"""FastAPI + WebSocket Telemetry Hub & Live Hardware/Firmware Lab Controller."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from contracts.hw_models import (
    ControlCommand,
    DrcReport,
    EmbeddedProjectSpec,
    HardwareBlueprint,
    TelemetryFrame,
)
from fw_generator import compile_and_verify_firmware, synthesize_firmware_project
from hil_sim.plants import (
    EdgeVoiceDisplayPlant,
    MicroclimateChamberPlant,
    Rover2DKinematicsPlant,
)
from hil_sim.serial_bridge import PlantType, SerialBridge
from hil_sim.stress_runner import ARTIFACTS_DIR, load_benchmark_specs
from hw_architect import architect_project


class ProjectSelectRequest(BaseModel):
    project_id: str


class FaultInjectRequest(BaseModel):
    sensor_disconnect: bool | None = None
    noise_spike: float | None = None
    disturbance_rh_rate: float | None = None
    actuator_cap: float | None = None
    reset_fault: bool = False


class TransportSwitchRequest(BaseModel):
    mode: Literal["virtual", "serial"]
    serial_port: str | None = None
    baudrate: int = 115200


class StudioRuntime:
    def __init__(self) -> None:
        self.specs: dict[str, EmbeddedProjectSpec] = {
            s.project_id: s for s in load_benchmark_specs()
        }
        self.active_project_id: str = os.environ.get("HIL_PROJECT", "benchmark_1_microclimate")
        if self.active_project_id not in self.specs:
            self.active_project_id = "benchmark_1_microclimate"

        self.mode: Literal["virtual", "serial"] = (
            "serial" if os.environ.get("HIL_MODE", "virtual").lower() == "serial" else "virtual"
        )
        self.serial_port: str | None = os.environ.get("HIL_SERIAL_PORT")
        self.baudrate: int = int(os.environ.get("HIL_BAUD", "115200"))

        self.initial_drc: DrcReport | None = None
        self.blueprint: HardwareBlueprint | None = None
        self.platformio_ini: str = ""
        self.pin_config_hpp: str = ""
        self.bridge: SerialBridge | None = None

        self._ws_queues: set[asyncio.Queue[TelemetryFrame]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def _make_plant(self, spec: EmbeddedProjectSpec) -> PlantType:
        if spec.control.archetype == "microclimate_pid":
            return MicroclimateChamberPlant(seed=42)
        if spec.control.archetype == "rover_obstacle_fsm":
            return Rover2DKinematicsPlant(seed=7)
        return EdgeVoiceDisplayPlant(seed=19)

    def _on_frame(self, frame: TelemetryFrame) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        for q in list(self._ws_queues):
            loop.call_soon_threadsafe(self._push_nonblocking, q, frame)

    @staticmethod
    def _push_nonblocking(q: asyncio.Queue[TelemetryFrame], frame: TelemetryFrame) -> None:
        if q.full():
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            q.put_nowait(frame)
        except asyncio.QueueFull:
            pass

    def activate_project(
        self,
        project_id: str,
        *,
        start_background: bool = True,
    ) -> None:
        if project_id not in self.specs:
            raise KeyError(f"Unknown project_id '{project_id}'")

        if self.bridge is not None:
            self.bridge.stop()
            self.bridge = None

        spec = self.specs[project_id]
        self.active_project_id = project_id
        initial_drc, blueprint = architect_project(spec, auto_repair=True)
        self.initial_drc = initial_drc
        self.blueprint = blueprint

        fw_root = ARTIFACTS_DIR / "firmware"
        svg_dir = ARTIFACTS_DIR / "wiring"
        fw_root.mkdir(parents=True, exist_ok=True)
        svg_dir.mkdir(parents=True, exist_ok=True)
        (svg_dir / f"{spec.project_id}_wiring.svg").write_text(blueprint.svg_diagram, encoding="utf-8")
        (svg_dir / f"{spec.project_id}_bom.md").write_text(blueprint.wiring_markdown, encoding="utf-8")

        proj_dir = synthesize_firmware_project(spec, blueprint, fw_root)
        self.platformio_ini = (proj_dir / "platformio.ini").read_text(encoding="utf-8")
        self.pin_config_hpp = (proj_dir / "include" / "pin_config.hpp").read_text(encoding="utf-8")

        fw_res = compile_and_verify_firmware(proj_dir, try_pio_native=False)
        dt_ms = max(20, int(round(1000.0 / spec.control.loop_hz)))

        if self.mode == "virtual":
            plant = self._make_plant(spec)
            self.bridge = SerialBridge(
                mode="virtual",
                firmware_binary=fw_res.hil_firmware_binary,
                plant=plant,
                dt_ms=dt_ms,
            )
        else:
            self.bridge = SerialBridge(
                mode="serial",
                serial_port=self.serial_port,
                baudrate=self.baudrate,
                dt_ms=dt_ms,
            )

        self.bridge.add_listener(self._on_frame)
        if start_background:
            # Stream at 35 Hz for smooth 30-60 FPS live oscilloscope rendering
            self.bridge.start_realtime_background(hz=35.0)

    def shutdown(self) -> None:
        if self.bridge is not None:
            self.bridge.stop()
            self.bridge = None


runtime = StudioRuntime()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    runtime._loop = asyncio.get_running_loop()
    start_bg = os.environ.get("HIL_DISABLE_BG", "0") != "1"
    runtime.activate_project(runtime.active_project_id, start_background=start_bg)
    try:
        yield
    finally:
        runtime.shutdown()


app = FastAPI(
    title="Embedded Hardware Architect & Serial HIL Studio API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def get_health() -> dict[str, object]:
    return {
        "status": "ok",
        "mode": runtime.mode,
        "serial_port": runtime.serial_port,
        "baudrate": runtime.baudrate,
        "active_project_id": runtime.active_project_id,
    }


@app.get("/api/benchmarks")
def list_benchmarks() -> list[dict[str, object]]:
    return [
        {
            "project_id": s.project_id,
            "name": s.name,
            "board_id": s.board_id,
            "description": s.description,
            "control": s.control.model_dump(),
        }
        for s in runtime.specs.values()
    ]


@app.get("/api/blueprint")
def get_blueprint() -> dict[str, object]:
    if runtime.blueprint is None or runtime.initial_drc is None:
        runtime.activate_project(runtime.active_project_id, start_background=False)
    assert runtime.blueprint is not None and runtime.initial_drc is not None
    spec = runtime.specs[runtime.active_project_id]
    sensor_disc = False
    if runtime.bridge and runtime.bridge.plant is not None:
        sensor_disc = getattr(runtime.bridge.plant, "sensor_disconnected", False)

    return {
        "mode": runtime.mode,
        "serial_port": runtime.serial_port,
        "baudrate": runtime.baudrate,
        "spec": spec.model_dump(),
        "initial_drc": runtime.initial_drc.model_dump(),
        "blueprint": runtime.blueprint.model_dump(),
        "platformio_ini": runtime.platformio_ini,
        "pin_config_hpp": runtime.pin_config_hpp,
        "fault_state": {"sensor_disconnected": sensor_disc},
    }


@app.post("/api/project/select")
def select_project(req: ProjectSelectRequest) -> dict[str, object]:
    if req.project_id not in runtime.specs:
        raise HTTPException(status_code=404, detail=f"Benchmark '{req.project_id}' not found.")
    start_bg = os.environ.get("HIL_DISABLE_BG", "0") != "1"
    runtime.activate_project(req.project_id, start_background=start_bg)
    return get_blueprint()


@app.post("/api/control/command")
def push_control_command(cmd: ControlCommand) -> dict[str, object]:
    if runtime.bridge is None:
        raise HTTPException(status_code=503, detail="SerialBridge is not initialized.")
    sent = runtime.bridge.send_command(cmd)
    return {"status": "sent", "wire_line": sent}


@app.post("/api/hil/inject_fault")
def inject_hil_fault(req: FaultInjectRequest) -> dict[str, object]:
    if runtime.bridge is None:
        raise HTTPException(status_code=503, detail="SerialBridge is not initialized.")
    info = runtime.bridge.inject_fault(
        sensor_disconnect=req.sensor_disconnect,
        noise_spike=req.noise_spike,
        disturbance_rh_rate=req.disturbance_rh_rate,
        actuator_cap=req.actuator_cap,
    )
    if req.reset_fault or req.sensor_disconnect is False:
        runtime.bridge.send_command("FAULT_RESET")
    return {"status": "updated", **info}


@app.post("/api/transport/mode")
def switch_transport_mode(req: TransportSwitchRequest) -> dict[str, object]:
    runtime.mode = req.mode
    runtime.serial_port = req.serial_port
    runtime.baudrate = req.baudrate
    start_bg = os.environ.get("HIL_DISABLE_BG", "0") != "1"
    runtime.activate_project(runtime.active_project_id, start_background=start_bg)
    return {
        "status": "switched",
        "mode": runtime.mode,
        "serial_port": runtime.serial_port,
        "baudrate": runtime.baudrate,
    }


@app.get("/api/console")
def get_serial_console() -> dict[str, object]:
    lines = runtime.bridge.console_lines if runtime.bridge else []
    return {"lines": lines[-150:]}


@app.get("/api/export/bundle")
def export_bundle() -> dict[str, object]:
    if runtime.blueprint is None:
        raise HTTPException(status_code=503, detail="No active blueprint.")
    hist = runtime.bridge.history if runtime.bridge else []
    csv_rows = ["t_ms,sp,pv,pv_secondary,out,out_secondary,state,fault,crc_ok"]
    for f in hist:
        csv_rows.append(
            f"{f.t_ms},{f.sp:.2f},{f.pv:.2f},{f.pv_secondary:.2f},"
            f"{f.out:.2f},{f.out_secondary:.2f},{f.state},{f.fault},{int(f.crc_ok)}"
        )
    return {
        "project_id": runtime.active_project_id,
        "platformio_ini": runtime.platformio_ini,
        "pin_config_hpp": runtime.pin_config_hpp,
        "wiring_markdown": runtime.blueprint.wiring_markdown,
        "svg_diagram": runtime.blueprint.svg_diagram,
        "telemetry_csv": "\n".join(csv_rows),
    }


@app.websocket("/ws/telemetry")
async def websocket_telemetry(ws: WebSocket) -> None:
    await ws.accept()
    q: asyncio.Queue[TelemetryFrame] = asyncio.Queue(maxsize=120)
    runtime._ws_queues.add(q)
    try:
        if runtime.bridge is not None:
            recent = [f.model_dump() for f in runtime.bridge.history[-160:]]
            await ws.send_json({"type": "history", "frames": recent})
        while True:
            frame = await q.get()
            await ws.send_json({"type": "telemetry", "frame": frame.model_dump()})
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        runtime._ws_queues.discard(q)


_WEB_DIST = Path(__file__).resolve().parent.parent / "web_hil_dashboard" / "dist"
if _WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=str(_WEB_DIST), html=True), name="web_hil_dashboard")

