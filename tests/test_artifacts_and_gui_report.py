"""Verification tests for generated toolchain audit, SVGs, PlatformIO projects, and GUI audit."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_generated_artifacts_and_gui_audit_report() -> None:
    toolchain = json.loads((ROOT / "artifacts" / "toolchain_audit.json").read_text(encoding="utf-8"))
    assert toolchain["python_venv"]["installed"] is True
    assert toolchain["tools"]["g++"]["installed"] is True

    gui_report = json.loads(
        (ROOT / "artifacts" / "gui_audit" / "gui_audit_report.json").read_text(encoding="utf-8")
    )
    assert gui_report["passed"] is True
    assert gui_report["console_errors"] == []
    assert gui_report["failsafe_ui_latency_s"] < 1.0
    assert all(ev["failsafe_enabled"] is True for ev in gui_report["events"])

    for shot in (
        "01_live_oscilloscope_streaming.png",
        "02_setpoint_shift_tracked_response.png",
        "03_failsafe_sensor_disconnect.png",
        "04_sensor_restored_auto.png",
        "05_pinout_drc_svg_inspector.png",
    ):
        p = ROOT / "artifacts" / "gui_audit" / shot
        assert p.exists() and p.stat().st_size > 10_000

    for bm in ("benchmark_1_microclimate", "benchmark_2_rover", "benchmark_3_voice_display"):
        svg = ROOT / "artifacts" / "wiring" / f"{bm}_wiring.svg"
        pio = ROOT / "artifacts" / "firmware" / bm / "platformio.ini"
        assert svg.exists() and "<svg" in svg.read_text(encoding="utf-8")
        assert pio.exists() and "[env:native]" in pio.read_text(encoding="utf-8")
