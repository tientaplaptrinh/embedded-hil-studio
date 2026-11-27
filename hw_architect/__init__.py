"""Hardware Architect package: MCU pin databases, solver, electrical DRC, and SVG wiring."""

from .electrical_drc import compute_power_budget, run_electrical_drc
from .pin_solver import (
    architect_project,
    build_raw_assignments_with_manual,
    load_board,
    solve_project_pins,
)
from .wiring_svg_gen import generate_wiring_markdown_and_bom, generate_wiring_svg

__all__ = [
    "architect_project",
    "build_raw_assignments_with_manual",
    "compute_power_budget",
    "generate_wiring_markdown_and_bom",
    "generate_wiring_svg",
    "load_board",
    "run_electrical_drc",
    "solve_project_pins",
]
