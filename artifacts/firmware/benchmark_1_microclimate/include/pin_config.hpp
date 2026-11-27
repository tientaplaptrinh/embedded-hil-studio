#pragma once
#include <stdint.h>
#include "controller_core.hpp"
#include "hal.hpp"

#ifdef ARDUINO
#include <Arduino.h>
#endif

namespace pin_config {

constexpr int PIN_SHT31_SENSOR_SDA = 21;  // GPIO21 (I2C)
constexpr int PIN_SHT31_SENSOR_SCL = 22;  // GPIO22 (I2C)
constexpr int PIN_SUBSTRATE_ADC_AOUT = 32;  // GPIO32 (ADC)
constexpr int PIN_MIST_RELAY_COIL_DRIVE = 16;  // GPIO16 (GPIO)
constexpr int PIN_EXHAUST_FAN_PWM_CTRL = 4;  // GPIO4 (PWM)

inline ehil::ControllerConfig default_controller_config() {
    return ehil::ControllerConfig{
        ehil::Archetype::MICROCLIMATE_PID,
        50u,
        75.00f,
        2.500f,
        0.600f,
        0.180f,
        45000u,
        350u,
        28.00f
    };
}

#ifdef ARDUINO
inline void init_pins() {
    pinMode(PIN_MIST_RELAY_COIL_DRIVE, OUTPUT);
    pinMode(PIN_EXHAUST_FAN_PWM_CTRL, OUTPUT);
}

inline ehil::SensorReading sample_hardware_sensors() {
    // Hardware bus read hook (I2C SHT31 / Ultrasonic pulseIn / I2S DMA RMS)
    return ehil::SensorReading{75.00f, 25.0f, true};
}

inline void apply_hardware_actuators(const ehil::ActuatorCommand& cmd) {
    (void)cmd;
}
#endif

}  // namespace pin_config
