"""FastAPI REST & WebSocket Telemetry Bridge Integration Tests."""

from __future__ import annotations

import os

from fastapi.testclient import TestClient

os.environ["HIL_DISABLE_BG"] = "1"
from backend_bridge.main import app, runtime  # noqa: E402


def test_backend_rest_and_live_hil_commands() -> None:
    with TestClient(app) as client:
        health = client.get("/api/health").json()
        assert health["status"] == "ok"

        bms = client.get("/api/benchmarks").json()
        assert len(bms) == 3

        bp = client.get("/api/blueprint").json()
        assert bp["blueprint"]["drc"]["passed"] is True
        assert "<svg" in bp["blueprint"]["svg_diagram"]
        assert "[env:native]" in bp["platformio_ini"]

        # Step virtual bridge synchronously and verify live setpoint + fault injection
        assert runtime.bridge is not None
        f1 = runtime.bridge.step_virtual_once()
        assert abs(f1.sp - 75.0) < 0.01

        res_cmd = client.post(
            "/api/control/command",
            json={"command": "SET", "param": "setpoint", "value": 81.5},
        )
        assert res_cmd.status_code == 200
        f2 = runtime.bridge.step_virtual_once()
        assert abs(f2.sp - 81.5) < 0.01

        res_fault = client.post("/api/hil/inject_fault", json={"sensor_disconnect": True})
        assert res_fault.status_code == 200
        f_fail = runtime.bridge.step_virtual_once()
        assert f_fail.state == "FAILSAFE"
        assert f_fail.out == 0.0

        res_restore = client.post(
            "/api/hil/inject_fault",
            json={"sensor_disconnect": False, "reset_fault": True},
        )
        assert res_restore.status_code == 200
        f_rec = runtime.bridge.step_virtual_once()
        assert f_rec.state == "AUTO"

        bundle = client.get("/api/export/bundle").json()
        assert "t_ms,sp,pv" in bundle["telemetry_csv"]

        # Switch project to Benchmark 2 Rover
        sw = client.post("/api/project/select", json={"project_id": "benchmark_2_rover"})
        assert sw.status_code == 200
        assert sw.json()["blueprint"]["project_id"] == "benchmark_2_rover"
