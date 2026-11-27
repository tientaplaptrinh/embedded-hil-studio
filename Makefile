PYTHON := .venv/Scripts/python.exe
PYTEST := .venv/Scripts/pytest.exe
RUFF := .venv/Scripts/ruff.exe

.PHONY: audit test lint benchmarks backend frontend e2e all

audit:
	$(PYTHON) scripts/toolchain_audit.py

lint:
	$(RUFF) check contracts hw_architect fw_generator hil_sim backend_bridge tests

test:
	$(PYTEST) -v

benchmarks:
	$(PYTHON) -m hil_sim.stress_runner

backend:
	.venv/Scripts/uvicorn.exe backend_bridge.main:app --host 127.0.0.1 --port 8765

frontend:
	cd web_hil_dashboard && npm.cmd run build

e2e:
	$(PYTHON) scripts/run_gui_audit.py

all: audit lint test benchmarks frontend e2e
