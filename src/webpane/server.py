from __future__ import annotations

"""Granian ASGI server lifecycle -- PID file management, port checks, start/stop."""

import atexit
import logging
import os
import signal
import socket
import sys
import threading
from pathlib import Path

from granian import Granian

log = logging.getLogger(__name__)


def _write_pid(pid_path: Path) -> None:
    """Write the current PID to disk, become process group leader, and register cleanup handlers.

    Becoming a process group leader (via os.setpgid(0, 0)) lets the 'stop'
    subcommand signal our entire process group with os.killpg, so granian
    worker subprocesses die with us instead of being orphaned.
    """
    try:
        os.setpgid(0, 0)  # 0,0 = current process becomes its own group leader
    except OSError:
        # Already a group leader, or not permitted in this context (e.g. some
        # supervised contexts) -- not fatal.
        pass
    pid_path.write_text(str(os.getpid()))
    atexit.register(_remove_pid, pid_path)
    # Clean up PID file on SIGTERM and SIGINT (Ctrl+C).
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda signum, _frame: _signal_handler(signum, _frame, pid_path))


def _remove_pid(pid_path: Path) -> None:
    """Remove the PID file if it exists."""
    try:
        pid_path.unlink(missing_ok=True)
    except OSError:
        pass


def _signal_handler(signum: int, _frame: object, pid_path: Path) -> None:
    """Handle SIGTERM/SIGINT: forward to our process group, clean up, exit."""
    # Restore default disposition so the forwarded signal doesn't recurse into us.
    signal.signal(signum, signal.SIG_DFL)
    try:
        os.killpg(os.getpgrp(), signum)
    except (ProcessLookupError, PermissionError):
        pass
    _remove_pid(pid_path)
    sys.exit(0)


def check_already_running(pid_path: Path, name: str = "server") -> None:
    """Exit if another instance is already running (based on the PID file)."""
    if not pid_path.exists():
        return
    try:
        pid = int(pid_path.read_text().strip())
    except (ValueError, OSError):
        # Corrupt or unreadable PID file -- treat as stale.
        _remove_pid(pid_path)
        return
    try:
        os.kill(pid, 0)  # probe whether the process is alive
    except ProcessLookupError:
        # Process is dead; stale PID file.
        _remove_pid(pid_path)
        return
    except PermissionError:
        # Process exists but we can't signal it -- still running.
        pass
    log.error(
        "%s is already running (PID %d). Stop it before starting another.",
        name,
        pid,
    )
    sys.exit(1)


def ensure_port_available(host: str, port: int) -> int:
    """Check that *port* on *host* is available; exit with a diagnostic error if not.

    Returns *port* on success.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        # SO_REUSEADDR matches Granian's behavior so our probe doesn't spuriously
        # fail during the kernel's brief TIME_WAIT after a recent stop. Without
        # this the bind raises EADDRINUSE while no process is actually listening.
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return port
        except OSError:
            log.error(
                "Port %d on %s is already in use. Use a different port "
                "or stop the process holding it.",
                port,
                host,
            )
            sys.exit(1)


def _make_server(target: str, host: str, port: int) -> Granian:
    """Create a Granian instance bound to *host* on *port*.

    *target* is an ASGI module path, e.g. ``"myapp:app"``.
    """
    return Granian(
        target=target,
        address=host,
        port=port,
        interface="asgi",
    )


def start_server(
    target: str,
    host: str = "127.0.0.1",
    port: int = 8000,
    pid_path: Path | None = None,
    name: str = "server",
) -> None:
    """Start Granian serving the ASGI app (blocks the calling thread).

    If *pid_path* is given, PID file management is enabled: an existing
    running instance is detected, the PID is written, and cleanup handlers
    are registered.
    """
    if pid_path is not None:
        check_already_running(pid_path, name)
    ensure_port_available(host, port)
    if pid_path is not None:
        _write_pid(pid_path)
    server = _make_server(target, host, port)
    log.info("Starting %s on http://%s:%d", name, host, port)
    server.serve()


def start_server_in_background(
    target: str,
    host: str = "127.0.0.1",
    port: int = 8000,
    pid_path: Path | None = None,
    name: str = "server",
) -> str:
    """Start Granian in a daemon thread and return the URL it listens on.

    The daemon thread dies automatically when the main thread exits.
    If *pid_path* is given, PID file management is enabled.
    """
    if pid_path is not None:
        check_already_running(pid_path, name)
    ensure_port_available(host, port)
    if pid_path is not None:
        _write_pid(pid_path)
    server = _make_server(target, host, port)
    url = f"http://{host}:{port}"
    thread = threading.Thread(target=server.serve, daemon=True)
    thread.start()
    log.info("%s started in background on %s", name, url)
    return url
