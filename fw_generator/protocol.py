"""CRC-16-CCITT Framed JSON Telemetry & Live Command Protocol."""

from __future__ import annotations

import json

from contracts.hw_models import ControlCommand, TelemetryFrame


def crc16_ccitt(data: bytes, poly: int = 0x1021, init: int = 0xFFFF) -> int:
    """Compute standard CRC-16-CCITT (0x1021, init 0xFFFF), matching C++17 crc16.hpp."""
    crc = init
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ poly) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def format_framed_json(payload: dict) -> str:
    body = json.dumps(payload, separators=(",", ":"))
    crc = crc16_ccitt(body.encode("utf-8"))
    return f"{body}*{crc:04X}"


def parse_telemetry_line(line: str) -> TelemetryFrame | None:
    """Parse a CRC-16 framed JSON telemetry line (`{...}*ABCD`) into a TelemetryFrame."""
    stripped = line.strip()
    if not stripped or not stripped.startswith("{"):
        return None

    crc_ok = True
    json_part = stripped
    if "*" in stripped:
        json_part, crc_hex = stripped.rsplit("*", 1)
        try:
            expected_crc = int(crc_hex.strip(), 16)
            actual_crc = crc16_ccitt(json_part.encode("utf-8"))
            crc_ok = expected_crc == actual_crc
        except ValueError:
            crc_ok = False

    try:
        obj = json.loads(json_part)
    except json.JSONDecodeError:
        return None

    if "t_ms" not in obj or "pv" not in obj:
        return None

    known_keys = {"t_ms", "sp", "pv", "pv2", "out", "out2", "state", "fault"}
    extra = {k: v for k, v in obj.items() if k not in known_keys}

    return TelemetryFrame(
        t_ms=int(obj.get("t_ms", 0)),
        sp=float(obj.get("sp", 0.0)),
        pv=float(obj.get("pv", 0.0)),
        pv_secondary=float(obj.get("pv2", 0.0)),
        out=float(obj.get("out", 0.0)),
        out_secondary=float(obj.get("out2", 0.0)),
        state=str(obj.get("state", "UNKNOWN")),
        fault=int(obj.get("fault", 0)),
        crc_ok=crc_ok,
        raw_line=stripped,
        extra=extra,
    )


def build_command_line(cmd: ControlCommand) -> str:
    return cmd.to_wire_line() + "\n"
