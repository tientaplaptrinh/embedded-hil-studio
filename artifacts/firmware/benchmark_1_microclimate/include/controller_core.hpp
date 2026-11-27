#pragma once
#include <stddef.h>
#include <stdint.h>
#include "hal.hpp"

namespace ehil {

enum class Archetype : uint8_t {
    MICROCLIMATE_PID = 0,
    ROVER_OBSTACLE_FSM = 1,
    EDGE_VOICE_DISPLAY = 2
};

enum class CtrlState : uint8_t {
    AUTO = 0,
    MANUAL = 1,
    FAILSAFE = 2,
    AVOID_SCAN = 3,
    AVOID_TURN = 4
};

enum FaultFlags : uint8_t {
    FAULT_NONE = 0x00,
    FAULT_SENSOR_NAN = 0x01,
    FAULT_SENSOR_TIMEOUT = 0x02,
    FAULT_MAX_ONTIME = 0x04,
    FAULT_CMD_PARSE_WARN = 0x08
};

struct ControllerConfig {
    Archetype archetype;
    uint32_t period_ms;
    float setpoint;
    float kp;
    float ki;
    float kd;
    uint32_t max_continuous_on_ms;
    uint32_t sensor_timeout_ms;
    float obstacle_stop_cm;
};

class ControllerCore {
public:
    ControllerCore(IHal& hal, const ControllerConfig& cfg);

    void init(uint32_t now_ms);
    void tick(uint32_t now_ms);
    bool handle_command(const char* raw_line);

    CtrlState state() const { return state_; }
    uint8_t fault_flags() const { return fault_flags_; }
    float setpoint() const { return setpoint_; }
    float kp() const { return kp_; }
    float ki() const { return ki_; }
    float kd() const { return kd_; }
    float filtered_pv() const { return filtered_pv_; }
    ActuatorCommand last_output() const { return last_cmd_; }
    uint32_t watchdog_kicks() const { return watchdog_kicks_; }

    static const char* state_name(CtrlState s);

private:
    float filter_sample(float raw);
    void step_microclimate(uint32_t now_ms, float dt_s, float pv2);
    void step_rover(uint32_t now_ms, float pv2);
    void step_voice_node(uint32_t now_ms, float pv2);
    void enter_failsafe(uint8_t reason_flag);
    void emit_telemetry(uint32_t now_ms, float pv2);

    IHal& hal_;
    ControllerConfig cfg_;
    CtrlState state_;
    uint8_t fault_flags_;

    float setpoint_;
    float kp_;
    float ki_;
    float kd_;
    float manual_out_;
    float manual_out2_;

    float integral_;
    float prev_pv_;
    bool filter_primed_;
    float med_buf_[3];
    uint8_t med_idx_;
    float filtered_pv_;

    uint32_t last_tick_ms_;
    uint32_t last_valid_sensor_ms_;
    uint32_t continuous_on_start_ms_;
    bool was_actively_driving_;

    uint32_t state_enter_ms_;
    float scan_left_cm_;
    float scan_right_cm_;
    float turn_dir_;
    uint32_t watchdog_kicks_;
    ActuatorCommand last_cmd_;
};

}  // namespace ehil
