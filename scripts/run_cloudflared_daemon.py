"""Long-running Cloudflare HTTPS/WSS tunnel daemon that records the public URL."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT_DIR = Path(__file__).resolve().parent.parent
CLOUDFLARED = ROOT_DIR.parent / "cloudflared.exe"
URLS_JSON = ROOT_DIR / "artifacts" / "public_web_urls.json"


def update_urls(cf_url: str) -> None:
    URLS_JSON.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if URLS_JSON.exists():
        try:
            data = json.loads(URLS_JSON.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["cloudflare_tunnel_url"] = cf_url
    data.setdefault("github_pages_url", "https://tientaplaptrinh.github.io/embedded-hil-studio/")
    URLS_JSON.write_text(json.dumps(data, indent=2), encoding="utf-8")


def main() -> None:
    if not CLOUDFLARED.exists():
        print(f"cloudflared.exe not found at {CLOUDFLARED}", file=sys.stderr)
        sys.exit(1)

    proc = subprocess.Popen(
        [str(CLOUDFLARED), "tunnel", "--url", "http://127.0.0.1:8765"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    assert proc.stdout is not None
    pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
    found = False

    try:
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            if not found:
                m = pattern.search(line)
                if m:
                    url = m.group(0)
                    update_urls(url)
                    print(f"\n[CLOUDFLARE_TUNNEL_READY] {url}\n", flush=True)
                    found = True
    except KeyboardInterrupt:
        proc.terminate()
    finally:
        if proc.poll() is None:
            proc.terminate()
        time.sleep(0.2)


if __name__ == "__main__":
    main()
