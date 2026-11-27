export interface PinAssignment {
  instance_id: string;
  part_number: string;
  signal_name: string;
  pin_id: string;
  gpio_num: number;
  bus_type: string;
  shared_bus: string | null;
  wire_color: string;
  notes: string;
}

export interface DrcViolation {
  severity: "error" | "warning";
  rule_id: string;
  peripheral_id: string | null;
  pin_id: string | null;
  message: string;
  recommendation: string;
}

export interface DrcReport {
  passed: boolean;
  error_count: number;
  warning_count: number;
  violations: DrcViolation[];
}

export interface PowerBudget {
  idle_current_ma: number;
  average_current_ma: number;
  peak_current_ma: number;
  mcu_regulator_current_ma: number;
  mcu_regulator_limit_ma: number;
  system_voltage_v: number;
  idle_power_w: number;
  average_power_w: number;
  peak_power_w: number;
  battery_name: string | null;
  battery_capacity_mah: number | null;
  estimated_runtime_hours: number | null;
  breakdown: Record<string, { voltage_v: number; idle_ma: number; avg_ma: number; peak_ma: number }>;
}

export interface BomItem {
  ref: string;
  part_number: string;
  description: string;
  quantity: number;
  notes: string;
}

export interface HardwareBlueprint {
  project_id: string;
  project_name: string;
  board: {
    board_id: string;
    name: string;
    mcu: string;
    pio_board: string;
    logic_voltage: number;
    max_regulator_current_ma: number;
  };
  pin_assignments: PinAssignment[];
  drc: DrcReport;
  power_budget: PowerBudget;
  auto_repaired: boolean;
  repair_notes: string[];
  svg_diagram: string;
  wiring_markdown: string;
  bom: BomItem[];
}

export interface BlueprintResponse {
  mode: "virtual" | "serial";
  serial_port: string | null;
  baudrate: number;
  spec: {
    project_id: string;
    name: string;
    description: string;
    control: {
      archetype: string;
      loop_hz: number;
      setpoint: number;
      kp: number;
      ki: number;
      kd: number;
    };
  };
  initial_drc: DrcReport;
  blueprint: HardwareBlueprint;
  platformio_ini: string;
  pin_config_hpp: string;
  fault_state: {
    sensor_disconnected: boolean;
  };
}

export interface TelemetryFrame {
  t_ms: number;
  sp: number;
  pv: number;
  pv_secondary: number;
  out: number;
  out_secondary: number;
  state: string;
  fault: number;
  crc_ok: boolean;
  raw_line: string;
  extra: Record<string, number | string>;
}

export interface BenchmarkSummary {
  project_id: string;
  name: string;
  board_id: string;
  description: string;
}
