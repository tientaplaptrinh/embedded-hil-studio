#pragma once
#ifdef ARDUINO

#include <Arduino.h>
#include "controller_core.hpp"
#include "hal.hpp"
#include "pin_config.hpp"

namespace ehil {

class McuHardwareHal : public IHal {
public:
    McuHardwareHal() : rx_len_(0) {}

    void begin() {
        Serial.begin(115200);
        pin_config::init_pins();
    }

    uint32_t millis_now() const override { return static_cast<uint32_t>(millis()); }

    SensorReading read_sensors() override {
        return pin_config::sample_hardware_sensors();
    }

    void write_actuators(const ActuatorCommand& cmd) override {
        pin_config::apply_hardware_actuators(cmd);
    }

    bool read_command_line(char* buf, size_t max_len) override {
        while (Serial.available() > 0) {
            const char c = static_cast<char>(Serial.read());
            if (c == '\n' || c == '\r') {
                if (rx_len_ > 0) {
                    rx_buf_[rx_len_] = '\0';
                    strncpy(buf, rx_buf_, max_len - 1);
                    buf[max_len - 1] = '\0';
                    rx_len_ = 0;
                    return true;
                }
            } else if (rx_len_ + 1 < sizeof(rx_buf_)) {
                rx_buf_[rx_len_++] = c;
            }
        }
        return false;
    }

    void write_telemetry_line(const char* line) override {
        Serial.println(line);
    }

    void kick_watchdog(uint32_t /*now_ms*/) override {
        // Hardware watchdog feed hook (esp_task_wdt_reset / wdt_reset)
    }

private:
    char rx_buf_[128];
    size_t rx_len_;
};

}  // namespace ehil

#endif  // ARDUINO
