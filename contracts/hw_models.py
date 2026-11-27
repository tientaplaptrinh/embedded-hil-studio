"""Strict Pydantic v2 data models for hardware architecture, DRC, firmware & HIL."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PinCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pin_id: str
    gpio_num: int
    label: str
    capabilities: list[str] = Field(default_factory=list)
    input_only: bool = False
    internal_pullup: bool = True
    forbidden: bool = False
    forbidden_reason: str | None = None
    reserved_when: list[str] = Field(default_factory=list)
    strapping: bool = False
    strapping_note: str | None = None
    adc_unit: Literal["ADC1", "ADC2"] | None = None
    timer_group: str | None = None
    hardware_uart: bool = False
    bus_roles: dict[str, str] = Field(default_factory=dict)


class BoardDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    board_id: str
    name: str
    mcu: str
    pio_board: str
    pio_platform: str
    pio_framework: str = "arduino"
    logic_voltage: float
    max_pin_current_safe_ma: float
    max_pin_current_abs_ma: float
    max_regulator_current_ma: float
    base_idle_current_ma: float
    base_active_current_ma: float
    wifi_active_extra_ma: float = 0.0
    wifi_peak_extra_ma: float = 0.0
    supports_wifi: bool = False
    flexible_pin_matrix: bool = False
    pins: list[PinCapability]

    def get_pin(self, pin_id: str) -> PinCapability | None:
        for pin in self.pins:
            if pin.pin_id == pin_id:
                return pin
        return None


class SignalReq(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal_name: str
    required_capability: str
    direction: Literal["in", "out", "inout"] = "out"
    shared_bus: str | None = None


class PeripheralSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instance_id: str
    part_number: str
    name: str = ""
    category: Literal["sensor", "actuator", "display", "audio", "comms", "driver"]
    supply_voltage: float
    logic_voltage: float
    idle_current_ma: float
    active_current_ma: float
    peak_current_ma: float
    duty_cycle: float = Field(default=0.5, ge=0.0, le=1.0)
    bus_type: Literal[
        "GPIO",
        "ADC",
        "PWM",
        "SERVO",
        "I2C",
        "SPI",
        "UART",
        "I2S_RX",
        "I2S_TX",
        "MOTOR_DRIVER",
    ]
    i2c_address: str | None = None
    has_i2c_mux: bool = False
    inductive_load: bool = False
    has_driver_stage: bool = False
    has_flyback_diode: bool = False
    has_level_shifter: bool = False
    uses_timer1_isr: bool = False
    powered_from_mcu_regulator: bool = True
    signals: list[SignalReq] = Field(default_factory=list)
    manual_pins: dict[str, str] = Field(default_factory=dict)
    bom_notes: str = ""


class BatterySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    nominal_voltage: float = Field(gt=0.0)
    capacity_mah: float = Field(ge=0.0)
    max_continuous_discharge_ma: float = Field(gt=0.0)
    regulator_efficiency: float = Field(default=0.85, gt=0.0, le=1.0)
    usable_dod: float = Field(default=0.85, gt=0.0, le=1.0)


class ControlProfileSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    archetype: Literal["microclimate_pid", "rover_obstacle_fsm", "edge_voice_display"]
    loop_hz: int = Field(default=20, ge=1, le=1000)
    setpoint: float = 75.0
    kp: float = 2.2
    ki: float = 0.35
    kd: float = 0.15
    max_continuous_on_ms: int = 30000
    sensor_timeout_ms: int = 400
    obstacle_stop_cm: float = 28.0


class EmbeddedProjectSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    name: str
    description: str = ""
    board_id: str
    wifi_enabled: bool = False
    opi_psram_enabled: bool = False
    usb_jtag_reserved: bool = True
    peripherals: list[PeripheralSpec]
    battery: BatterySpec | None = None
    control: ControlProfileSpec


class PinAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instance_id: str
    part_number: str
    signal_name: str
    pin_id: str
    gpio_num: int
    bus_type: str
    shared_bus: str | None = None
    wire_color: str = "#38bdf8"
    notes: str = ""


class DrcViolation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Literal["error", "warning"]
    rule_id: str
    peripheral_id: str | None = None
    pin_id: str | None = None
    message: str
    recommendation: str


class DrcReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    error_count: int
    warning_count: int
    violations: list[DrcViolation] = Field(default_factory=list)


class PowerBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idle_current_ma: float
    average_current_ma: float
    peak_current_ma: float
    mcu_regulator_current_ma: float
    mcu_regulator_limit_ma: float
    system_voltage_v: float
    idle_power_w: float
    average_power_w: float
    peak_power_w: float
    battery_name: str | None = None
    battery_capacity_mah: float | None = None
    estimated_runtime_hours: float | None = None
    breakdown: dict[str, dict[str, float]] = Field(default_factory=dict)


class BomItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref: str
    part_number: str
    description: str
    quantity: int = 1
    notes: str = ""


class HardwareBlueprint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    project_name: str
    board: BoardDef
    pin_assignments: list[PinAssignment]
    drc: DrcReport
    power_budget: PowerBudget
    auto_repaired: bool = False
    repair_notes: list[str] = Field(default_factory=list)
    svg_diagram: str = ""
    wiring_markdown: str = ""
    bom: list[BomItem] = Field(default_factory=list)


class TelemetryFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    t_ms: int
    sp: float
    pv: float
    pv_secondary: float = 0.0
    out: float
    out_secondary: float = 0.0
    state: str
    fault: int = 0
    crc_ok: bool = True
    raw_line: str = ""
    extra: dict[str, float | int | str] = Field(default_factory=dict)


class ControlCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: Literal["SET", "FAULT_RESET", "MODE"]
    param: str | None = None
    value: float | str | None = None

    def to_wire_line(self) -> str:
        if self.command == "FAULT_RESET":
            return "FAULT_RESET"
        if self.command == "MODE":
            return f"MODE {self.value}"
        return f"SET {self.param} {self.value}"


class HilAssertionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    benchmark_id: str
    passed: bool
    duration_sim_s: float
    settling_time_s: float | None = None
    steady_state_error: float | None = None
    max_overshoot: float | None = None
    collisions: int = 0
    failsafe_latency_ms: float | None = None
    mode_switch_verified: bool = False
    frames_captured: int = 0
    crc_errors: int = 0
    assertions: dict[str, bool] = Field(default_factory=dict)
    details: list[str] = Field(default_factory=list)


# Convenient aliases matching Monorepo overview terminology
ProjectSpec = EmbeddedProjectSpec
PinAllocation = PinAssignment
