"""Electrical Design Rule Checker (DRC) and Power / Battery Runtime Calculator."""

from __future__ import annotations

from collections import defaultdict

from contracts.hw_models import (
    BoardDef,
    DrcReport,
    DrcViolation,
    EmbeddedProjectSpec,
    PeripheralSpec,
    PinAssignment,
    PowerBudget,
    SignalReq,
)


def _find_signal(periph: PeripheralSpec, signal_name: str) -> SignalReq | None:
    for sig in periph.signals:
        if sig.signal_name == signal_name:
            return sig
    return None


def compute_power_budget(project: EmbeddedProjectSpec, board: BoardDef) -> PowerBudget:
    breakdown: dict[str, dict[str, float]] = {}

    mcu_idle_ma = board.base_idle_current_ma
    mcu_avg_ma = board.base_active_current_ma + (
        board.wifi_active_extra_ma if project.wifi_enabled else 0.0
    )
    mcu_peak_ma = board.base_active_current_ma + (
        board.wifi_peak_extra_ma if project.wifi_enabled else 15.0
    )
    breakdown[board.board_id] = {
        "voltage_v": board.logic_voltage,
        "idle_ma": round(mcu_idle_ma, 2),
        "avg_ma": round(mcu_avg_ma, 2),
        "peak_ma": round(mcu_peak_ma, 2),
    }

    idle_ma_sum = mcu_idle_ma
    avg_ma_sum = mcu_avg_ma
    peak_ma_sum = mcu_peak_ma
    mcu_reg_peak_ma = mcu_peak_ma

    idle_power_w = (mcu_idle_ma / 1000.0) * board.logic_voltage
    avg_power_w = (mcu_avg_ma / 1000.0) * board.logic_voltage
    peak_power_w = (mcu_peak_ma / 1000.0) * board.logic_voltage

    # Track regulated vs direct-battery power for accurate battery runtime
    reg_avg_power_w = avg_power_w
    direct_bat_avg_power_w = 0.0
    reg_peak_power_w = peak_power_w
    direct_bat_peak_power_w = 0.0

    bat = project.battery
    for p in project.peripherals:
        p_idle = p.idle_current_ma
        p_avg = p.idle_current_ma * (1.0 - p.duty_cycle) + p.active_current_ma * p.duty_cycle
        p_peak = p.peak_current_ma

        idle_ma_sum += p_idle
        avg_ma_sum += p_avg
        peak_ma_sum += p_peak
        if p.powered_from_mcu_regulator:
            mcu_reg_peak_ma += p_peak

        p_idle_w = (p_idle / 1000.0) * p.supply_voltage
        p_avg_w = (p_avg / 1000.0) * p.supply_voltage
        p_peak_w = (p_peak / 1000.0) * p.supply_voltage

        idle_power_w += p_idle_w
        avg_power_w += p_avg_w
        peak_power_w += p_peak_w

        if bat and abs(p.supply_voltage - bat.nominal_voltage) < 0.4 and not p.powered_from_mcu_regulator:
            direct_bat_avg_power_w += p_avg_w
            direct_bat_peak_power_w += p_peak_w
        else:
            reg_avg_power_w += p_avg_w
            reg_peak_power_w += p_peak_w

        breakdown[p.instance_id] = {
            "voltage_v": p.supply_voltage,
            "idle_ma": round(p_idle, 2),
            "avg_ma": round(p_avg, 2),
            "peak_ma": round(p_peak, 2),
        }

    sys_v = bat.nominal_voltage if bat else 5.0
    runtime_h: float | None = None
    bat_name: str | None = None
    bat_cap: float | None = None

    if bat:
        bat_name = bat.name
        bat_cap = bat.capacity_mah
        eff_total_avg_w = (reg_avg_power_w / bat.regulator_efficiency) + direct_bat_avg_power_w
        bat_avg_current_ma = (eff_total_avg_w / bat.nominal_voltage) * 1000.0
        if bat.capacity_mah > 0.0 and bat_avg_current_ma > 0.0:
            runtime_h = round((bat.capacity_mah * bat.usable_dod) / bat_avg_current_ma, 2)

    return PowerBudget(
        idle_current_ma=round(idle_ma_sum, 2),
        average_current_ma=round(avg_ma_sum, 2),
        peak_current_ma=round(peak_ma_sum, 2),
        mcu_regulator_current_ma=round(mcu_reg_peak_ma, 2),
        mcu_regulator_limit_ma=round(board.max_regulator_current_ma, 2),
        system_voltage_v=sys_v,
        idle_power_w=round(idle_power_w, 3),
        average_power_w=round(avg_power_w, 3),
        peak_power_w=round(peak_power_w, 3),
        battery_name=bat_name,
        battery_capacity_mah=bat_cap,
        estimated_runtime_hours=runtime_h,
        breakdown=breakdown,
    )


def run_electrical_drc(
    project: EmbeddedProjectSpec,
    board: BoardDef,
    assignments: list[PinAssignment],
) -> tuple[DrcReport, PowerBudget]:
    violations: list[DrcViolation] = []
    periph_map = {p.instance_id: p for p in project.peripherals}

    has_timer1_servo = any(
        p.uses_timer1_isr or p.bus_type == "SERVO" for p in project.peripherals
    )

    # Check completeness: every peripheral signal should have an assignment
    assigned_keys = {(a.instance_id, a.signal_name) for a in assignments}
    for p in project.peripherals:
        for sig in p.signals:
            if (p.instance_id, sig.signal_name) not in assigned_keys:
                violations.append(
                    DrcViolation(
                        severity="error",
                        rule_id="DRC_UNASSIGNED_SIGNAL",
                        peripheral_id=p.instance_id,
                        pin_id=None,
                        message=f"Signal '{sig.signal_name}' on '{p.instance_id}' has no MCU pin assigned.",
                        recommendation=f"Run constraint pin solver to allocate a valid {sig.required_capability} pin.",
                    )
                )

    # Pin-level rules
    pin_usage: dict[str, list[tuple[PinAssignment, SignalReq | None]]] = defaultdict(list)
    for a in assignments:
        periph = periph_map.get(a.instance_id)
        sig = _find_signal(periph, a.signal_name) if periph else None
        pin = board.get_pin(a.pin_id)
        pin_usage[a.pin_id].append((a, sig))

        if pin is None:
            violations.append(
                DrcViolation(
                    severity="error",
                    rule_id="DRC_UNKNOWN_PIN",
                    peripheral_id=a.instance_id,
                    pin_id=a.pin_id,
                    message=f"Pin '{a.pin_id}' does not exist on board '{board.name}'.",
                    recommendation="Select a valid header pin from the MCU board definition.",
                )
            )
            continue

        # 1. Reserved / Flash / Octal PSRAM / USB-JTAG pins
        if pin.forbidden:
            violations.append(
                DrcViolation(
                    severity="error",
                    rule_id="DRC_FLASH_PSRAM_RESERVED",
                    peripheral_id=a.instance_id,
                    pin_id=a.pin_id,
                    message=(
                        f"Pin {a.pin_id} is forbidden ({pin.forbidden_reason or 'SPI Flash reserved'})."
                    ),
                    recommendation="Move signal off internal SPI Flash pins (GPIO 6-11 on ESP32 / GPIO 26-32 on S3).",
                )
            )
            continue

        if "opi_psram" in pin.reserved_when and project.opi_psram_enabled:
            violations.append(
                DrcViolation(
                    severity="error",
                    rule_id="DRC_FLASH_PSRAM_RESERVED",
                    peripheral_id=a.instance_id,
                    pin_id=a.pin_id,
                    message=(
                        f"Pin {a.pin_id} is reserved by Octal SPI PSRAM/Flash (GPIO 26-37) on {board.name}."
                    ),
                    recommendation="Reassign to free general-purpose GPIOs outside GPIO 26-37.",
                )
            )

        if "usb_jtag" in pin.reserved_when and project.usb_jtag_reserved:
            violations.append(
                DrcViolation(
                    severity="error",
                    rule_id="DRC_USB_JTAG_RESERVED",
                    peripheral_id=a.instance_id,
                    pin_id=a.pin_id,
                    message=f"Pin {a.pin_id} is reserved for native USB Serial/JTAG debugging.",
                    recommendation="Keep GPIO 19/20 free for USB-JTAG flashing and telemetry.",
                )
            )

        if sig is not None:
            # (b) Output assigned to input-only GPIO
            is_output_like = sig.direction in ("out", "inout") or sig.required_capability not in (
                "GPIO_IN",
                "ADC",
                "I2S_SD",
            )
            if pin.input_only and is_output_like:
                violations.append(
                    DrcViolation(
                        severity="error",
                        rule_id="DRC_INPUT_ONLY_GPIO_OUTPUT",
                        peripheral_id=a.instance_id,
                        pin_id=a.pin_id,
                        message=(
                            f"Output/bidirectional signal '{a.signal_name}' of '{a.instance_id}' is wired to "
                            f"input-only pin {a.pin_id} (no output driver or internal pull-up)."
                        ),
                        recommendation="Reassign output signal to an output-capable GPIO (e.g., GPIO 16-27, 32-33).",
                    )
                )

            # (a) ADC2 used alongside Wi-Fi
            if sig.required_capability == "ADC" and pin.adc_unit == "ADC2" and project.wifi_enabled:
                violations.append(
                    DrcViolation(
                        severity="error",
                        rule_id="DRC_ADC2_WIFI_CONFLICT",
                        peripheral_id=a.instance_id,
                        pin_id=a.pin_id,
                        message=(
                            f"Analog input '{a.signal_name}' on '{a.instance_id}' uses {a.pin_id} (ADC2) "
                            f"while Wi-Fi is enabled; ESP32 Wi-Fi driver locks the SAR ADC2 controller."
                        ),
                        recommendation="Move analog sensor to an ADC1 pin (GPIO 32-39 on ESP32, GPIO 1-10 on ESP32-S3).",
                    )
                )

            # Capability check (only if not already caught as input-only output)
            if sig.required_capability not in pin.capabilities and not (pin.input_only and is_output_like):
                violations.append(
                    DrcViolation(
                        severity="error",
                        rule_id="DRC_CAPABILITY_MISMATCH",
                        peripheral_id=a.instance_id,
                        pin_id=a.pin_id,
                        message=(
                            f"Pin {a.pin_id} lacks capability '{sig.required_capability}' required by "
                            f"'{a.instance_id}.{a.signal_name}'."
                        ),
                        recommendation=f"Assign a pin supporting {sig.required_capability}.",
                    )
                )

            # (f) Timer1 Servo vs PWM clash on Arduino Uno
            if (
                has_timer1_servo
                and sig.required_capability == "PWM"
                and pin.timer_group == "Timer1"
            ):
                violations.append(
                    DrcViolation(
                        severity="error",
                        rule_id="DRC_UNO_TIMER1_SERVO_PWM",
                        peripheral_id=a.instance_id,
                        pin_id=a.pin_id,
                        message=(
                            f"PWM signal '{a.instance_id}.{a.signal_name}' is assigned to {a.pin_id} ({pin.timer_group}), "
                            f"which conflicts with Servo Timer1 ISR (analogWrite disabled on D9/D10)."
                        ),
                        recommendation="Move PWM channel to Timer0 (D5, D6) or Timer2 (D3, D11).",
                    )
                )

        # Strapping pin warning
        if pin.strapping:
            violations.append(
                DrcViolation(
                    severity="warning",
                    rule_id="DRC_STRAPPING_PIN_WARN",
                    peripheral_id=a.instance_id,
                    pin_id=a.pin_id,
                    message=(
                        f"Pin {a.pin_id} is an MCU boot strapping pin ({pin.strapping_note or 'boot-sensitive'})."
                    ),
                    recommendation="Prefer non-strapping GPIOs or ensure external pull state does not disturb reset.",
                )
            )

        # Hardware UART0 conflict warning
        if pin.hardware_uart:
            violations.append(
                DrcViolation(
                    severity="warning",
                    rule_id="DRC_UNO_HW_UART_SHARED",
                    peripheral_id=a.instance_id,
                    pin_id=a.pin_id,
                    message=(
                        f"Pin {a.pin_id} shares hardware UART0 with USB Serial/bootloader flashing "
                        f"for '{a.instance_id}.{a.signal_name}'."
                    ),
                    recommendation=(
                        "Disconnect peripheral TX during firmware upload or isolate with a 1kΩ series resistor."
                    ),
                )
            )

    # Pin collision rule (allow shared buses like I2C SDA/SCL or SPI MOSI/MISO/SCK)
    for pin_id, entries in pin_usage.items():
        if len(entries) <= 1:
            continue
        first_assign, first_sig = entries[0]
        can_share = (
            first_sig is not None
            and first_sig.shared_bus is not None
            and all(
                sig is not None
                and sig.shared_bus == first_sig.shared_bus
                and sig.required_capability == first_sig.required_capability
                for _, sig in entries
            )
        )
        if not can_share:
            owners = ", ".join(f"{a.instance_id}.{a.signal_name}" for a, _ in entries)
            violations.append(
                DrcViolation(
                    severity="error",
                    rule_id="DRC_PIN_COLLISION",
                    peripheral_id=first_assign.instance_id,
                    pin_id=pin_id,
                    message=f"Electrical pin collision on {pin_id} contended by: {owners}.",
                    recommendation="Assign dedicated pins to non-bus signals and unique CS lines.",
                )
            )

    # Peripheral-level electrical rules
    i2c_groups: dict[int, list[PeripheralSpec]] = defaultdict(list)
    for p in project.peripherals:
        # (c) 5V peripheral TX/data wired directly to 3.3V MCU RX/input without level shifter
        if p.logic_voltage > board.logic_voltage + 0.3 and not p.has_level_shifter:
            drives_mcu = [s for s in p.signals if s.direction in ("in", "inout")]
            if drives_mcu:
                sig_names = ", ".join(s.signal_name for s in drives_mcu)
                violations.append(
                    DrcViolation(
                        severity="error",
                        rule_id="DRC_5V_TO_3V3_LEVEL_SHIFT",
                        peripheral_id=p.instance_id,
                        pin_id=None,
                        message=(
                            f"Peripheral '{p.instance_id}' ({p.logic_voltage}V logic) drives {board.logic_voltage}V "
                            f"MCU input(s) [{sig_names}] without a level shifter or voltage divider."
                        ),
                        recommendation="Add a BSS138 bidirectional level shifter or 1kΩ/2kΩ voltage divider.",
                    )
                )

        # (d) Inductive load without driver + flyback diode
        if p.inductive_load and (not p.has_driver_stage or not p.has_flyback_diode):
            missing = []
            if not p.has_driver_stage:
                missing.append("transistor/MOSFET/optocoupler driver stage")
            if not p.has_flyback_diode:
                missing.append("flyback clamp diode")
            violations.append(
                DrcViolation(
                    severity="error",
                    rule_id="DRC_INDUCTIVE_NO_DRIVER",
                    peripheral_id=p.instance_id,
                    pin_id=None,
                    message=(
                        f"Inductive load '{p.instance_id}' ({p.peak_current_ma:.0f} mA peak vs "
                        f"{board.max_pin_current_safe_ma:.0f} mA safe GPIO limit) lacks {' and '.join(missing)}."
                    ),
                    recommendation=(
                        "Drive coil/motor via N-MOSFET (AO3400), opto-isolated relay driver, or H-Bridge "
                        "with anti-parallel 1N4007/SS14 flyback diode."
                    ),
                )
            )

        # Collect I2C addresses
        if p.bus_type == "I2C" and p.i2c_address and not p.has_i2c_mux:
            addr_int = int(p.i2c_address, 16)
            i2c_groups[addr_int].append(p)

    # (e) I2C address clash without mux
    for addr_int, devs in i2c_groups.items():
        if len(devs) > 1:
            names = ", ".join(d.instance_id for d in devs)
            violations.append(
                DrcViolation(
                    severity="error",
                    rule_id="DRC_I2C_ADDR_CLASH",
                    peripheral_id=devs[0].instance_id,
                    pin_id=None,
                    message=f"I2C address collision at 0x{addr_int:02X} shared by [{names}] without an I2C mux.",
                    recommendation="Change AD0 address strap on one sensor or insert a PCA9548A I2C multiplexer.",
                )
            )

    # (g) Power & Battery Runtime checks
    power_budget = compute_power_budget(project, board)
    if power_budget.mcu_regulator_current_ma > board.max_regulator_current_ma:
        violations.append(
            DrcViolation(
                severity="error",
                rule_id="DRC_REGULATOR_OVERCURRENT",
                peripheral_id=None,
                pin_id=None,
                message=(
                    f"Peak current on MCU onboard regulator ({power_budget.mcu_regulator_current_ma:.1f} mA) "
                    f"exceeds rating ({board.max_regulator_current_ma:.1f} mA)."
                ),
                recommendation="Power high-current actuators/amplifiers from an external buck regulator or VBUS rail.",
            )
        )

    if project.battery is not None:
        bat = project.battery
        est_peak_bat_ma = (
            power_budget.peak_power_w / (bat.nominal_voltage * bat.regulator_efficiency)
        ) * 1000.0
        if est_peak_bat_ma > bat.max_continuous_discharge_ma:
            violations.append(
                DrcViolation(
                    severity="error",
                    rule_id="DRC_BATTERY_OVERCURRENT",
                    peripheral_id=None,
                    pin_id=None,
                    message=(
                        f"System peak battery current ({est_peak_bat_ma:.0f} mA) exceeds battery max continuous "
                        f"rating ({bat.max_continuous_discharge_ma:.0f} mA) for '{bat.name}'."
                    ),
                    recommendation="Upgrade battery C-rating/parallel cells or add bulk capacitance + soft-start.",
                )
            )

    err_count = sum(1 for v in violations if v.severity == "error")
    warn_count = sum(1 for v in violations if v.severity == "warning")
    report = DrcReport(
        passed=(err_count == 0),
        error_count=err_count,
        warning_count=warn_count,
        violations=violations,
    )
    return report, power_budget
