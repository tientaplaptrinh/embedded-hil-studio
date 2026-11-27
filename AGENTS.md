# Embedded Hardware Architect & Serial HIL Debugger (`embedded_hil_studio`)

## Architecture Overview
This monorepo implements an autonomous 4-stage Embedded Hardware & Firmware Verification Studio:
1. **`contracts/`**: Strict Pydantic v2 data contracts (`hw_models.py`) shared across solver, DRC, firmware synthesizer, HIL simulator, and FastAPI/WebSocket bridge.
2. **`hw_architect/`**: Accurate MCU pin capability databases (`ESP32 DevKit V1`, `ESP32-S3 DevKitC-1`, `Arduino Uno`), backtracking constraint pin solver, electrical Design Rule Checker (DRC) + battery/power runtime estimator, and annotated vector SVG wiring & BOM generator.
3. **`fw_generator/`**: Modular C++17 PlatformIO synthesizer emitting decoupled Control Core (`controller_core.hpp/.cpp`) and HAL (`hal.hpp`) with CRC-16 framed JSON telemetry, non-blocking `millis()` scheduling, safety interlocks, and dual `native` + MCU build/test targets.
4. **`hil_sim/`**: Closed-loop Hardware-in-the-Loop physics engine (`microclimate_chamber.py`, `rover_2d_kinematics.py`) and unified `SerialBridge` supporting both compiled native firmware subprocesses and physical `pyserial` USB COM hardware, plus automated fault injection (`stress_runner.py`).
5. **`backend_bridge/` & `web_hil_dashboard/`**: FastAPI REST + WebSocket live telemetry hub and dark-mode React + Vite + TypeScript + Tailwind Serial Oscilloscope, Pinout/DRC Inspector, and Live PID/Fault Tuner.

## Safety Rules for Desktop GUI Automation
- Always set `pyautogui.FAILSAFE = True` before any mouse/keyboard operation.
- Confine all automated pointer/key actions strictly within the bounds of the dedicated isolated test browser window.
- Record every GUI action and verification screenshot in `./artifacts/gui_audit/`.

## Common Commands
- Run full pytest suite: `.venv/Scripts/pytest -q`
- Run all 3 benchmarks end-to-end: `.venv/Scripts/python -m hil_sim.stress_runner`
- Start backend in HIL virtual mode: `.venv/Scripts/uvicorn backend_bridge.main:app --host 127.0.0.1 --port 8765`
- Start backend on real USB COM port: `$env:HIL_MODE="serial"; $env:HIL_SERIAL_PORT="COM5"; $env:HIL_BAUD="115200"; .venv/Scripts/uvicorn backend_bridge.main:app --host 127.0.0.1 --port 8765`
