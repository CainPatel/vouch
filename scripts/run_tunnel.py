#!/usr/bin/env python3
"""Start Vouch locally with an automatic public HTTPS tunnel for phone QR scanning."""
from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import threading
import time

PORT = os.getenv("PORT", "8080")
URL_RE = re.compile(r"https://[a-zA-Z0-9.-]+\.lhr\.life\b")


def main() -> int:
    found_url: list[str] = []
    ready = threading.Event()

    ssh_cmd = [
        "ssh",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "ExitOnForwardFailure=yes",
        "-R",
        f"80:127.0.0.1:{PORT}",
        "nokey@localhost.run",
    ]
    print(f"[tunnel] Opening HTTPS tunnel to 127.0.0.1:{PORT} via localhost.run...", flush=True)
    ssh_proc = subprocess.Popen(
        ssh_cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    def _reader() -> None:
        assert ssh_proc.stdout is not None
        for line in ssh_proc.stdout:
            m = URL_RE.search(line)
            if m and not found_url:
                found_url.append(m.group(0))
                ready.set()

    threading.Thread(target=_reader, daemon=True).start()
    ready.wait(timeout=8.0)

    env = os.environ.copy()
    if found_url:
        env["VOUCH_PUBLIC_URL"] = found_url[0]
        print(f"\n[tunnel] Phone QR Public HTTPS URL: {found_url[0]}", flush=True)
        print(f"[tunnel] Open laptop demo at:       http://localhost:{PORT}/demo\n", flush=True)
    else:
        print(
            f"[tunnel] Could not establish SSH tunnel within 8s; falling back to LAN IP.",
            flush=True,
        )

    uvicorn_proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "server.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            str(PORT),
        ],
        env=env,
    )

    def _shutdown(*_args) -> None:
        uvicorn_proc.terminate()
        ssh_proc.terminate()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        return uvicorn_proc.wait()
    finally:
        ssh_proc.terminate()
        time.sleep(0.1)


if __name__ == "__main__":
    raise SystemExit(main())
