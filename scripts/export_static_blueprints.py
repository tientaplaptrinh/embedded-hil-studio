"""Export pre-computed hardware blueprints, SVGs, DRC reports & PlatformIO configs for static cloud hosting."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fw_generator import synthesize_firmware_project
from hil_sim.stress_runner import ARTIFACTS_DIR, load_benchmark_specs
from hw_architect import architect_project

PUBLIC_DIR = ROOT_DIR / "web_hil_dashboard" / "public"


def main() -> None:
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    (PUBLIC_DIR / ".nojekyll").write_text("", encoding="utf-8")

    specs = load_benchmark_specs()
    fw_root = ARTIFACTS_DIR / "firmware"
    fw_root.mkdir(parents=True, exist_ok=True)

    benchmarks_list = []
    blueprints_map = {}

    for spec in specs:
        initial_drc, blueprint = architect_project(spec, auto_repair=True)
        proj_dir = synthesize_firmware_project(spec, blueprint, fw_root)
        pio_ini = (proj_dir / "platformio.ini").read_text(encoding="utf-8")
        pin_hpp = (proj_dir / "include" / "pin_config.hpp").read_text(encoding="utf-8")

        benchmarks_list.append(
            {
                "project_id": spec.project_id,
                "name": spec.name,
                "board_id": spec.board_id,
                "description": spec.description,
                "control": spec.control.model_dump(),
            }
        )
        blueprints_map[spec.project_id] = {
            "mode": "virtual",
            "serial_port": None,
            "baudrate": 115200,
            "spec": spec.model_dump(),
            "initial_drc": initial_drc.model_dump(),
            "blueprint": blueprint.model_dump(),
            "platformio_ini": pio_ini,
            "pin_config_hpp": pin_hpp,
            "fault_state": {"sensor_disconnected": False},
        }

    out = {"benchmarks": benchmarks_list, "blueprints": blueprints_map}
    out_file = PUBLIC_DIR / "static_blueprints.json"
    out_file.write_text(json.dumps(out), encoding="utf-8")
    print(f"Exported {len(benchmarks_list)} static blueprints to {out_file}")


if __name__ == "__main__":
    main()
