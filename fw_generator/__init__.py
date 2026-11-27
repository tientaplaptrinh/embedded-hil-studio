"""Firmware Synthesizer, Protocol & Build Verifier package."""

from .build_verifier import FirmwareBuildResult, compile_and_verify_firmware
from .firmware_synthesizer import synthesize_firmware_project
from .protocol import build_command_line, crc16_ccitt, format_framed_json, parse_telemetry_line

__all__ = [
    "FirmwareBuildResult",
    "build_command_line",
    "compile_and_verify_firmware",
    "crc16_ccitt",
    "format_framed_json",
    "parse_telemetry_line",
    "synthesize_firmware_project",
]
