#pragma once
#include <stddef.h>
#include <stdint.h>

namespace ehil {

struct SensorReading {
    float primary;
    float secondary;
    bool valid;
};

struct ActuatorCommand {
    float primary_pct;    // [0..100] (e.g. mist duty, left motor PWM, audio amp gain)
    float secondary_pct;  // [-100..100] or [0..100] (e.g. exhaust fan PWM, right motor PWM, TFT BL)
    float servo_deg;      // [-90..90] scan angle for rover ultrasonic servo
    bool relay_closed;
};

class IHal {
public:
    virtual ~IHal() = default;
    virtual uint32_t millis_now() const = 0;
    virtual SensorReading read_sensors() = 0;
    virtual void write_actuators(const ActuatorCommand& cmd) = 0;
    virtual bool read_command_line(char* buf, size_t max_len) = 0;
    virtual void write_telemetry_line(const char* line) = 0;
    virtual void kick_watchdog(uint32_t now_ms) = 0;
};

}  // namespace ehil
