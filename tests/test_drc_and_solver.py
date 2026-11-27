"""Unit tests for MCU databases, Pin Solver, Electrical DRC, Power Budget, and SVG/BOM."""

from __future__ import annotations

from contracts.hw_models import (
    ControlProfileSpec,
    EmbeddedProjectSpec,
    PeripheralSpec,
    SignalReq,
)
from hil_sim.stress_runner import load_benchmark_specs
from hw_architect import (
    architect_project,
    build_raw_assignments_with_manual,
    load_board,
    run_electrical_drc,
    solve_project_pins,
)


def test_board_databases_load_accurately() -> None:
    esp32 = load_board("esp32_devkit_v1")
    s3 = load_board("esp32_s3_devkitc")
    uno = load_board("arduino_uno")

    # ESP32 SPI flash pins 6-11 forbidden & GPIO 34-39 input-only
    for g in range(6, 12):
        pin = esp32.get_pin(f"GPIO{g}")
        assert pin is not None and pin.forbidden
    for g in (34, 35, 36, 39):
        pin = esp32.get_pin(f"GPIO{g}")
        assert pin is not None and pin.input_only and not pin.internal_pullup

    # ESP32-S3 Octal PSRAM/Flash pins 26-37 tagged
    for g in range(26, 38):
        pin = s3.get_pin(f"GPIO{g}")
        assert pin is not None and "opi_psram" in pin.reserved_when

    # Arduino Uno Timer1 on D9/D10
    assert uno.get_pin("D9").timer_group == "Timer1"
    assert uno.get_pin("D10").timer_group == "Timer1"
    assert uno.get_pin("D0").hardware_uart and uno.get_pin("D1").hardware_uart


def test_benchmark_1_drc_negative_and_auto_repair() -> None:
    specs = {s.project_id: s for s in load_benchmark_specs()}
    b1 = specs["benchmark_1_microclimate"]

    init_drc, blueprint = architect_project(b1, auto_repair=True)
    rule_ids = {v.rule_id for v in init_drc.violations if v.severity == "error"}

    # Must catch all 3 critical errors in initial flawed spec
    assert not init_drc.passed
    assert init_drc.error_count == 3
    assert "DRC_ADC2_WIFI_CONFLICT" in rule_ids
    assert "DRC_INPUT_ONLY_GPIO_OUTPUT" in rule_ids
    assert "DRC_INDUCTIVE_NO_DRIVER" in rule_ids

    # Auto-repaired blueprint must have 0 errors and valid SVG/BOM
    assert blueprint.auto_repaired
    assert blueprint.drc.passed
    assert blueprint.drc.error_count == 0
    assert "<svg" in blueprint.svg_diagram
    assert len(blueprint.bom) >= 5


def test_benchmark_2_uno_timer1_servo_pwm_and_uart_warning() -> None:
    specs = {s.project_id: s for s in load_benchmark_specs()}
    b2 = specs["benchmark_2_rover"]

    init_drc, blueprint = architect_project(b2, auto_repair=True)
    init_errors = {v.rule_id for v in init_drc.violations if v.severity == "error"}
    assert "DRC_UNO_TIMER1_SERVO_PWM" in init_errors

    # Repaired pinout avoids D9/D10 for L298N PWM while emitting D0/D1 UART warning
    assert blueprint.drc.passed
    assert blueprint.drc.error_count == 0
    warn_rules = {v.rule_id for v in blueprint.drc.violations if v.severity == "warning"}
    assert "DRC_UNO_HW_UART_SHARED" in warn_rules

    pwm_pins = {
        a.pin_id
        for a in blueprint.pin_assignments
        if a.instance_id == "l298n_drive" and a.signal_name in ("ENA", "ENB")
    }
    assert pwm_pins.isdisjoint({"D9", "D10"})
    assert blueprint.power_budget.estimated_runtime_hours is not None
    assert blueprint.power_budget.estimated_runtime_hours > 1.5


def test_benchmark_3_esp32_s3_opi_psram_and_strapping_avoidance() -> None:
    specs = {s.project_id: s for s in load_benchmark_specs()}
    b3 = specs["benchmark_3_voice_display"]

    _, blueprint = architect_project(b3, auto_repair=True)
    assert blueprint.drc.passed
    assert blueprint.drc.error_count == 0
    assert blueprint.drc.warning_count == 0

    opi_and_strap = {f"GPIO{g}" for g in range(26, 38)} | {"GPIO0", "GPIO3", "GPIO45", "GPIO46", "GPIO19", "GPIO20"}
    assigned = {a.pin_id for a in blueprint.pin_assignments}
    assert assigned.isdisjoint(opi_and_strap)
    assert blueprint.power_budget.peak_current_ma > 650.0
    assert blueprint.power_budget.mcu_regulator_current_ma < blueprint.power_budget.mcu_regulator_limit_ma


def test_5v_level_shift_and_i2c_clash_drc_detection_and_repair() -> None:
    board = load_board("esp32_devkit_v1")
    proj = EmbeddedProjectSpec(
        project_id="drc_edge_cases",
        name="5V Echo & Duplicate I2C Test",
        board_id="esp32_devkit_v1",
        wifi_enabled=False,
        control=ControlProfileSpec(archetype="microclimate_pid"),
        peripherals=[
            PeripheralSpec(
                instance_id="hc_sr04_raw",
                part_number="HC-SR04",
                category="sensor",
                supply_voltage=5.0,
                logic_voltage=5.0,
                idle_current_ma=2.0,
                active_current_ma=15.0,
                peak_current_ma=20.0,
                bus_type="GPIO",
                has_level_shifter=False,
                signals=[
                    SignalReq(signal_name="TRIG", required_capability="GPIO_OUT", direction="out"),
                    SignalReq(signal_name="ECHO", required_capability="GPIO_IN", direction="in"),
                ],
            ),
            PeripheralSpec(
                instance_id="sht_a",
                part_number="SHT31-D",
                category="sensor",
                supply_voltage=3.3,
                logic_voltage=3.3,
                idle_current_ma=0.2,
                active_current_ma=1.2,
                peak_current_ma=1.8,
                bus_type="I2C",
                i2c_address="0x44",
                signals=[
                    SignalReq(signal_name="SDA", required_capability="I2C_SDA", direction="inout", shared_bus="I2C0"),
                    SignalReq(signal_name="SCL", required_capability="I2C_SCL", direction="out", shared_bus="I2C0"),
                ],
            ),
            PeripheralSpec(
                instance_id="sht_b",
                part_number="SHT31-D",
                category="sensor",
                supply_voltage=3.3,
                logic_voltage=3.3,
                idle_current_ma=0.2,
                active_current_ma=1.2,
                peak_current_ma=1.8,
                bus_type="I2C",
                i2c_address="0x44",
                signals=[
                    SignalReq(signal_name="SDA", required_capability="I2C_SDA", direction="inout", shared_bus="I2C0"),
                    SignalReq(signal_name="SCL", required_capability="I2C_SCL", direction="out", shared_bus="I2C0"),
                ],
            ),
        ],
    )

    raw_assign = build_raw_assignments_with_manual(proj, board)
    raw_drc, _ = run_electrical_drc(proj, board, raw_assign)
    err_ids = {v.rule_id for v in raw_drc.violations if v.severity == "error"}
    assert "DRC_5V_TO_3V3_LEVEL_SHIFT" in err_ids
    assert "DRC_I2C_ADDR_CLASH" in err_ids

    _, repaired = architect_project(proj, auto_repair=True)
    assert repaired.drc.passed
    assert repaired.drc.error_count == 0
    assert len(solve_project_pins(proj, board)) == 6
