#include "controller_core.hpp"
#include "crc16.hpp"

#include <ctype.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

namespace ehil {

namespace {

float clampf(float v, float lo, float hi) {
    if (v < lo) return lo;
    if (v > hi) return hi;
    return v;
}

float median3(float a, float b, float c) {
    if (a > b) { float t = a; a = b; b = t; }
    if (b > c) { float t = b; b = c; c = t; }
    if (a > b) { float t = a; a = b; b = t; }
    return b;
}

bool iequals(const char* a, const char* b) {
    while (*a && *b) {
        if (tolower(static_cast<unsigned char>(*a)) != tolower(static_cast<unsigned char>(*b))) {
            return false;
        }
        ++a;
        ++b;
    }
    return *a == '\0' && *b == '\0';
}

}  // namespace

ControllerCore::ControllerCore(IHal& hal, const ControllerConfig& cfg)
    : hal_(hal),
      cfg_(cfg),
      state_(CtrlState::AUTO),
      fault_flags_(FAULT_NONE),
      setpoint_(cfg.setpoint),
      kp_(cfg.kp),
      ki_(cfg.ki),
      kd_(cfg.kd),
      manual_out_(0.0f),
      manual_out2_(0.0f),
      integral_(0.0f),
      prev_pv_(0.0f),
      filter_primed_(false),
      med_buf_{0.0f, 0.0f, 0.0f},
      med_idx_(0),
      filtered_pv_(0.0f),
      last_tick_ms_(0),
      last_valid_sensor_ms_(0),
      continuous_on_start_ms_(0),
      was_actively_driving_(false),
      state_enter_ms_(0),
      scan_left_cm_(100.0f),
      scan_right_cm_(100.0f),
      turn_dir_(1.0f),
      watchdog_kicks_(0),
      last_cmd_{0.0f, 0.0f, 0.0f, false} {}

void ControllerCore::init(uint32_t now_ms) {
    last_tick_ms_ = now_ms;
    last_valid_sensor_ms_ = now_ms;
    state_enter_ms_ = now_ms;
    continuous_on_start_ms_ = now_ms;
}

const char* ControllerCore::state_name(CtrlState s) {
    switch (s) {
        case CtrlState::AUTO: return "AUTO";
        case CtrlState::MANUAL: return "MANUAL";
        case CtrlState::FAILSAFE: return "FAILSAFE";
        case CtrlState::AVOID_SCAN: return "AVOID_SCAN";
        case CtrlState::AVOID_TURN: return "AVOID_TURN";
        default: return "UNKNOWN";
    }
}

float ControllerCore::filter_sample(float raw) {
    if (!filter_primed_) {
        med_buf_[0] = raw;
        med_buf_[1] = raw;
        med_buf_[2] = raw;
        med_idx_ = 0;
        filtered_pv_ = raw;
        prev_pv_ = raw;
        filter_primed_ = true;
        return filtered_pv_;
    }
    med_buf_[med_idx_] = raw;
    med_idx_ = static_cast<uint8_t>((med_idx_ + 1u) % 3u);
    const float med = median3(med_buf_[0], med_buf_[1], med_buf_[2]);
    // Exponential moving average (alpha = 0.55) for responsive noise suppression
    filtered_pv_ = 0.55f * med + 0.45f * filtered_pv_;
    return filtered_pv_;
}

void ControllerCore::enter_failsafe(uint8_t reason_flag) {
    state_ = CtrlState::FAILSAFE;
    fault_flags_ = static_cast<uint8_t>(fault_flags_ | reason_flag);
    integral_ = 0.0f;
    filter_primed_ = false;
    was_actively_driving_ = false;
    last_cmd_ = ActuatorCommand{0.0f, 0.0f, 0.0f, false};
    hal_.write_actuators(last_cmd_);
}

void ControllerCore::tick(uint32_t now_ms) {
    // Drain non-blocking incoming serial commands
    char cmd_buf[160];
    uint8_t drained = 0;
    while (drained < 8u && hal_.read_command_line(cmd_buf, sizeof(cmd_buf))) {
        handle_command(cmd_buf);
        ++drained;
    }

    const uint32_t elapsed_ms = (now_ms >= last_tick_ms_) ? (now_ms - last_tick_ms_) : cfg_.period_ms;
    if (elapsed_ms < cfg_.period_ms && filter_primed_) {
        return;
    }
    const float dt_s = (elapsed_ms > 0u) ? (static_cast<float>(elapsed_ms) * 0.001f)
                                         : (static_cast<float>(cfg_.period_ms) * 0.001f);
    last_tick_ms_ = now_ms;

    hal_.kick_watchdog(now_ms);
    ++watchdog_kicks_;

    const SensorReading sr = hal_.read_sensors();
    const bool sample_bad = (!sr.valid) || isnan(sr.primary) || isinf(sr.primary);

    if (sample_bad) {
        if (isnan(sr.primary) || isinf(sr.primary)) {
            enter_failsafe(FAULT_SENSOR_NAN);
            emit_telemetry(now_ms, 0.0f);
            return;
        }
        if ((now_ms - last_valid_sensor_ms_) >= cfg_.sensor_timeout_ms) {
            enter_failsafe(FAULT_SENSOR_TIMEOUT);
            emit_telemetry(now_ms, sr.secondary);
            return;
        }
    } else {
        last_valid_sensor_ms_ = now_ms;
        // Auto-recover from sensor-disconnect failsafe once clean readings return OR via FAULT_RESET
        filter_sample(sr.primary);
    }

    const float clean_pv2 = (isnan(sr.secondary) || isinf(sr.secondary)) ? 0.0f : sr.secondary;

    if (state_ == CtrlState::FAILSAFE) {
        last_cmd_ = ActuatorCommand{0.0f, 0.0f, 0.0f, false};
        hal_.write_actuators(last_cmd_);
        emit_telemetry(now_ms, clean_pv2);
        return;
    }

    if (state_ == CtrlState::MANUAL) {
        float p1 = clampf(manual_out_, 0.0f, 100.0f);
        float p2 = clampf(manual_out2_, -100.0f, 100.0f);
        // Rover hard collision interlock even in manual mode
        if (cfg_.archetype == Archetype::ROVER_OBSTACLE_FSM && filtered_pv_ < 14.0f && p1 > 0.0f && p2 > 0.0f) {
            p1 = 0.0f;
            p2 = 0.0f;
        }
        last_cmd_ = ActuatorCommand{p1, p2, 0.0f, p1 > 50.0f};
        hal_.write_actuators(last_cmd_);
        prev_pv_ = filtered_pv_;
        emit_telemetry(now_ms, clean_pv2);
        return;
    }

    switch (cfg_.archetype) {
        case Archetype::MICROCLIMATE_PID:
            step_microclimate(now_ms, dt_s, clean_pv2);
            break;
        case Archetype::ROVER_OBSTACLE_FSM:
            step_rover(now_ms, clean_pv2);
            break;
        case Archetype::EDGE_VOICE_DISPLAY:
            step_voice_node(now_ms, clean_pv2);
            break;
    }

    prev_pv_ = filtered_pv_;
    hal_.write_actuators(last_cmd_);
    emit_telemetry(now_ms, clean_pv2);
}

void ControllerCore::step_microclimate(uint32_t now_ms, float dt_s, float pv2_temp_c) {
    const float err = setpoint_ - filtered_pv_;
    const float p_term = kp_ * err;
    const float d_meas = (dt_s > 1e-4f) ? (-kd_ * (filtered_pv_ - prev_pv_) / dt_s) : 0.0f;

    // Candidate integral update with clamping anti-windup
    const float i_cand = clampf(integral_ + ki_ * err * dt_s, -40.0f, 85.0f);
    const float raw_u = p_term + i_cand + d_meas;
    const float clamped_u = clampf(raw_u, 0.0f, 100.0f);

    const bool saturating_high = (raw_u > 100.0f) && (err > 0.0f);
    const bool saturating_low = (raw_u < 0.0f) && (err < 0.0f);
    if (!saturating_high && !saturating_low) {
        integral_ = i_cand;
    }

    // Soft lead tapering near setpoint to prevent misting thermal/transport-lag overshoot
    float mist_pct = clamped_u;
    if (err < 2.0f && err > -0.5f && (filtered_pv_ - prev_pv_) > 0.08f) {
        mist_pct = clampf(mist_pct * 0.55f, 0.0f, 55.0f);
    }

    // Active exhaust fan modulation if RH exceeds setpoint + 0.5% or chamber temp > 29C
    float fan_pct = 6.0f;
    if (filtered_pv_ > setpoint_ + 0.4f) {
        fan_pct = clampf(15.0f + (filtered_pv_ - setpoint_) * 28.0f, 6.0f, 100.0f);
        mist_pct = 0.0f;
    } else if (pv2_temp_c > 29.0f) {
        fan_pct = clampf(20.0f + (pv2_temp_c - 29.0f) * 20.0f, 6.0f, 100.0f);
    }

    // Max continuous misting ON-time safety interlock
    if (mist_pct > 10.0f) {
        if (!was_actively_driving_) {
            was_actively_driving_ = true;
            continuous_on_start_ms_ = now_ms;
        } else if ((now_ms - continuous_on_start_ms_) > cfg_.max_continuous_on_ms) {
            fault_flags_ = static_cast<uint8_t>(fault_flags_ | FAULT_MAX_ONTIME);
            mist_pct = 0.0f;
            fan_pct = 60.0f;
        }
    } else {
        was_actively_driving_ = false;
        fault_flags_ = static_cast<uint8_t>(fault_flags_ & ~FAULT_MAX_ONTIME);
    }

    last_cmd_ = ActuatorCommand{mist_pct, fan_pct, 0.0f, mist_pct >= 15.0f};
}

void ControllerCore::step_rover(uint32_t now_ms, float pv2_side_bias) {
    if (state_ == CtrlState::AUTO) {
        if (filtered_pv_ < cfg_.obstacle_stop_cm) {
            state_ = CtrlState::AVOID_SCAN;
            state_enter_ms_ = now_ms;
            scan_left_cm_ = filtered_pv_ + pv2_side_bias;
            scan_right_cm_ = filtered_pv_ - pv2_side_bias;
            last_cmd_ = ActuatorCommand{0.0f, 0.0f, 45.0f, false};
            return;
        }
        const float cruise = clampf(setpoint_, 25.0f, 90.0f);
        // Gentle proportional slow-down when approaching caution zone
        float scale = 1.0f;
        if (filtered_pv_ < cfg_.obstacle_stop_cm * 1.6f) {
            scale = clampf(filtered_pv_ / (cfg_.obstacle_stop_cm * 1.6f), 0.45f, 1.0f);
        }
        const float spd = cruise * scale;
        const float sweep_deg = ((now_ms / 250u) % 2u == 0u) ? 20.0f : -20.0f;
        last_cmd_ = ActuatorCommand{spd, spd, sweep_deg, false};
        return;
    }

    if (state_ == CtrlState::AVOID_SCAN) {
        if ((now_ms - state_enter_ms_) < 150u) {
            last_cmd_ = ActuatorCommand{0.0f, 0.0f, -45.0f, false};
            return;
        }
        turn_dir_ = (pv2_side_bias >= 0.0f) ? 1.0f : -1.0f;
        state_ = CtrlState::AVOID_TURN;
        state_enter_ms_ = now_ms;
    }

    if (state_ == CtrlState::AVOID_TURN) {
        const uint32_t turn_elapsed = now_ms - state_enter_ms_;
        if (turn_elapsed >= 250u && filtered_pv_ > (cfg_.obstacle_stop_cm + 14.0f)) {
            state_ = CtrlState::AUTO;
            state_enter_ms_ = now_ms;
            last_cmd_ = ActuatorCommand{50.0f, 50.0f, 0.0f, false};
            return;
        }
        // Differential-drive zero-radius pivot turn away from wall
        if (turn_dir_ > 0.0f) {
            last_cmd_ = ActuatorCommand{62.0f, -62.0f, 0.0f, false};
        } else {
            last_cmd_ = ActuatorCommand{-62.0f, 62.0f, 0.0f, false};
        }
    }
}

void ControllerCore::step_voice_node(uint32_t /*now_ms*/, float /*pv2_cpu_pct*/) {
    // AGC gain targeting setpoint dB SPL + dynamic TFT backlight wake on voice activity
    const float err = setpoint_ - filtered_pv_;
    const float gain_pct = clampf(50.0f + kp_ * err, 5.0f, 95.0f);
    const float tft_bl_pct = (filtered_pv_ > 48.0f) ? 92.0f : 35.0f;
    last_cmd_ = ActuatorCommand{gain_pct, tft_bl_pct, 0.0f, filtered_pv_ > 48.0f};
}

bool ControllerCore::handle_command(const char* raw_line) {
    if (raw_line == nullptr) return false;

    // Copy and trim whitespace/CR/LF safely in fixed stack buffer
    char buf[160];
    size_t j = 0;
    while (raw_line[j] != '\0' && isspace(static_cast<unsigned char>(raw_line[j]))) {
        ++j;
    }
    size_t len = 0;
    while (raw_line[j] != '\0' && raw_line[j] != '\r' && raw_line[j] != '\n' && len + 1 < sizeof(buf)) {
        buf[len++] = raw_line[j++];
    }
    buf[len] = '\0';
    if (len == 0) return false;

    char* saveptr = nullptr;
#if defined(_MSC_VER)
    char* tok0 = strtok_s(buf, " \t", &saveptr);
#else
    char* tok0 = strtok_r(buf, " \t", &saveptr);
#endif
    if (tok0 == nullptr) return false;

    if (iequals(tok0, "FAULT_RESET")) {
        fault_flags_ = FAULT_NONE;
        integral_ = 0.0f;
        was_actively_driving_ = false;
        last_valid_sensor_ms_ = last_tick_ms_;
        if (state_ == CtrlState::FAILSAFE) {
            state_ = CtrlState::AUTO;
        }
        return true;
    }

    if (iequals(tok0, "MODE")) {
#if defined(_MSC_VER)
        char* mode_tok = strtok_s(nullptr, " \t", &saveptr);
#else
        char* mode_tok = strtok_r(nullptr, " \t", &saveptr);
#endif
        if (mode_tok == nullptr) {
            fault_flags_ = static_cast<uint8_t>(fault_flags_ | FAULT_CMD_PARSE_WARN);
            return false;
        }
        if (iequals(mode_tok, "MANUAL")) {
            state_ = CtrlState::MANUAL;
            return true;
        }
        if (iequals(mode_tok, "AUTO")) {
            if (state_ != CtrlState::FAILSAFE) {
                state_ = CtrlState::AUTO;
                return true;
            }
            return false;
        }
        fault_flags_ = static_cast<uint8_t>(fault_flags_ | FAULT_CMD_PARSE_WARN);
        return false;
    }

    if (iequals(tok0, "SET")) {
#if defined(_MSC_VER)
        char* key_tok = strtok_s(nullptr, " \t", &saveptr);
        char* val_tok = strtok_s(nullptr, " \t", &saveptr);
#else
        char* key_tok = strtok_r(nullptr, " \t", &saveptr);
        char* val_tok = strtok_r(nullptr, " \t", &saveptr);
#endif
        if (key_tok == nullptr || val_tok == nullptr) {
            fault_flags_ = static_cast<uint8_t>(fault_flags_ | FAULT_CMD_PARSE_WARN);
            return false;
        }
        char* endp = nullptr;
        const float val = strtof(val_tok, &endp);
        if (endp == val_tok || isnan(val) || isinf(val)) {
            fault_flags_ = static_cast<uint8_t>(fault_flags_ | FAULT_CMD_PARSE_WARN);
            return false;
        }

        if (iequals(key_tok, "kp")) {
            kp_ = clampf(val, 0.0f, 50.0f);
            return true;
        }
        if (iequals(key_tok, "ki")) {
            ki_ = clampf(val, 0.0f, 25.0f);
            return true;
        }
        if (iequals(key_tok, "kd")) {
            kd_ = clampf(val, 0.0f, 25.0f);
            return true;
        }
        if (iequals(key_tok, "setpoint") || iequals(key_tok, "sp")) {
            setpoint_ = clampf(val, -100.0f, 500.0f);
            return true;
        }
        if (iequals(key_tok, "manual_out")) {
            manual_out_ = clampf(val, 0.0f, 100.0f);
            manual_out2_ = clampf(val, -100.0f, 100.0f);
            return true;
        }
        if (iequals(key_tok, "manual_lr")) {
            manual_out_ = clampf(val, 0.0f, 100.0f);
#if defined(_MSC_VER)
            char* val2_tok = strtok_s(nullptr, " \t", &saveptr);
#else
            char* val2_tok = strtok_r(nullptr, " \t", &saveptr);
#endif
            if (val2_tok != nullptr) {
                manual_out2_ = clampf(strtof(val2_tok, nullptr), -100.0f, 100.0f);
            }
            return true;
        }
    }

    fault_flags_ = static_cast<uint8_t>(fault_flags_ | FAULT_CMD_PARSE_WARN);
    return false;
}

void ControllerCore::emit_telemetry(uint32_t now_ms, float pv2) {
    char json_buf[224];
    const int n = snprintf(
        json_buf,
        sizeof(json_buf),
        "{\"t_ms\":%lu,\"sp\":%.2f,\"pv\":%.2f,\"pv2\":%.2f,\"out\":%.2f,\"out2\":%.2f,\"state\":\"%s\",\"fault\":%u}",
        static_cast<unsigned long>(now_ms),
        static_cast<double>(setpoint_),
        static_cast<double>(filtered_pv_),
        static_cast<double>(pv2),
        static_cast<double>(last_cmd_.primary_pct),
        static_cast<double>(last_cmd_.secondary_pct),
        state_name(state_),
        static_cast<unsigned int>(fault_flags_)
    );
    if (n <= 0 || static_cast<size_t>(n) >= sizeof(json_buf)) {
        return;
    }
    const uint16_t crc = crc16_ccitt(json_buf, static_cast<size_t>(n));
    char framed[240];
    snprintf(framed, sizeof(framed), "%s*%04X", json_buf, static_cast<unsigned int>(crc));
    hal_.write_telemetry_line(framed);
}

}  // namespace ehil
