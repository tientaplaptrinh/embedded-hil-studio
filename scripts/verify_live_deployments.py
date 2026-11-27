"""Verify live public HTTPS deployments (Cloudflare Full-Stack Tunnel + GitHub Pages 24/7)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright

ROOT_DIR = Path(__file__).resolve().parent.parent
AUDIT_DIR = ROOT_DIR / "artifacts" / "gui_audit"


def wait_public_url(url: str, timeout_s: float = 90.0) -> bool:
    deadline = time.time() + timeout_s
    req_headers = {"User-Agent": "Mozilla/5.0 EmbeddedHILVerifier/1.0"}
    while time.time() < deadline:
        try:
            req = urllib.request.Request(url, headers=req_headers)
            with urllib.request.urlopen(req, timeout=8.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(3.0)
    return False


def find_chromium_executable() -> str | None:
    local_pw = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    if local_pw.exists():
        for cand in sorted(local_pw.glob("chromium-*/chrome-win*/chrome.exe"), reverse=True):
            return str(cand)
    return None


def verify_url_in_browser(url: str, screenshot_name: str, expected_badge_substr: str) -> dict:
    profile = Path(tempfile.mkdtemp(prefix="ehil_deploy_check_"))
    console_errors: list[str] = []
    try:
        with sync_playwright() as p:
            kwargs: dict = {
                "user_data_dir": str(profile),
                "headless": True,
                "viewport": {"width": 1360, "height": 860},
            }
            chrome_exe = find_chromium_executable()
            try:
                ctx = p.chromium.launch_persistent_context(**kwargs)
            except Exception:
                if chrome_exe:
                    kwargs["executable_path"] = chrome_exe
                ctx = p.chromium.launch_persistent_context(**kwargs)

            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.on(
                "console",
                lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
            )
            page.on("pageerror", lambda err: console_errors.append(str(err)))

            page.goto(url, wait_until="networkidle", timeout=35000)
            page.wait_for_selector('[data-testid="telemetry-canvas"]', timeout=15000)
            page.wait_for_function(
                "() => Number(document.querySelector('[data-testid=\"telemetry-panel\"]')?.getAttribute('data-frame-count') || '0') >= 12",
                timeout=15000,
            )
            fc = int(page.get_attribute('[data-testid="telemetry-panel"]', "data-frame-count") or "0")
            badge = (page.text_content('[data-testid="transport-badge"]') or "").strip()

            shot_path = AUDIT_DIR / screenshot_name
            page.screenshot(path=str(shot_path), full_page=False)
            ctx.close()

        return {
            "url": url,
            "reachable": True,
            "frames_streamed": fc,
            "transport_badge": badge,
            "badge_matched": expected_badge_substr in badge,
            "console_errors": console_errors,
            "screenshot": str(shot_path),
        }
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def main() -> None:
    urls_path = ROOT_DIR / "artifacts" / "public_web_urls.json"
    if not urls_path.exists():
        print("Missing artifacts/public_web_urls.json", file=sys.stderr)
        sys.exit(1)

    urls = json.loads(urls_path.read_text(encoding="utf-8"))
    results = {}

    cf_url = urls.get("cloudflare_tunnel_url")
    if cf_url:
        ok = wait_public_url(f"{cf_url}/api/health", timeout_s=45.0)
        if not ok:
            raise RuntimeError(f"Cloudflare tunnel URL did not become healthy: {cf_url}")
        results["cloudflare_fullstack"] = verify_url_in_browser(
            cf_url, "deploy_01_cloudflare_fullstack_live.png", "HIL VIRTUAL SIM"
        )

    gh_url = urls.get("github_pages_url")
    if gh_url:
        ok = wait_public_url(gh_url, timeout_s=95.0)
        if not ok:
            raise RuntimeError(f"GitHub Pages URL not yet live: {gh_url}")
        results["github_pages_24x7"] = verify_url_in_browser(
            gh_url, "deploy_02_github_pages_24x7_live.png", "CLOUD WEB-HIL SIM"
        )

    out_report = AUDIT_DIR / "live_deployment_verification.json"
    out_report.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))

    for key, val in results.items():
        if val["console_errors"]:
            raise AssertionError(f"Console errors on {key}: {val['console_errors']}")
        if val["frames_streamed"] < 12:
            raise AssertionError(f"Insufficient frames on {key}: {val}")


if __name__ == "__main__":
    main()
