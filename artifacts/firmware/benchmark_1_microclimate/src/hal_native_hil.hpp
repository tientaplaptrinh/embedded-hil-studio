#pragma once
#ifndef ARDUINO

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "controller_core.hpp"
#include "hal.hpp"

namespace ehil {

class NativeHilHal : public IHal {
public:
    NativeHilHal()
        : sim_millis_(0),
          current_sr_{50.0f, 25.0f, true},
          last_act_{0.0f, 0.0f, 0.0f, false},
          has_queued_cmd_(false),
          wdt_ms_(0) {
        queued_cmd_[0] = '\0';
    }

    uint32_t millis_now() const override { return sim_millis_; }

    SensorReading read_sensors() override { return current_sr_; }

    void write_actuators(const ActuatorCommand& cmd) override { last_act_ = cmd; }

    bool read_command_line(char* buf, size_t max_len) override {
        if (!has_queued_cmd_ || max_len == 0) {
            return false;
        }
        strncpy(buf, queued_cmd_, max_len - 1);
        buf[max_len - 1] = '\0';
        has_queued_cmd_ = false;
        return true;
    }

    void write_telemetry_line(const char* line) override {
        fprintf(stdout, "%s\n", line);
        fflush(stdout);
    }

    void kick_watchdog(uint32_t now_ms) override { wdt_ms_ = now_ms; }

    void run_stdio_loop(ControllerCore& core) {
        core.init(0);
        char line[256];
        while (fgets(line, sizeof(line), stdin) != nullptr) {
            if (strncmp(line, "QUIT", 4) == 0) {
                break;
            }
            if (strncmp(line, "SENS ", 5) == 0) {
                unsigned long dt_ms = 50;
                char p1_tok[48] = {0};
                char p2_tok[48] = {0};
                int valid_int = 1;
                const int parsed = sscanf(line + 5, "%lu %47s %47s %d", &dt_ms, p1_tok, p2_tok, &valid_int);
                if (parsed >= 4) {
                    sim_millis_ += static_cast<uint32_t>(dt_ms);
                    float v1 = NAN;
                    if (strcmp(p1_tok, "nan") != 0 && strcmp(p1_tok, "NAN") != 0) {
                        v1 = strtof(p1_tok, nullptr);
                    }
                    const float v2 = strtof(p2_tok, nullptr);
                    current_sr_ = SensorReading{v1, v2, valid_int != 0};
                    core.tick(sim_millis_);
                }
            } else {
                strncpy(queued_cmd_, line, sizeof(queued_cmd_) - 1);
                queued_cmd_[sizeof(queued_cmd_) - 1] = '\0';
                has_queued_cmd_ = true;
                core.handle_command(queued_cmd_);
                has_queued_cmd_ = false;
            }
        }
    }

private:
    uint32_t sim_millis_;
    SensorReading current_sr_;
    ActuatorCommand last_act_;
    bool has_queued_cmd_;
    char queued_cmd_[160];
    uint32_t wdt_ms_;
};

}  // namespace ehil

#endif  // !ARDUINO
