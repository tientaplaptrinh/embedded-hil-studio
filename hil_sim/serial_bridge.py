"""Unified SerialBridge: Virtual HIL C++ Firmware Subprocess OR Physical PySerial COM Port."""

from __future__ import annotations

import math
import queue
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable, Literal

import serial

from contracts.hw_models import ControlCommand, TelemetryFrame
from fw_generator.protocol import build_command_line, parse_telemetry_line
from hil_sim.plants import (
    EdgeVoiceDisplayPlant,
    MicroclimateChamberPlant,
    Rover2DKinematicsPlant,
)

PlantType = MicroclimateChamberPlant | Rover2DKinematicsPlant | EdgeVoiceDisplayPlant


class SerialBridge:
    """Unified transport bridging either:
    1. Compiled C++17 native firmware binary coupled to a differential-equation physics plant (`virtual`), or
    2. Real ESP32 / Arduino hardware connected via USB-UART (`serial` via `pyserial`).
    """

    def __init__(
        self,
        mode: Literal["virtual", "serial"] = "virtual",
        *,
        firmware_binary: Path | None = None,
        plant: PlantType | None = None,
        dt_ms: int = 50,
        serial_port: str | None = None,
        baudrate: int = 115200,
    ) -> None:
        self.mode = mode
        self.firmware_binary = firmware_binary
        self.plant = plant
        self.dt_ms = dt_ms
        self.serial_port = serial_port
        self.baudrate = baudrate

        self._proc: subprocess.Popen[str] | None = None
        self._ser: serial.Serial | None = None
        self._cmd_queue: queue.Queue[str] = queue.Queue()
        self._last_frame: TelemetryFrame | None = None
        self._history: deque[TelemetryFrame] = deque(maxlen=1200)
        self._console_lines: deque[str] = deque(maxlen=400)
        self._listeners: list[Callable[[TelemetryFrame], None]] = []

        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def history(self) -> list[TelemetryFrame]:
        with self._lock:
            return list(self._history)

    @property
    def console_lines(self) -> list[str]:
        with self._lock:
            return list(self._console_lines)

    def add_listener(self, cb: Callable[[TelemetryFrame], None]) -> None:
        self._listeners.append(cb)

    def remove_listener(self, cb: Callable[[TelemetryFrame], None]) -> None:
        if cb in self._listeners:
            self._listeners.remove(cb)

    def start_subprocess_only(self) -> None:
        """Start the C++ firmware binary for synchronous deterministic HIL stepping."""
        if self.mode != "virtual":
            raise ValueError("start_subprocess_only is only valid in virtual mode.")
        if self.firmware_binary is None or not self.firmware_binary.exists():
            raise FileNotFoundError(f"Compiled firmware binary missing: {self.firmware_binary}")
        if self._proc is not None and self._proc.poll() is None:
            return
        self._proc = subprocess.Popen(
            [str(self.firmware_binary)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def stop(self) -> None:
        self._running = False
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

        if self._proc is not None:
            try:
                if self._proc.stdin and not self._proc.stdin.closed:
                    self._proc.stdin.write("QUIT\n")
                    self._proc.stdin.flush()
                self._proc.wait(timeout=1.5)
            except Exception:
                self._proc.kill()
            finally:
                self._proc = None

        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None

    def send_command(self, cmd: ControlCommand | str) -> str:
        wire = cmd if isinstance(cmd, str) else build_command_line(cmd)
        if not wire.endswith("\n"):
            wire += "\n"
        self._cmd_queue.put(wire)
        with self._lock:
            self._console_lines.append(f"TX >> {wire.strip()}")
        return wire.strip()

    def inject_fault(
        self,
        *,
        sensor_disconnect: bool | None = None,
        noise_spike: float | None = None,
        disturbance_rh_rate: float | None = None,
        actuator_cap: float | None = None,
    ) -> dict[str, object]:
        if self.plant is None:
            return {"status": "no_virtual_plant"}
        if sensor_disconnect is not None:
            self.plant.sensor_disconnected = sensor_disconnect
        if isinstance(self.plant, MicroclimateChamberPlant):
            if noise_spike is not None:
                self.plant.pending_noise_spike = noise_spike
            if disturbance_rh_rate is not None:
                self.plant.disturbance_rh_rate = disturbance_rh_rate
            if actuator_cap is not None:
                self.plant.actuator_saturation_cap = actuator_cap
        return {
            "sensor_disconnected": getattr(self.plant, "sensor_disconnected", False),
            "disturbance_rh_rate": getattr(self.plant, "disturbance_rh_rate", 0.0),
        }

    def step_virtual_once(self) -> TelemetryFrame:
        """Advance virtual plant + C++ firmware subprocess by one deterministic `dt_ms` tick."""
        if self._proc is None or self._proc.poll() is not None:
            self.start_subprocess_only()
        assert self._proc is not None and self._proc.stdin is not None and self._proc.stdout is not None
        assert self.plant is not None

        # Drain any queued runtime commands into firmware stdin first
        while not self._cmd_queue.empty():
            wire_cmd = self._cmd_queue.get_nowait()
            self._proc.stdin.write(wire_cmd)
            self._proc.stdin.flush()

        dt_s = self.dt_ms / 1000.0
        prev_out1 = self._last_frame.out if self._last_frame else 0.0
        prev_out2 = self._last_frame.out_secondary if self._last_frame else 0.0

        # Step physics plant using firmware's current actuator outputs
        if isinstance(self.plant, MicroclimateChamberPlant):
            self.plant.step(dt_s, prev_out1, prev_out2)
        elif isinstance(self.plant, Rover2DKinematicsPlant):
            self.plant.step(dt_s, prev_out1, prev_out2)
        elif isinstance(self.plant, EdgeVoiceDisplayPlant):
            self.plant.step(dt_s, prev_out1, prev_out2)

        v1, v2, valid = self.plant.read_sensors()
        v1_str = "nan" if math.isnan(v1) else f"{v1:.4f}"
        v2_str = "0.0" if math.isnan(v2) else f"{v2:.4f}"
        sens_line = f"SENS {self.dt_ms} {v1_str} {v2_str} {1 if valid else 0}\n"

        self._proc.stdin.write(sens_line)
        self._proc.stdin.flush()

        raw_out = self._proc.stdout.readline()
        if not raw_out:
            raise RuntimeError("C++ HIL firmware subprocess closed stdout unexpectedly.")

        frame = parse_telemetry_line(raw_out)
        if frame is None:
            raise RuntimeError(f"Invalid telemetry line from firmware: {raw_out!r}")

        # Attach rich plant state metadata for UI visualizations
        if isinstance(self.plant, Rover2DKinematicsPlant):
            frame.extra["x_cm"] = round(self.plant.state.x_cm, 2)
            frame.extra["y_cm"] = round(self.plant.state.y_cm, 2)
            frame.extra["theta_rad"] = round(self.plant.state.theta_rad, 3)
            frame.extra["collisions"] = self.plant.state.collisions

        with self._lock:
            self._last_frame = frame
            self._history.append(frame)
            self._console_lines.append(f"RX << {frame.raw_line}")

        for cb in list(self._listeners):
            try:
                cb(frame)
            except Exception:
                pass
        return frame

    def start_realtime_background(self, hz: float = 30.0) -> None:
        """Run continuous real-time telemetry loop (30-60 Hz) in a background daemon thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._realtime_loop, args=(hz,), daemon=True)
        self._thread.start()

    def _realtime_loop(self, hz: float) -> None:
        interval = 1.0 / max(5.0, min(hz, 100.0))
        if self.mode == "virtual":
            self.start_subprocess_only()
            while self._running:
                t0 = time.perf_counter()
                try:
                    self.step_virtual_once()
                except Exception as exc:
                    with self._lock:
                        self._console_lines.append(f"ERR !! {exc}")
                    time.sleep(0.2)
                elapsed = time.perf_counter() - t0
                if elapsed < interval:
                    time.sleep(interval - elapsed)
        else:
            # Real Hardware PySerial COM Mode with auto-reconnect
            while self._running:
                if self._ser is None or not self._ser.is_open:
                    try:
                        if not self.serial_port:
                            raise RuntimeError("HIL_SERIAL_PORT not specified")
                        self._ser = serial.Serial(
                            port=self.serial_port,
                            baudrate=self.baudrate,
                            timeout=0.1,
                        )
                        with self._lock:
                            self._console_lines.append(
                                f"SYS :: Connected to {self.serial_port} @ {self.baudrate} baud"
                            )
                    except Exception as exc:
                        with self._lock:
                            self._console_lines.append(f"SERIAL_WAIT :: {exc}")
                        time.sleep(1.0)
                        continue

                try:
                    while not self._cmd_queue.empty():
                        cmd_line = self._cmd_queue.get_nowait()
                        self._ser.write(cmd_line.encode("utf-8"))
                        self._ser.flush()

                    raw_bytes = self._ser.readline()
                    if raw_bytes:
                        decoded = raw_bytes.decode("utf-8", errors="replace")
                        frame = parse_telemetry_line(decoded)
                        if frame is not None:
                            with self._lock:
                                self._last_frame = frame
                                self._history.append(frame)
                                self._console_lines.append(f"RX << {frame.raw_line}")
                            for cb in list(self._listeners):
                                try:
                                    cb(frame)
                                except Exception:
                                    pass
                except serial.SerialException as exc:
                    with self._lock:
                        self._console_lines.append(f"SERIAL_LOST :: {exc} (reconnecting...)")
                    try:
                        self._ser.close()
                    except Exception:
                        pass
                    self._ser = None
                    time.sleep(0.5)
