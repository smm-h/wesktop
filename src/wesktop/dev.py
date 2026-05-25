"""Development mode: Vite + wesktop server in a single command."""

from __future__ import annotations

import importlib
import logging
import socket
import subprocess
import time
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


def dev(
    target: str | Callable,
    *,
    vite_command: str = "npm run dev",
    vite_port: int = 5173,
    host: str | None = None,
    port: int | None = None,
    pid_path: Path | None = None,
    name: str = "WESKTOP",
    pre_serve: Callable[[], None] | None = None,
) -> None:
    """Start Vite dev server + wesktop ASGI server for development.

    Spawns Vite as a subprocess, waits for it to be ready, then starts
    the wesktop server with ViteDevProxy middleware. All frontend
    requests are proxied to Vite (with HMR), API requests are handled
    by the wesktop router. Kills Vite on shutdown.
    """
    from wesktop.middleware import ViteDevProxy
    from wesktop.server import serve

    # Resolve the target to a callable ASGI app
    if isinstance(target, str):
        module_path, attr = target.rsplit(":", 1)
        module = importlib.import_module(module_path)
        app = getattr(module, attr)
    else:
        app = target

    # Wrap with ViteDevProxy
    wrapped = ViteDevProxy(app, vite_port=vite_port)

    # Spawn Vite
    logger.info("Starting Vite dev server: %s", vite_command)
    vite_proc = subprocess.Popen(
        vite_command,
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    # Wait for Vite to be ready
    deadline = time.monotonic() + 15  # 15s timeout
    ready = False
    while time.monotonic() < deadline:
        try:
            sock = socket.create_connection(("127.0.0.1", vite_port), timeout=1)
            sock.close()
            ready = True
            break
        except (ConnectionRefusedError, OSError):
            if vite_proc.poll() is not None:
                stderr = vite_proc.stderr.read().decode() if vite_proc.stderr else ""
                raise RuntimeError(f"Vite process exited with code {vite_proc.returncode}: {stderr}")
            time.sleep(0.3)

    if not ready:
        vite_proc.terminate()
        raise RuntimeError(f"Vite dev server did not start within 15s on port {vite_port}")

    logger.info("Vite ready on port %d", vite_port)

    try:
        serve(
            wrapped,
            foreground=True,
            host=host,
            port=port,
            pid_path=pid_path,
            name=name,
            pre_serve=pre_serve,
        )
    finally:
        logger.info("Stopping Vite dev server")
        vite_proc.terminate()
        try:
            vite_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            vite_proc.kill()
            vite_proc.wait()
