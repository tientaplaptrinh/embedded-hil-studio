"""Deterministic Backtracking Constraint Pin Solver & Auto-Repair Engine."""

from __future__ import annotations

from pathlib import Path

import yaml

from contracts.hw_models import (
    BoardDef,
    DrcReport,
    EmbeddedProjectSpec,
    HardwareBlueprint,
    PeripheralSpec,
    PinAssignment,
    PinCapability,
    SignalReq,
)

from .electrical_drc import run_electrical_drc
from .wiring_svg_gen import generate_wiring_markdown_and_bom, generate_wiring_svg

_BOARDS_DIR = Path(__file__).resolve().parent / "boards"

BUS_WIRE_COLORS: dict[str, str] = {
    "I2C": "#06b6d4",
    "SPI": "#a855f7",
    "I2S_RX": "#10b981",
    "I2S_TX": "#14b8a6",
    "PWM": "#f59e0b",
    "SERVO": "#fb923c",
    "UART": "#f43f5e",
    "ADC": "#84cc16",
    "MOTOR_DRIVER": "#eab308",
    "GPIO": "#38bdf8",
}


def load_board(board_id: str) -> BoardDef:
    path = _BOARDS_DIR / f"{board_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Board database not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return BoardDef.model_validate(raw)


def _candidate_pins_for_signal(
    project: EmbeddedProjectSpec,
    board: BoardDef,
    periph: PeripheralSpec,
    sig: SignalReq,
    *,
    has_timer1_servo: bool,
    allow_strapping: bool = False,
    respect_manual: bool = True,
) -> list[PinCapability]:
    manual_pin_id = periph.manual_pins.get(sig.signal_name) if respect_manual else None
    is_output_like = sig.direction in ("out", "inout") or sig.required_capability not in (
        "GPIO_IN",
        "ADC",
        "I2S_SD",
    )

    candidates: list[tuple[int, int, PinCapability]] = []
    for pin in board.pins:
        if pin.forbidden:
            continue
        if "opi_psram" in pin.reserved_when and project.opi_psram_enabled:
            continue
        if "usb_jtag" in pin.reserved_when and project.usb_jtag_reserved:
            continue
        if not allow_strapping and pin.strapping:
            continue
        if sig.required_capability not in pin.capabilities:
            continue
        if pin.input_only and is_output_like:
            continue
        if sig.required_capability == "ADC" and project.wifi_enabled and pin.adc_unit == "ADC2":
            continue
        if has_timer1_servo and sig.required_capability == "PWM" and pin.timer_group == "Timer1":
            continue

        score = 100
        if manual_pin_id and pin.pin_id == manual_pin_id:
            score -= 200

        # Prefer dedicated bus role pins (e.g., default I2C SDA/SCL, SPI2 MOSI/MISO/SCK)
        for role_val in pin.bus_roles.values():
            if sig.required_capability.endswith(role_val):
                score -= 40

        # Keep hardware UART0 free unless this is a UART signal and no secondary UART exists
        if pin.hardware_uart:
            if sig.required_capability in ("UART_RX", "UART_TX"):
                score += 60
            else:
                score += 400

        if pin.strapping:
            score += 300

        # Prefer pure digital pins for plain GPIO_IN/OUT so scarce PWM/ADC/SPI pins stay free
        if sig.required_capability in ("GPIO_IN", "GPIO_OUT"):
            if "PWM" in pin.capabilities and not board.flexible_pin_matrix:
                score += 25
            if "SPI_MOSI" in pin.capabilities or "SPI_MISO" in pin.capabilities or "SPI_SCK" in pin.capabilities:
                score += 18
            if "I2C_SDA" in pin.capabilities or "I2C_SCL" in pin.capabilities:
                score += 20
            if pin.adc_unit == "ADC1":
                score += 15
        elif sig.required_capability == "SERVO":
            # On Arduino Uno, Servo uses Timer1 ISR anyway, so placing Servo signal on D9/D10
            # preserves Timer0/Timer2 PWM pins (D3, D5, D6, D11) for DC motors/fans!
            if pin.timer_group == "Timer1":
                score -= 30
            elif pin.timer_group in ("Timer0", "Timer2"):
                score += 25

        candidates.append((score, pin.gpio_num, pin))

    candidates.sort(key=lambda item: (item[0], item[1]))
    return [c[2] for c in candidates]


def solve_project_pins(
    project: EmbeddedProjectSpec,
    board: BoardDef,
    *,
    respect_manual: bool = True,
) -> list[PinAssignment]:
    """Deterministically assign conflict-free MCU pins via MRV backtracking search."""
    has_timer1_servo = any(
        p.uses_timer1_isr or p.bus_type == "SERVO" for p in project.peripherals
    )

    # Group tasks: shared-bus signals are solved once per (shared_bus, required_capability)
    tasks: list[dict] = []
    shared_index: dict[tuple[str, str], int] = {}

    for p in project.peripherals:
        for sig in p.signals:
            if sig.shared_bus is not None:
                key = (sig.shared_bus, sig.required_capability)
                if key in shared_index:
                    tasks[shared_index[key]]["consumers"].append((p, sig))
                    continue
                shared_index[key] = len(tasks)
            cands = _candidate_pins_for_signal(
                project,
                board,
                p,
                sig,
                has_timer1_servo=has_timer1_servo,
                allow_strapping=False,
                respect_manual=respect_manual,
            )
            if not cands:
                cands = _candidate_pins_for_signal(
                    project,
                    board,
                    p,
                    sig,
                    has_timer1_servo=has_timer1_servo,
                    allow_strapping=True,
                    respect_manual=respect_manual,
                )
            tasks.append(
                {
                    "rep_periph": p,
                    "rep_sig": sig,
                    "consumers": [(p, sig)],
                    "candidates": cands,
                }
            )

    # Most-Constrained-Variable (MRV) ordering for fast deterministic backtracking
    order = sorted(range(len(tasks)), key=lambda idx: (len(tasks[idx]["candidates"]), idx))
    chosen: dict[int, PinCapability] = {}
    used_pins: set[str] = set()

    def backtrack(pos: int) -> bool:
        if pos == len(order):
            return True
        task_idx = order[pos]
        for cand in tasks[task_idx]["candidates"]:
            if cand.pin_id in used_pins:
                continue
            used_pins.add(cand.pin_id)
            chosen[task_idx] = cand
            if backtrack(pos + 1):
                return True
            used_pins.remove(cand.pin_id)
            del chosen[task_idx]
        return False

    if not backtrack(0):
        raise RuntimeError(
            f"Pin solver could not find a conflict-free pin allocation on {board.name} "
            f"for project '{project.project_id}'."
        )

    # Emit assignments in peripheral/signal declaration order
    pair_to_pin: dict[tuple[str, str], PinCapability] = {}
    for task_idx, pin_cap in chosen.items():
        for p, sig in tasks[task_idx]["consumers"]:
            pair_to_pin[(p.instance_id, sig.signal_name)] = pin_cap

    assignments: list[PinAssignment] = []
    for p in project.peripherals:
        for sig in p.signals:
            pin_cap = pair_to_pin[(p.instance_id, sig.signal_name)]
            note_parts = []
            if sig.shared_bus:
                note_parts.append(f"Shared {sig.shared_bus}")
            if pin_cap.adc_unit:
                note_parts.append(pin_cap.adc_unit)
            if pin_cap.timer_group and sig.required_capability == "PWM":
                note_parts.append(pin_cap.timer_group)
            assignments.append(
                PinAssignment(
                    instance_id=p.instance_id,
                    part_number=p.part_number,
                    signal_name=sig.signal_name,
                    pin_id=pin_cap.pin_id,
                    gpio_num=pin_cap.gpio_num,
                    bus_type=p.bus_type,
                    shared_bus=sig.shared_bus,
                    wire_color=BUS_WIRE_COLORS.get(p.bus_type, "#38bdf8"),
                    notes=", ".join(note_parts),
                )
            )
    return assignments


def build_raw_assignments_with_manual(
    project: EmbeddedProjectSpec,
    board: BoardDef,
) -> list[PinAssignment]:
    """Honor user manual_pins verbatim (even if conflicting/illegal) for DRC negative audits,
    filling any unspecified pins via the solver."""
    clean_assignments = solve_project_pins(project, board, respect_manual=False)
    fallback_map = {(a.instance_id, a.signal_name): a for a in clean_assignments}

    raw_list: list[PinAssignment] = []
    for p in project.peripherals:
        for sig in p.signals:
            manual_pin_id = p.manual_pins.get(sig.signal_name)
            if manual_pin_id:
                pin_cap = board.get_pin(manual_pin_id)
                gpio_num = pin_cap.gpio_num if pin_cap is not None else -1
                raw_list.append(
                    PinAssignment(
                        instance_id=p.instance_id,
                        part_number=p.part_number,
                        signal_name=sig.signal_name,
                        pin_id=manual_pin_id,
                        gpio_num=gpio_num,
                        bus_type=p.bus_type,
                        shared_bus=sig.shared_bus,
                        wire_color=BUS_WIRE_COLORS.get(p.bus_type, "#38bdf8"),
                        notes="Manual pinout",
                    )
                )
            else:
                raw_list.append(fallback_map[(p.instance_id, sig.signal_name)])
    return raw_list


def architect_project(
    project: EmbeddedProjectSpec,
    *,
    auto_repair: bool = True,
) -> tuple[DrcReport, HardwareBlueprint]:
    """Run initial Electrical DRC on user spec; if violations exist and auto_repair=True,
    repair pin allocations and missing protection stages, then emit complete SVG & BOM."""
    board = load_board(project.board_id)
    raw_assignments = build_raw_assignments_with_manual(project, board)
    initial_drc, initial_power = run_electrical_drc(project, board, raw_assignments)

    active_project = project.model_copy(deep=True)
    active_assignments = raw_assignments
    active_drc = initial_drc
    active_power = initial_power
    repaired = False
    repair_notes: list[str] = []

    if not initial_drc.passed and auto_repair:
        repaired = True
        # 1. Clear manual pin overrides that caused DRC violations
        for p in active_project.peripherals:
            if p.manual_pins:
                repair_notes.append(
                    f"Cleared conflicting manual pin overrides on '{p.instance_id}' ({p.manual_pins})."
                )
                p.manual_pins.clear()

            # 2. Repair missing inductive driver + flyback diode
            if p.inductive_load and (not p.has_driver_stage or not p.has_flyback_diode):
                p.has_driver_stage = True
                p.has_flyback_diode = True
                if p.supply_voltage >= 5.0:
                    p.powered_from_mcu_regulator = False
                p.bom_notes = "Auto-inserted PC817/AO3400 MOSFET driver + 1N4007 flyback diode"
                repair_notes.append(
                    f"Inserted opto-isolated N-MOSFET driver + 1N4007 flyback diode for inductive load '{p.instance_id}'."
                )

            # 3. Repair missing 5V -> 3.3V logic level shifter
            if p.logic_voltage > board.logic_voltage + 0.3 and not p.has_level_shifter:
                if any(s.direction in ("in", "inout") for s in p.signals):
                    p.has_level_shifter = True
                    p.bom_notes = (p.bom_notes + "; " if p.bom_notes else "") + (
                        "Auto-inserted BSS138 4-ch bidirectional logic level shifter"
                    )
                    repair_notes.append(
                        f"Inserted BSS138 5V->3.3V level shifter on '{p.instance_id}' data lines."
                    )

        # 4. Repair I2C address collisions if present
        seen_i2c: set[int] = set()
        for p in active_project.peripherals:
            if p.bus_type == "I2C" and p.i2c_address and not p.has_i2c_mux:
                addr_int = int(p.i2c_address, 16)
                if addr_int in seen_i2c:
                    p.has_i2c_mux = True
                    repair_notes.append(
                        f"Inserted PCA9548A I2C mux channel isolation for duplicate address {p.i2c_address} on '{p.instance_id}'."
                    )
                seen_i2c.add(addr_int)

        active_assignments = solve_project_pins(active_project, board, respect_manual=False)
        active_drc, active_power = run_electrical_drc(active_project, board, active_assignments)

    svg = generate_wiring_svg(active_project, board, active_assignments, active_drc, active_power)
    wiring_md, bom = generate_wiring_markdown_and_bom(
        active_project, board, active_assignments, active_power, repair_notes
    )

    blueprint = HardwareBlueprint(
        project_id=active_project.project_id,
        project_name=active_project.name,
        board=board,
        pin_assignments=active_assignments,
        drc=active_drc,
        power_budget=active_power,
        auto_repaired=repaired,
        repair_notes=repair_notes,
        svg_diagram=svg,
        wiring_markdown=wiring_md,
        bom=bom,
    )
    return initial_drc, blueprint
