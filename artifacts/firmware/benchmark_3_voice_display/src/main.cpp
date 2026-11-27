#include "controller_core.hpp"
#include "pin_config.hpp"

#ifdef ARDUINO
#include "hal_mcu.hpp"

namespace {
ehil::McuHardwareHal g_hal;
ehil::ControllerCore g_core(g_hal, pin_config::default_controller_config());
}  // namespace

void setup() {
    g_hal.begin();
    g_core.init(g_hal.millis_now());
}

void loop() {
    g_core.tick(g_hal.millis_now());
}

#else
#include "hal_native_hil.hpp"

int main() {
    ehil::NativeHilHal hal;
    ehil::ControllerCore core(hal, pin_config::default_controller_config());
    hal.run_stdio_loop(core);
    return 0;
}
#endif
