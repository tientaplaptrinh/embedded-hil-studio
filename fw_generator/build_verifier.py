"""C++17 Native TDD & Strict Zero-Warning Firmware Build Verifier."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FirmwareBuildResult:
    project_dir: Path
    unit_test_binary: Path
    hil_firmware_binary: Path
    mcu_syntax_verified: bool
    unit_tests_passed: bool
    compiler_used: str
    pio_native_tested: bool
    stdout_summary: str


def _render_arduino_mock_header(target_dir: Path) -> Path:
    """Minimal strict C++17 Arduino API mock header so `ARDUINO` MCU code path (`hal_mcu.hpp`
    + `pin_config.hpp` + `main.cpp` `setup()`/`loop()`) is also compiled with `-Wall -Wextra -Werror`!"""
    mock_dir = target_dir / "build_VerifyMcuMock"
    mock_dir.mkdir(parents=True, exist_ok=True)
    header = mock_dir / "Arduino.h"
    header.write_text(
        """#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#define INPUT 0x0
#define OUTPUT 0x1
#define INPUT_PULLUP 0x2
#define LOW 0x0
#define HIGH 0x1

inline uint32_t millis() { return 0; }
inline void pinMode(int, int) {}
inline void digitalWrite(int, int) {}
inline int digitalRead(int) { return 0; }
inline int analogRead(int) { return 512; }
inline void analogWrite(int, int) {}

struct HardwareSerialMock {
    void begin(unsigned long) {}
    int available() { return 0; }
    int read() { return -1; }
    void println(const char* s) { (void)s; }
};

static HardwareSerialMock Serial;
""",
        encoding="utf-8",
    )
    return mock_dir


def compile_and_verify_firmware(
    project_dir: Path,
    *,
    try_pio_native: bool = False,
) -> FirmwareBuildResult:
    """Compile C++17 unit tests, run native TDD suite, compile interactive HIL firmware binary,
    and verify ARDUINO MCU HAL compilation with strict `-std=c++17 -Wall -Wextra -Werror`."""
    gpp = shutil.which("g++")
    if not gpp:
        raise RuntimeError("g++ compiler not found on PATH.")

    build_dir = project_dir / ".native_build"
    build_dir.mkdir(parents=True, exist_ok=True)
    exe_ext = ".exe" if os.name == "nt" else ""

    test_bin = build_dir / f"unit_tests_{os.getpid()}{exe_ext}"
    hil_bin = build_dir / f"firmware_hil{exe_ext}"
    if hil_bin.exists():
        try:
            hil_bin.unlink()
        except PermissionError:
            hil_bin = build_dir / f"firmware_hil_{os.getpid()}{exe_ext}"
    mcu_obj = build_dir / f"mcu_hal_check_{os.getpid()}.o"

    common_flags = [
        gpp,
        "-std=c++17",
        "-O2",
        "-Wall",
        "-Wextra",
        "-Werror",
        f"-I{project_dir / 'include'}",
        f"-I{project_dir / 'src'}",
    ]

    # 1. Build Native TDD Unit Test Binary
    cmd_test_build = [
        *common_flags,
        str(project_dir / "src" / "controller_core.cpp"),
        str(project_dir / "test" / "test_controller" / "test_main.cpp"),
        "-o",
        str(test_bin),
    ]
    res_tb = subprocess.run(cmd_test_build, capture_output=True, text=True, check=False)
    if res_tb.returncode != 0:
        raise RuntimeError(
            f"Native unit test build failed in {project_dir}:\n{res_tb.stdout}\n{res_tb.stderr}"
        )

    # 2. Execute Native TDD Unit Tests
    res_tr = subprocess.run([str(test_bin)], capture_output=True, text=True, timeout=15, check=False)
    if res_tr.returncode != 0:
        raise RuntimeError(
            f"Native unit tests failed in {project_dir}:\n{res_tr.stdout}\n{res_tr.stderr}"
        )

    # 3. Build Interactive Native HIL Firmware Subprocess Binary
    cmd_hil_build = [
        *common_flags,
        str(project_dir / "src" / "controller_core.cpp"),
        str(project_dir / "src" / "main.cpp"),
        "-o",
        str(hil_bin),
    ]
    res_hb = subprocess.run(cmd_hil_build, capture_output=True, text=True, check=False)
    if res_hb.returncode != 0:
        raise RuntimeError(
            f"HIL firmware binary build failed in {project_dir}:\n{res_hb.stdout}\n{res_hb.stderr}"
        )

    # 4. Strict `-DARDUINO` compile check of MCU HAL (`hal_mcu.hpp` + `pin_config.hpp` + `setup()/loop()`)
    mock_inc = _render_arduino_mock_header(build_dir)
    cmd_mcu_check = [
        *common_flags,
        "-DARDUINO=10819",
        f"-I{mock_inc}",
        "-c",
        str(project_dir / "src" / "main.cpp"),
        "-o",
        str(mcu_obj),
    ]
    res_mcu = subprocess.run(cmd_mcu_check, capture_output=True, text=True, check=False)
    if res_mcu.returncode != 0:
        raise RuntimeError(
            f"MCU ARDUINO HAL strict compile check failed in {project_dir}:\n{res_mcu.stdout}\n{res_mcu.stderr}"
        )

    pio_ok = False
    summary_lines = [res_tr.stdout.strip()]
    if try_pio_native:
        root_venv_pio = project_dir.parent.parent.parent / ".venv" / "Scripts" / "pio.exe"
        pio_exe = str(root_venv_pio) if root_venv_pio.exists() else shutil.which("pio")
        if pio_exe:
            res_pio = subprocess.run(
                [pio_exe, "test", "-e", "native"],
                cwd=str(project_dir),
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            pio_ok = res_pio.returncode == 0
            summary_lines.append(f"pio test -e native: {'PASS' if pio_ok else 'FALLBACK_GPP'}")

    return FirmwareBuildResult(
        project_dir=project_dir,
        unit_test_binary=test_bin,
        hil_firmware_binary=hil_bin,
        mcu_syntax_verified=True,
        unit_tests_passed=True,
        compiler_used=gpp,
        pio_native_tested=pio_ok,
        stdout_summary=" | ".join(s for s in summary_lines if s),
    )
