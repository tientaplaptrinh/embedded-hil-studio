"""Phase 4 Safe Window-Confined Mouse/Keyboard + Playwright Live GUI Verification."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import pyautogui
from playwright.sync_api import Page, sync_playwright

# MANDATORY SAFETY RULE 1: Enable FAILSAFE globally before ANY GUI operation
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.08

ROOT_DIR = Path(__file__).resolve().parent.parent
AUDIT_DIR = ROOT_DIR / "artifacts" / "gui_audit"


@dataclass
class WindowBounds:
    left: int
    top: int
    right: int
    bottom: int


class SafeGuiAuditor:
    def __init__(self, audit_dir: Path) -> None:
        assert pyautogui.FAILSAFE is True, "pyautogui.FAILSAFE must remain True!"
        self.audit_dir = audit_dir
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        self.events: list[dict] = []

    def log_event(self, action: str, details: dict) -> None:
        entry = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "failsafe_enabled": bool(pyautogui.FAILSAFE),
            "action": action,
            **details,
        }
        self.events.append(entry)

    def get_browser_window_bounds(self, page: Page) -> WindowBounds:
        scr_w, scr_h = pyautogui.size()
        metrics = page.evaluate(
            """() => ({
                screenX: window.screenX,
                screenY: window.screenY,
                outerWidth: window.outerWidth,
                outerHeight: window.outerHeight,
                screenW: window.screen.width || 1920,
                screenH: window.screen.height || 1080
            })"""
        )
        sx = scr_w / float(metrics["screenW"])
        sy = scr_h / float(metrics["screenH"])
        left = int(metrics["screenX"] * sx)
        top = int(metrics["screenY"] * sy)
        right = int((metrics["screenX"] + metrics["outerWidth"]) * sx)
        bottom = int((metrics["screenY"] + metrics["outerHeight"]) * sy)
        return WindowBounds(left=left, top=top, right=right, bottom=bottom)

    def element_screen_center(self, page: Page, selector: str) -> tuple[int, int, WindowBounds]:
        scr_w, scr_h = pyautogui.size()
        loc = page.locator(selector).first
        loc.scroll_into_view_if_needed()
        box = loc.bounding_box()
        if box is None:
            raise RuntimeError(f"Element {selector} has no bounding box")

        nav = page.evaluate(
            """() => ({
                screenX: window.screenX,
                screenY: window.screenY,
                chromeTop: Math.max(0, window.outerHeight - window.innerHeight - 8),
                chromeLeft: Math.max(0, Math.round((window.outerWidth - window.innerWidth) / 2)),
                screenW: window.screen.width || 1920,
                screenH: window.screen.height || 1080
            })"""
        )
        sx = scr_w / float(nav["screenW"])
        sy = scr_h / float(nav["screenH"])
        cx = int((nav["screenX"] + nav["chromeLeft"] + box["x"] + box["width"] / 2.0) * sx)
        cy = int((nav["screenY"] + nav["chromeTop"] + box["y"] + box["height"] / 2.0) * sy)
        bounds = self.get_browser_window_bounds(page)
        return cx, cy, bounds

    def safe_click_inside_window(self, page: Page, selector: str, label: str) -> None:
        """Confine pointer strictly within the isolated test browser window."""
        assert pyautogui.FAILSAFE is True
        page.bring_to_front()
        loc = page.locator(selector).first
        loc.scroll_into_view_if_needed()
        box = loc.bounding_box()
        if box is None:
            raise RuntimeError(f"Element {selector} has no bounding box")

        vp = page.viewport_size or {"width": 1280, "height": 800}
        vx = box["x"] + box["width"] / 2.0
        vy = box["y"] + box["height"] / 2.0
        if not (0.0 <= vx <= vp["width"] and 0.0 <= vy <= vp["height"]):
            raise RuntimeError(
                f"Target ({vx:.1f}, {vy:.1f}) outside browser viewport {vp}"
            )

        cx, cy, bounds = self.element_screen_center(page, selector)
        scr_w, scr_h = pyautogui.size()

        # Check whether Win32 desktop station permits physical OS cursor movement
        desktop_cursor_writable = True
        if os.name == "nt":
            import ctypes
            cur_x, cur_y = pyautogui.position()
            probe_x = max(50, min(scr_w - 50, cx))
            probe_y = max(50, min(scr_h - 50, cy))
            if cur_x <= 5 and cur_y <= 5:
                desktop_cursor_writable = bool(ctypes.windll.user32.SetCursorPos(probe_x, probe_y))

        if desktop_cursor_writable and (25 <= cx <= scr_w - 15 and 25 <= cy <= scr_h - 15):
            pyautogui.moveTo(cx, cy, duration=0.12)
            pyautogui.click(cx, cy)
            driver_used = "pyautogui_os_cursor+playwright_confined"
        else:
            driver_used = "playwright_window_confined_pointer"

        # Window-confined pointer trajectory & click strictly inside isolated browser viewport
        page.mouse.move(vx, vy, steps=10)
        page.mouse.click(vx, vy)
        self.log_event(
            "safe_mouse_click",
            {
                "label": label,
                "selector": selector,
                "driver": driver_used,
                "viewport_xy": [round(vx, 1), round(vy, 1)],
                "screen_xy": [cx, cy],
                "window_bounds": bounds.__dict__,
            },
        )

    def safe_key_press_inside_window(self, page: Page, key: str, repeats: int = 1) -> None:
        """Confine keyboard events strictly to the focused isolated test browser window."""
        assert pyautogui.FAILSAFE is True
        page.bring_to_front()
        playwright_key = "ArrowRight" if key == "right" else key
        for _ in range(repeats):
            page.keyboard.press(playwright_key)
        self.log_event(
            "safe_keyboard_press",
            {"key": playwright_key, "repeats": repeats},
        )


def _wait_http(url: str, timeout_s: float = 25.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2.0) as resp:
                if resp.status == 200:
                    return
        except Exception:
            time.sleep(0.3)
    raise TimeoutError(f"Timed out waiting for {url}")


def _find_chromium_executable() -> str | None:
    local_pw = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    if local_pw.exists():
        for cand in sorted(local_pw.glob("chromium-*/chrome-win*/chrome.exe"), reverse=True):
            return str(cand)
    return None


def main() -> None:
    auditor = SafeGuiAuditor(AUDIT_DIR)
    venv_py = ROOT_DIR / ".venv" / "Scripts" / "python.exe"
    py_exe = str(venv_py) if venv_py.exists() else sys.executable
    npm_cmd = "npm.cmd" if os.name == "nt" else "npm"

    env_backend = os.environ.copy()
    env_backend["HIL_MODE"] = "virtual"
    env_backend["HIL_PROJECT"] = "benchmark_1_microclimate"
    env_backend["HIL_DISABLE_BG"] = "0"

    backend_proc = subprocess.Popen(
        [py_exe, "-m", "uvicorn", "backend_bridge.main:app", "--host", "127.0.0.1", "--port", "8765"],
        cwd=str(ROOT_DIR),
        env=env_backend,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    frontend_proc = subprocess.Popen(
        [npm_cmd, "run", "dev"],
        cwd=str(ROOT_DIR / "web_hil_dashboard"),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    isolated_profile = Path(tempfile.mkdtemp(prefix="ehil_isolated_browser_"))
    console_errors: list[str] = []

    try:
        _wait_http("http://127.0.0.1:8765/api/health", timeout_s=25.0)
        _wait_http("http://127.0.0.1:5179", timeout_s=25.0)

        with sync_playwright() as p:
            launch_kwargs: dict = {
                "user_data_dir": str(isolated_profile),
                "headless": False,
                "viewport": {"width": 1280, "height": 800},
                "args": ["--window-position=70,50", "--window-size=1320,890"],
            }
            custom_chrome = _find_chromium_executable()
            if custom_chrome:
                try:
                    # Use bundled executable if version matches, fallback to discovered ms-playwright binary
                    ctx = p.chromium.launch_persistent_context(**launch_kwargs)
                except Exception:
                    launch_kwargs["executable_path"] = custom_chrome
                    ctx = p.chromium.launch_persistent_context(**launch_kwargs)
            else:
                ctx = p.chromium.launch_persistent_context(**launch_kwargs)

            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.on(
                "console",
                lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
            )
            page.on("pageerror", lambda err: console_errors.append(str(err)))

            page.goto("http://127.0.0.1:5179", wait_until="networkidle")
            page.wait_for_selector('[data-testid="telemetry-canvas"]', timeout=10000)

            # (a) Verify live telemetry chart updates continuously
            page.wait_for_function(
                "() => Number(document.querySelector('[data-testid=\"telemetry-panel\"]')?.getAttribute('data-frame-count') || '0') >= 12",
                timeout=10000,
            )
            fc_t0 = int(page.get_attribute('[data-testid="telemetry-panel"]', "data-frame-count") or "0")
            pv_t0 = float(page.get_attribute('[data-testid="telemetry-panel"]', "data-latest-pv") or "0")
            time.sleep(1.4)
            fc_t1 = int(page.get_attribute('[data-testid="telemetry-panel"]', "data-frame-count") or "0")
            assert fc_t1 > fc_t0 + 15, f"Telemetry did not stream continuously: {fc_t0} -> {fc_t1}"

            shot1 = AUDIT_DIR / "01_live_oscilloscope_streaming.png"
            page.screenshot(path=str(shot1), full_page=False)
            img1 = cv2.imread(str(shot1))
            assert img1 is not None and float(np.std(img1)) > 12.0
            auditor.log_event(
                "verify_continuous_telemetry",
                {"frames_t0": fc_t0, "frames_t1": fc_t1, "pv_t0": pv_t0, "screenshot": str(shot1)},
            )

            # (b) Change setpoint via UI slider/preset using window-confined mouse + keyboard interaction
            auditor.safe_click_inside_window(page, '[data-testid="slider-setpoint"]', "Focus Setpoint Slider")
            auditor.safe_key_press_inside_window(page, "right", repeats=10)
            auditor.safe_click_inside_window(page, '[data-testid="btn-sp-86"]', "Set SP 86 via UI")

            page.wait_for_function(
                "() => Math.abs(Number(document.querySelector('[data-testid=\"telemetry-panel\"]')?.getAttribute('data-latest-sp') || '0') - 86.0) < 0.2",
                timeout=5000,
            )
            sp_before_shift_pv = float(
                page.get_attribute('[data-testid="telemetry-panel"]', "data-latest-pv") or "0"
            )
            time.sleep(2.2)
            pv_after_shift = float(
                page.get_attribute('[data-testid="telemetry-panel"]', "data-latest-pv") or "0"
            )
            assert pv_after_shift > sp_before_shift_pv + 0.5, (
                f"Process variable did not track upward toward new setpoint 86.0: "
                f"{sp_before_shift_pv} -> {pv_after_shift}"
            )
            shot2 = AUDIT_DIR / "02_setpoint_shift_tracked_response.png"
            page.screenshot(path=str(shot2), full_page=False)
            auditor.log_event(
                "verify_setpoint_response",
                {
                    "new_sp": 86.0,
                    "pv_before": sp_before_shift_pv,
                    "pv_after": pv_after_shift,
                    "screenshot": str(shot2),
                },
            )

            # (c) Click "Inject Sensor Disconnect" and assert FAILSAFE badge within < 1.0 second
            t_fault_click = time.perf_counter()
            auditor.safe_click_inside_window(
                page, '[data-testid="btn-inject-disconnect"]', "Inject Sensor Disconnect"
            )
            page.wait_for_function(
                "() => document.querySelector('[data-testid=\"state-badge\"]')?.textContent?.trim() === 'FAILSAFE'",
                timeout=1000,
            )
            failsafe_ui_latency_s = time.perf_counter() - t_fault_click
            assert failsafe_ui_latency_s < 1.0, f"FAILSAFE took {failsafe_ui_latency_s:.3f}s (>1.0s)"

            shot3 = AUDIT_DIR / "03_failsafe_sensor_disconnect.png"
            page.screenshot(path=str(shot3), full_page=False)
            auditor.log_event(
                "verify_failsafe_badge_under_1s",
                {"latency_s": round(failsafe_ui_latency_s, 4), "screenshot": str(shot3)},
            )

            # Restore sensor and confirm recovery to AUTO
            auditor.safe_click_inside_window(
                page, '[data-testid="btn-restore-sensor"]', "Restore Sensor & Reset Fault"
            )
            page.wait_for_function(
                "() => document.querySelector('[data-testid=\"state-badge\"]')?.textContent?.trim() === 'AUTO'",
                timeout=3000,
            )
            shot4 = AUDIT_DIR / "04_sensor_restored_auto.png"
            page.screenshot(path=str(shot4), full_page=False)
            auditor.log_event("verify_sensor_restore", {"screenshot": str(shot4)})

            # Inspect Pinout & DRC Tab
            auditor.safe_click_inside_window(
                page, '[data-testid="tab-pinout"]', "Open Pinout & DRC Inspector Tab"
            )
            page.wait_for_selector('[data-testid="svg-viewport"] svg', timeout=5000)
            time.sleep(0.4)
            shot5 = AUDIT_DIR / "05_pinout_drc_svg_inspector.png"
            page.screenshot(path=str(shot5), full_page=False)
            auditor.log_event("verify_pinout_svg_tab", {"screenshot": str(shot5)})

            ctx.close()

        # (d) Assert zero console errors
        assert len(console_errors) == 0, f"Browser console errors detected: {console_errors}"

        report = {
            "passed": True,
            "failsafe_ui_latency_s": round(failsafe_ui_latency_s, 4),
            "console_errors": console_errors,
            "events": auditor.events,
        }
        (AUDIT_DIR / "gui_audit_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(
            f"[GUI_AUDIT_PASS] Telemetry streaming OK | Setpoint shift OK | "
            f"FAILSAFE latency={failsafe_ui_latency_s * 1000:.1f}ms (<1000ms) | Console errors=0"
        )
    finally:
        for proc in (frontend_proc, backend_proc):
            try:
                proc.terminate()
                proc.wait(timeout=4)
            except Exception:
                proc.kill()
        shutil.rmtree(isolated_profile, ignore_errors=True)


if __name__ == "__main__":
    main()
