"""Phase 0 Environment & Toolchain Audit Script."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def probe_cmd(cmd: list[str]) -> dict[str, object]:
    exe = shutil.which(cmd[0])
    if not exe:
        return {"installed": False, "path": None, "version": None}
    try:
        proc = subprocess.run(
            [exe, *cmd[1:]],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        out = (proc.stdout or proc.stderr).strip().splitlines()
        version = out[0] if out else ""
        return {
            "installed": proc.returncode == 0,
            "path": exe,
            "version": version,
            "returncode": proc.returncode,
        }
    except Exception as exc:
        return {"installed": False, "path": exe, "version": str(exc)}


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    artifacts = root / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "gui_audit").mkdir(parents=True, exist_ok=True)

    venv_pio = root / ".venv" / "Scripts" / "pio.exe"
    pio_cmd = [str(venv_pio), "--version"] if venv_pio.exists() else ["pio", "--version"]

    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "os": platform.platform(),
        "python_venv": {
            "installed": True,
            "path": sys.executable,
            "version": sys.version.split()[0],
        },
        "tools": {
            "python3": probe_cmd([sys.executable, "--version"]),
            "node": probe_cmd(["node", "--version"]),
            "npm": probe_cmd(["npm.cmd" if os.name == "nt" else "npm", "--version"]),
            "g++": probe_cmd(["g++", "--version"]),
            "clang++": probe_cmd(["clang++", "--version"]),
            "pio": probe_cmd(pio_cmd),
        },
    }

    out_path = artifacts / "toolchain_audit.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote toolchain audit to {out_path}")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
