#pragma once
#include <stdint.h>
#include "controller_core.hpp"
#include "hal.hpp"

#ifdef ARDUINO
#include <Arduino.h>
#endif

namespace pin_config {

constexpr int PIN_INMP441_MIC_SCK = 4;  // GPIO4 (I2S_RX)
constexpr int PIN_INMP441_MIC_WS = 5;  // GPIO5 (I2S_RX)
constexpr int PIN_INMP441_MIC_SD = 6;  // GPIO6 (I2S_RX)
constexpr int PIN_MAX98357A_AMP_BCLK = 7;  // GPIO7 (I2S_TX)
constexpr int PIN_MAX98357A_AMP_LRC = 8;  // GPIO8 (I2S_TX)
constexpr int PIN_MAX98357A_AMP_DIN = 9;  // GPIO9 (I2S_TX)
constexpr int PIN_ILI9341_TFT_MOSI = 11;  // GPIO11 (SPI)
constexpr int PIN_ILI9341_TFT_MISO = 13;  // GPIO13 (SPI)
constexpr int PIN_ILI9341_TFT_SCK = 12;  // GPIO12 (SPI)
constexpr int PIN_ILI9341_TFT_CS = 10;  // GPIO10 (SPI)
constexpr int PIN_ILI9341_TFT_DC = 14;  // GPIO14 (SPI)
constexpr int PIN_ILI9341_TFT_RST = 15;  // GPIO15 (SPI)
constexpr int PIN_ILI9341_TFT_LED_PWM = 1;  // GPIO1 (SPI)

inline ehil::ControllerConfig default_controller_config() {
    return ehil::ControllerConfig{
        ehil::Archetype::EDGE_VOICE_DISPLAY,
        40u,
        65.00f,
        1.800f,
        0.200f,
        0.050f,
        60000u,
        400u,
        28.00f
    };
}

#ifdef ARDUINO
inline void init_pins() {
    // Bus pins configured by peripheral drivers
}

inline ehil::SensorReading sample_hardware_sensors() {
    // Hardware bus read hook (I2C SHT31 / Ultrasonic pulseIn / I2S DMA RMS)
    return ehil::SensorReading{65.00f, 25.0f, true};
}

inline void apply_hardware_actuators(const ehil::ActuatorCommand& cmd) {
    (void)cmd;
}
#endif

}  // namespace pin_config
