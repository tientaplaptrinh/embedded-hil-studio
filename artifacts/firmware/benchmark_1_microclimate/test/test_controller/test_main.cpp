#include "controller_core.hpp"
#include "crc16.hpp"

#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

namespace {

class MockHal : public ehil::IHal {
public:
    uint32_t now = 0;
    ehil::SensorReading sr{55.0f, 24.5f, true};
    ehil::ActuatorCommand last_act{0.0f, 0.0f, 0.0f, false};
    char last_telemetry[256] = {0};
    char pending_cmd[160] = {0};
    bool has_cmd = false;
    uint32_t wdt_count = 0;

    uint32_t millis_now() const override { return now; }
    ehil::SensorReading read_sensors() override { return sr; }
    void write_actuators(const ehil::ActuatorCommand& cmd) override { last_act = cmd; }
    bool read_command_line(char* buf, size_t max_len) override {
        if (!has_cmd) return false;
        strncpy(buf, pending_cmd, max_len - 1);
        buf[max_len - 1] = '\0';
        has_cmd = false;
        return true;
    }
    void write_telemetry_line(const char* line) override {
        strncpy(last_telemetry, line, sizeof(last_telemetry) - 1);
        last_telemetry[sizeof(last_telemetry) - 1] = '\0';
    }
    void kick_watchdog(uint32_t /*now_ms*/) override { ++wdt_count; }
};

void test_crc16_and_framed_telemetry() {
    const char* vec = "123456789";
    const uint16_t crc = ehil::crc16_ccitt(vec, strlen(vec));
    assert(crc == 0x29B1u);

    MockHal hal;
    ehil::ControllerConfig cfg{
        ehil::Archetype::MICROCLIMATE_PID, 50, 75.0f, 2.2f, 0.35f, 0.15f, 30000, 400, 28.0f
    };
    ehil::ControllerCore core(hal, cfg);
    core.init(0);
    hal.now = 50;
    core.tick(50);

    const char* star = strrchr(hal.last_telemetry, '*');
    assert(star != nullptr);
    const size_t body_len = static_cast<size_t>(star - hal.last_telemetry);
    const uint16_t expected = ehil::crc16_ccitt(hal.last_telemetry, body_len);
    const unsigned int parsed_crc = static_cast<unsigned int>(strtoul(star + 1, nullptr, 16));
    assert(expected == static_cast<uint16_t>(parsed_crc));
}

void test_pid_clamping_and_anti_windup() {
    MockHal hal;
    ehil::ControllerConfig cfg{
        ehil::Archetype::MICROCLIMATE_PID, 50, 80.0f, 4.0f, 2.5f, 0.1f, 60000, 400, 28.0f
    };
    ehil::ControllerCore core(hal, cfg);
    core.init(0);

    // Hold huge positive error for 200 ticks: output must clamp <= 100 and integral must not wind up unbounded
    hal.sr = {20.0f, 25.0f, true};
    for (int i = 1; i <= 200; ++i) {
        hal.now = static_cast<uint32_t>(i * 50);
        core.tick(hal.now);
        assert(hal.last_act.primary_pct >= 0.0f && hal.last_act.primary_pct <= 100.0f);
    }

    // Immediately step PV above setpoint: anti-windup ensures immediate drop to 0% mist
    for (int i = 201; i <= 206; ++i) {
        hal.sr = {84.0f, 25.0f, true};
        hal.now = static_cast<uint32_t>(i * 50);
        core.tick(hal.now);
    }
    assert(hal.last_act.primary_pct == 0.0f);
    assert(hal.last_act.secondary_pct > 15.0f);
}

void test_sensor_nan_and_timeout_failsafe() {
    MockHal hal;
    ehil::ControllerConfig cfg{
        ehil::Archetype::MICROCLIMATE_PID, 50, 75.0f, 2.2f, 0.35f, 0.15f, 30000, 300, 28.0f
    };
    ehil::ControllerCore core(hal, cfg);
    core.init(0);

    hal.sr = {60.0f, 24.0f, true};
    core.tick(50);
    assert(core.state() == ehil::CtrlState::AUTO);
    assert(hal.last_act.primary_pct > 0.0f);

    // Inject NaN -> immediate FAILSAFE shutoff on same tick
    hal.sr = {NAN, 24.0f, true};
    core.tick(100);
    assert(core.state() == ehil::CtrlState::FAILSAFE);
    assert(hal.last_act.primary_pct == 0.0f);
    assert(hal.last_act.relay_closed == false);

    // Reset fault and test timeout disconnect (>300ms invalid)
    assert(core.handle_command("FAULT_RESET"));
    hal.sr = {60.0f, 24.0f, true};
    core.tick(150);
    assert(core.state() == ehil::CtrlState::AUTO);

    hal.sr = {60.0f, 24.0f, false};
    core.tick(500);
    assert(core.state() == ehil::CtrlState::FAILSAFE);
    assert((core.fault_flags() & ehil::FAULT_SENSOR_TIMEOUT) != 0);
    assert(hal.last_act.primary_pct == 0.0f);
}

void test_rover_obstacle_fsm_and_manual_switch() {
    MockHal hal;
    ehil::ControllerConfig cfg{
        ehil::Archetype::ROVER_OBSTACLE_FSM, 50, 70.0f, 1.0f, 0.0f, 0.0f, 30000, 400, 30.0f
    };
    ehil::ControllerCore core(hal, cfg);
    core.init(0);

    hal.sr = {95.0f, 10.0f, true};
    core.tick(50);
    assert(core.state() == ehil::CtrlState::AUTO);
    assert(hal.last_act.primary_pct > 40.0f);

    // Obstacle at 18 cm -> transitions to AVOID_SCAN then AVOID_TURN with differential wheel signs
    for (int i = 2; i <= 5; ++i) {
        hal.sr = {18.0f, 12.0f, true};
        core.tick(static_cast<uint32_t>(i * 50));
    }
    assert(core.state() == ehil::CtrlState::AVOID_SCAN || core.state() == ehil::CtrlState::AVOID_TURN);
    core.tick(500);
    assert(core.state() == ehil::CtrlState::AVOID_TURN);
    assert(hal.last_act.primary_pct * hal.last_act.secondary_pct < 0.0f);

    // Bluetooth manual mode switch
    assert(core.handle_command("MODE MANUAL"));
    assert(core.handle_command("SET manual_lr 55 45"));
    hal.sr = {80.0f, 0.0f, true};
    core.tick(600);
    assert(core.state() == ehil::CtrlState::MANUAL);
    assert(fabsf(hal.last_act.primary_pct - 55.0f) < 0.01f);
}

void test_command_parser_and_fuzz_resilience() {
    MockHal hal;
    ehil::ControllerConfig cfg{
        ehil::Archetype::MICROCLIMATE_PID, 50, 75.0f, 2.0f, 0.3f, 0.1f, 30000, 400, 28.0f
    };
    ehil::ControllerCore core(hal, cfg);
    core.init(0);

    assert(core.handle_command("SET kp 3.75\r\n"));
    assert(fabsf(core.kp() - 3.75f) < 1e-4f);
    assert(core.handle_command("SET setpoint 68.5"));
    assert(fabsf(core.setpoint() - 68.5f) < 1e-4f);

    // Fuzz 500 malformed, overlong, NaN, binary-ish strings without crash or NaN state corruption
    const char* malformed[] = {
        "",
        "   \r\n",
        "SET",
        "SET kp",
        "SET kp not_a_float",
        "SET kp nan",
        "SET kp inf",
        "SET unknown_param 12.3",
        "MODE",
        "MODE BOGUS",
        "GARBAGE_CMD 1 2 3 4 5 6 7 8 9",
        "SET setpoint 99999999999999999999999999999999999999999",
    };
    for (size_t round = 0; round < 500; ++round) {
        const char* sample = malformed[round % (sizeof(malformed) / sizeof(malformed[0]))];
        (void)core.handle_command(sample);
        assert(!isnan(core.kp()) && !isnan(core.setpoint()));
    }

    char huge[300];
    memset(huge, 'A', sizeof(huge) - 1);
    huge[sizeof(huge) - 1] = '\0';
    assert(!core.handle_command(huge));
    assert(fabsf(core.kp() - 3.75f) < 1e-4f);
}

}  // namespace

int main() {
    test_crc16_and_framed_telemetry();
    test_pid_clamping_and_anti_windup();
    test_sensor_nan_and_timeout_failsafe();
    test_rover_obstacle_fsm_and_manual_switch();
    test_command_parser_and_fuzz_resilience();
    printf("[NATIVE_TDD_PASS] All 5 C++17 firmware test suites passed with 0 errors.\n");
    return 0;
}
