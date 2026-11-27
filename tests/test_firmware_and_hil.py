"""End-to-end tests for C++17 Firmware Synthesis, CRC-16 Protocol, and Closed-Loop HIL Benchmarks."""

from __future__ import annotations

from fw_generator import crc16_ccitt, format_framed_json, parse_telemetry_line
from hil_sim.stress_runner import execute_full_benchmark_suite


def test_crc16_framed_protocol_roundtrip_and_corruption_detection() -> None:
    assert crc16_ccitt(b"123456789") == 0x29B1
    wire = format_framed_json(
        {
            "t_ms": 250,
            "sp": 75.0,
            "pv": 68.4,
            "pv2": 25.1,
            "out": 52.3,
            "out2": 6.0,
            "state": "AUTO",
            "fault": 0,
        }
    )
    frame = parse_telemetry_line(wire)
    assert frame is not None
    assert frame.crc_ok
    assert frame.t_ms == 250
    assert abs(frame.pv - 68.4) < 1e-6

    # Flip one digit -> CRC check must catch corruption
    corrupted = wire.replace("68.4", "69.4")
    bad_frame = parse_telemetry_line(corrupted)
    assert bad_frame is not None
    assert not bad_frame.crc_ok


def test_all_three_benchmarks_pass_build_and_closed_loop_hil() -> None:
    results = execute_full_benchmark_suite()
    assert len(results) == 3

    by_id = {r["project_id"]: r for r in results}

    b1 = by_id["benchmark_1_microclimate"]
    assert b1["firmware_build"]["unit_tests_passed"]
    assert b1["firmware_build"]["mcu_syntax_verified"]
    assert b1["hil_result"]["passed"], f"B1 HIL failed: {b1['hil_result']}"
    assert b1["hil_result"]["steady_state_error"] <= 2.0
    assert b1["hil_result"]["failsafe_latency_ms"] < 500.0

    b2 = by_id["benchmark_2_rover"]
    assert b2["firmware_build"]["unit_tests_passed"]
    assert b2["hil_result"]["passed"], f"B2 HIL failed: {b2['hil_result']}"
    assert b2["hil_result"]["collisions"] == 0
    assert b2["hil_result"]["mode_switch_verified"]

    b3 = by_id["benchmark_3_voice_display"]
    assert b3["firmware_build"]["unit_tests_passed"]
    assert b3["hil_result"]["passed"], f"B3 HIL failed: {b3['hil_result']}"
