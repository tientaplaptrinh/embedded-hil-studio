"""Vector SVG Pinout & Orthogonal Wiring Diagram + BOM Generator."""

from __future__ import annotations

from html import escape

from contracts.hw_models import (
    BoardDef,
    BomItem,
    DrcReport,
    EmbeddedProjectSpec,
    PinAssignment,
    PowerBudget,
)


def generate_wiring_svg(
    project: EmbeddedProjectSpec,
    board: BoardDef,
    assignments: list[PinAssignment],
    drc: DrcReport,
    power: PowerBudget,
) -> str:
    width = 1120
    periph_heights: list[int] = []
    assign_by_periph: dict[str, list[PinAssignment]] = {p.instance_id: [] for p in project.peripherals}
    for a in assignments:
        assign_by_periph.setdefault(a.instance_id, []).append(a)

    for p in project.peripherals:
        n_sigs = max(len(assign_by_periph.get(p.instance_id, [])), 1)
        periph_heights.append(88 + n_sigs * 24)

    right_total_h = sum(periph_heights) + max(0, len(periph_heights) - 1) * 22
    used_pin_ids = {a.pin_id for a in assignments}
    # Show allocated pins + up to 6 notable restricted pins for architectural clarity
    allocated_pins = [pin for pin in board.pins if pin.pin_id in used_pin_ids]
    notable_restricted = [
        pin
        for pin in board.pins
        if pin.pin_id not in used_pin_ids and (pin.forbidden or pin.input_only or "opi_psram" in pin.reserved_when or pin.timer_group == "Timer1")
    ][:6]
    displayed_pins = allocated_pins + notable_restricted

    mcu_box_h = max(320, 120 + (len(displayed_pins) + 2) * 26)
    height = max(mcu_box_h + 170, right_total_h + 170, 560)

    mcu_x, mcu_y, mcu_w = 70, 96, 330
    periph_x, periph_w = 700, 360

    lines: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" height="100%" '
        f'style="background:#0b1120;font-family:Inter,Segoe UI,monospace;">',
        "<defs>",
        '  <pattern id="grid" width="24" height="24" patternUnits="userSpaceOnUse">',
        '    <path d="M 24 0 L 0 0 0 24" fill="none" stroke="#1e293b" stroke-width="0.7"/>',
        "  </pattern>",
        "</defs>",
        f'<rect width="{width}" height="{height}" fill="url(#grid)"/>',
        # Header banner
        f'<rect x="24" y="18" width="{width - 48}" height="56" rx="10" fill="#111827" stroke="#334155" stroke-width="1.2"/>',
        f'<text x="44" y="43" fill="#f8fafc" font-size="16" font-weight="700">{escape(project.name)} — Annotated Hardware Wiring</text>',
        f'<text x="44" y="63" fill="#94a3b8" font-size="12">MCU: {escape(board.name)} ({board.logic_voltage}V Logic) | '
        f'Avg Power: {power.average_power_w:.2f}W (Peak {power.peak_power_w:.2f}W)'
        + (f' | Est. Runtime: {power.estimated_runtime_hours:.1f}h' if power.estimated_runtime_hours else '')
        + "</text>",
    ]

    status_color = "#10b981" if drc.passed else "#ef4444"
    status_label = f"DRC PASS ({drc.warning_count} WARN)" if drc.passed else f"DRC FAIL ({drc.error_count} ERR)"
    lines.append(
        f'<rect x="{width - 235}" y="30" width="190" height="32" rx="16" fill="{status_color}22" stroke="{status_color}" stroke-width="1.4"/>'
    )
    lines.append(
        f'<text x="{width - 140}" y="50" text-anchor="middle" fill="{status_color}" font-size="12" font-weight="700">{status_label}</text>'
    )

    # MCU Block
    lines.extend(
        [
            f'<rect x="{mcu_x}" y="{mcu_y}" width="{mcu_w}" height="{mcu_box_h}" rx="12" fill="#0f172a" stroke="#38bdf8" stroke-width="1.8"/>',
            f'<rect x="{mcu_x}" y="{mcu_y}" width="{mcu_w}" height="48" rx="12" fill="#1e293b"/>',
            f'<text x="{mcu_x + 18}" y="{mcu_y + 24}" fill="#f8fafc" font-size="14" font-weight="700">{escape(board.name)}</text>',
            f'<text x="{mcu_x + 18}" y="{mcu_y + 41}" fill="#38bdf8" font-size="11">MCU: {escape(board.mcu)} | Safe Pin {board.max_pin_current_safe_ma:.0f}mA</text>',
        ]
    )

    pin_y_map: dict[str, int] = {}
    vcc_y = mcu_y + 72
    gnd_y = mcu_y + 98
    pin_y_map["__VCC__"] = vcc_y
    pin_y_map["__GND__"] = gnd_y

    # Power & GND header pins on MCU
    lines.extend(
        [
            f'<circle cx="{mcu_x + mcu_w}" cy="{vcc_y}" r="5" fill="#ef4444"/>',
            f'<text x="{mcu_x + mcu_w - 14}" y="{vcc_y + 4}" text-anchor="end" fill="#fca5a5" font-size="11" font-weight="700">VCC / {board.logic_voltage}V / 5V RAIL</text>',
            f'<circle cx="{mcu_x + mcu_w}" cy="{gnd_y}" r="5" fill="#94a3b8"/>',
            f'<text x="{mcu_x + mcu_w - 14}" y="{gnd_y + 4}" text-anchor="end" fill="#cbd5e1" font-size="11" font-weight="700">COMMON GND</text>',
        ]
    )

    cur_pin_y = mcu_y + 128
    for pin in displayed_pins:
        pin_y_map[pin.pin_id] = cur_pin_y
        is_used = pin.pin_id in used_pin_ids
        dot_color = "#38bdf8" if is_used else "#475569"
        txt_color = "#e2e8f0" if is_used else "#64748b"
        badge = ""
        if pin.forbidden or "opi_psram" in pin.reserved_when:
            badge = " [LOCKED:FLASH/PSRAM]"
            dot_color = "#ef4444"
        elif pin.input_only:
            badge = " [IN-ONLY]"
        elif pin.timer_group == "Timer1":
            badge = " [TIMER1]"
        lines.extend(
            [
                f'<circle cx="{mcu_x + mcu_w}" cy="{cur_pin_y}" r="4.5" fill="{dot_color}"/>',
                f'<text x="{mcu_x + mcu_w - 14}" y="{cur_pin_y + 4}" text-anchor="end" fill="{txt_color}" font-size="11">{escape(pin.label)}{badge}</text>',
            ]
        )
        cur_pin_y += 26

    # Peripherals + Orthogonal Wires
    cur_py = 96
    lane_idx = 0
    for idx, p in enumerate(project.peripherals):
        box_h = periph_heights[idx]
        p_assigns = assign_by_periph.get(p.instance_id, [])

        # Badges for safety hardware
        badges: list[str] = []
        if p.inductive_load and p.has_driver_stage:
            badges.append("DRV+FLYBACK")
        if p.has_level_shifter:
            badges.append("LVL-SHIFT")
        if p.i2c_address:
            badges.append(f"I2C {p.i2c_address}")
        if not p.powered_from_mcu_regulator:
            badges.append(f"EXT {p.supply_voltage}V")
        badge_str = " | ".join(badges)

        lines.extend(
            [
                f'<rect x="{periph_x}" y="{cur_py}" width="{periph_w}" height="{box_h}" rx="10" fill="#0f172a" stroke="#475569" stroke-width="1.5"/>',
                f'<rect x="{periph_x}" y="{cur_py}" width="{periph_w}" height="44" rx="10" fill="#1e293b"/>',
                f'<text x="{periph_x + 14}" y="{cur_py + 21}" fill="#f8fafc" font-size="13" font-weight="700">{escape(p.instance_id)} ({escape(p.part_number)})</text>',
                f'<text x="{periph_x + 14}" y="{cur_py + 37}" fill="#94a3b8" font-size="10.5">{p.supply_voltage}V Supply | Peak {p.peak_current_ma:.0f}mA'
                + (f" | {escape(badge_str)}" if badge_str else "")
                + "</text>",
            ]
        )

        # Power & GND stubs into peripheral
        pv_y = cur_py + 58
        pg_y = cur_py + 74
        pwr_lane_x = mcu_x + mcu_w + 26
        gnd_lane_x = mcu_x + mcu_w + 40
        lines.extend(
            [
                f'<path d="M {mcu_x + mcu_w} {vcc_y} L {pwr_lane_x} {vcc_y} L {pwr_lane_x} {pv_y} L {periph_x} {pv_y}" fill="none" stroke="#ef4444" stroke-width="1.3" stroke-dasharray="4 3" opacity="0.75"/>',
                f'<path d="M {mcu_x + mcu_w} {gnd_y} L {gnd_lane_x} {gnd_y} L {gnd_lane_x} {pg_y} L {periph_x} {pg_y}" fill="none" stroke="#64748b" stroke-width="1.3" stroke-dasharray="4 3" opacity="0.75"/>',
                f'<text x="{periph_x + 12}" y="{pv_y + 4}" fill="#fca5a5" font-size="10">VCC ({p.supply_voltage}V)</text>',
                f'<text x="{periph_x + 12}" y="{pg_y + 4}" fill="#94a3b8" font-size="10">GND</text>',
            ]
        )

        sig_y = cur_py + 96
        for a in p_assigns:
            src_y = pin_y_map.get(a.pin_id, mcu_y + 130)
            mid_x = mcu_x + mcu_w + 62 + (lane_idx * 14) % 210
            lane_idx += 1
            color = a.wire_color
            lines.extend(
                [
                    f'<path d="M {mcu_x + mcu_w} {src_y} L {mid_x} {src_y} L {mid_x} {sig_y} L {periph_x} {sig_y}" '
                    f'fill="none" stroke="{color}" stroke-width="2.1" stroke-linejoin="round"/>',
                    f'<circle cx="{periph_x}" cy="{sig_y}" r="4" fill="{color}"/>',
                    f'<text x="{periph_x + 12}" y="{sig_y + 4}" fill="#f1f5f9" font-size="11" font-weight="600">{escape(a.signal_name)}</text>',
                    f'<text x="{periph_x + periph_w - 12}" y="{sig_y + 4}" text-anchor="end" fill="{color}" font-size="10.5">{escape(a.pin_id)}</text>',
                ]
            )
            sig_y += 24

        cur_py += box_h + 22

    # Legend bar at bottom
    leg_y = height - 42
    lines.append(
        f'<rect x="24" y="{leg_y - 18}" width="{width - 48}" height="34" rx="8" fill="#111827" stroke="#1e293b"/>'
    )
    legend_items = [
        ("VCC", "#ef4444"),
        ("GND", "#64748b"),
        ("I2C", "#06b6d4"),
        ("SPI", "#a855f7"),
        ("I2S", "#10b981"),
        ("PWM/SERVO", "#f59e0b"),
        ("UART", "#f43f5e"),
        ("ADC", "#84cc16"),
        ("GPIO", "#38bdf8"),
    ]
    lx = 44
    for name, col in legend_items:
        lines.append(f'<line x1="{lx}" y1="{leg_y - 1}" x2="{lx + 22}" y2="{leg_y - 1}" stroke="{col}" stroke-width="3"/>')
        lines.append(f'<text x="{lx + 28}" y="{leg_y + 3}" fill="#cbd5e1" font-size="11">{name}</text>')
        lx += 108

    lines.append("</svg>")
    return "\n".join(lines)


def generate_wiring_markdown_and_bom(
    project: EmbeddedProjectSpec,
    board: BoardDef,
    assignments: list[PinAssignment],
    power: PowerBudget,
    repair_notes: list[str],
) -> tuple[str, list[BomItem]]:
    bom: list[BomItem] = [
        BomItem(
            ref="U1",
            part_number=board.pio_board.upper(),
            description=f"{board.name} ({board.mcu})",
            quantity=1,
            notes=f"{board.logic_voltage}V logic",
        )
    ]

    for idx, p in enumerate(project.peripherals, start=1):
        bom.append(
            BomItem(
                ref=f"P{idx}",
                part_number=p.part_number,
                description=p.name or p.instance_id,
                quantity=1,
                notes=p.bom_notes or f"{p.supply_voltage}V supply, {p.bus_type}",
            )
        )
        if p.has_level_shifter and "BSS138" in p.bom_notes:
            bom.append(
                BomItem(
                    ref=f"U_LVL{idx}",
                    part_number="BSS138-4CH-I2C-LVL",
                    description="4-Channel Bidirectional 5V<->3.3V Logic Level Shifter",
                    quantity=1,
                    notes=f"Protects 3.3V MCU pins from {p.instance_id}",
                )
            )
        if "Auto-inserted PC817/AO3400" in p.bom_notes:
            bom.append(
                BomItem(
                    ref=f"Q_DRV{idx}",
                    part_number="PC817-AO3400-1N4007",
                    description="Opto-Isolated N-MOSFET Low-Side Driver + Flyback Diode",
                    quantity=1,
                    notes=f"Inductive transient clamp for {p.instance_id}",
                )
            )

    if project.battery:
        bom.append(
            BomItem(
                ref="BAT1",
                part_number=project.battery.name.upper().replace(" ", "-"),
                description=f"{project.battery.name} ({project.battery.nominal_voltage}V, {project.battery.capacity_mah:.0f}mAh)",
                quantity=1,
                notes=(
                    f"Est. runtime {power.estimated_runtime_hours}h"
                    if power.estimated_runtime_hours
                    else "Primary supply"
                ),
            )
        )

    md_lines = [
        f"# Hardware Wiring & BOM — {project.name}",
        "",
        "## Pin Allocation Table",
        "| Peripheral | Part Number | Signal | MCU Pin | GPIO # | Bus | Notes |",
        "|---|---|---|---|---:|---|---|",
    ]
    for a in assignments:
        md_lines.append(
            f"| `{a.instance_id}` | `{a.part_number}` | `{a.signal_name}` | **`{a.pin_id}`** | {a.gpio_num} | {a.bus_type} | {a.notes} |"
        )

    if repair_notes:
        md_lines.extend(["", "## Auto-Repair Actions Applied"])
        for note in repair_notes:
            md_lines.append(f"- {note}")

    md_lines.extend(
        [
            "",
            "## Power & Battery Budget",
            f"- **Idle Current:** {power.idle_current_ma:.1f} mA ({power.idle_power_w:.2f} W)",
            f"- **Average Current:** {power.average_current_ma:.1f} mA ({power.average_power_w:.2f} W)",
            f"- **Peak Current:** {power.peak_current_ma:.1f} mA ({power.peak_power_w:.2f} W)",
            f"- **MCU Onboard Regulator Load:** {power.mcu_regulator_current_ma:.1f} / {power.mcu_regulator_limit_ma:.0f} mA",
        ]
    )
    if power.estimated_runtime_hours is not None:
        md_lines.append(
            f"- **Estimated Battery Runtime ({power.battery_name}):** **{power.estimated_runtime_hours:.2f} hours**"
        )

    md_lines.extend(
        [
            "",
            "## Bill of Materials (BOM)",
            "| Ref | Part Number | Description | Qty | Notes |",
            "|---|---|---|---:|---|",
        ]
    )
    for item in bom:
        md_lines.append(
            f"| {item.ref} | `{item.part_number}` | {item.description} | {item.quantity} | {item.notes} |"
        )

    return "\n".join(md_lines), bom
