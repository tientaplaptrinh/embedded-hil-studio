#pragma once
#include <stdint.h>
#include "controller_core.hpp"
#include "hal.hpp"

#ifdef ARDUINO
#include <Arduino.h>
#endif

namespace pin_config {

constexpr int PIN_L298N_DRIVE_ENA = 3;  // D3 (MOTOR_DRIVER)
constexpr int PIN_L298N_DRIVE_ENB = 5;  // D5 (MOTOR_DRIVER)
constexpr int PIN_L298N_DRIVE_IN1 = 2;  // D2 (MOTOR_DRIVER)
constexpr int PIN_L298N_DRIVE_IN2 = 4;  // D4 (MOTOR_DRIVER)
constexpr int PIN_L298N_DRIVE_IN3 = 7;  // D7 (MOTOR_DRIVER)
constexpr int PIN_L298N_DRIVE_IN4 = 8;  // D8 (MOTOR_DRIVER)
constexpr int PIN_ULTRASONIC_FRONT_TRIG = 14;  // A0 (GPIO)
constexpr int PIN_ULTRASONIC_FRONT_ECHO = 15;  // A1 (GPIO)
constexpr int PIN_PAN_SERVO_SERVO_SIG = 9;  // D9 (SERVO)
constexpr int PIN_BT_HC05_MCU_RX_FROM_BT_TX = 0;  // D0 (UART)
constexpr int PIN_BT_HC05_MCU_TX_TO_BT_RX = 1;  // D1 (UART)

inline ehil::ControllerConfig default_controller_config() {
    return ehil::ControllerConfig{
        ehil::Archetype::ROVER_OBSTACLE_FSM,
        50u,
        68.00f,
        1.500f,
        0.000f,
        0.050f,
        60000u,
        400u,
        30.00f
    };
}

#ifdef ARDUINO
inline void init_pins() {
    pinMode(PIN_L298N_DRIVE_ENA, OUTPUT);
    pinMode(PIN_L298N_DRIVE_ENB, OUTPUT);
    pinMode(PIN_L298N_DRIVE_IN1, OUTPUT);
    pinMode(PIN_L298N_DRIVE_IN2, OUTPUT);
    pinMode(PIN_L298N_DRIVE_IN3, OUTPUT);
    pinMode(PIN_L298N_DRIVE_IN4, OUTPUT);
    pinMode(PIN_ULTRASONIC_FRONT_TRIG, OUTPUT);
    pinMode(PIN_ULTRASONIC_FRONT_ECHO, INPUT);
}

inline ehil::SensorReading sample_hardware_sensors() {
    // Hardware bus read hook (I2C SHT31 / Ultrasonic pulseIn / I2S DMA RMS)
    return ehil::SensorReading{68.00f, 25.0f, true};
}

inline void apply_hardware_actuators(const ehil::ActuatorCommand& cmd) {
    (void)cmd;
}
#endif

}  // namespace pin_config
