from __future__ import annotations

"""Granian ASGI server lifecycle -- PID file management, port checks, serve/stop/status."""

import atexit
import logging
import os
import signal
import socket
import sys
import threading
import time
import types
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from granian import Granian

log = logging.getLogger(__name__)

# Counter for generating unique synthetic module names when serving callables.
_callable_counter = 0
_callable_counter_lock = threading.Lock()


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
    _remove_port_file(_port_file_path(pid_path))
    sys.exit(0)


def check_already_running(pid_path: Path, name: str = "server") -> int | None:
    """Check if another instance is running. Returns the PID if running, None otherwise.

    Stale PID files (process dead) are cleaned up automatically.
    """
    if not pid_path.exists():
        return None
    try:
        pid = int(pid_path.read_text().strip())
    except (ValueError, OSError):
        # Corrupt or unreadable PID file -- treat as stale.
        _remove_pid(pid_path)
        return None
    try:
        os.kill(pid, 0)  # probe whether the process is alive
    except ProcessLookupError:
        # Process is dead; stale PID file.
        _remove_pid(pid_path)
        return None
    except PermissionError:
        pass  # Process exists but we can't signal it
    return pid  # Process is alive


def ensure_port_available(host: str, port: int, name: str = "server") -> int:
    """Ensure port is available. If occupied by a previous instance, stop it.

    Probes the port. If something responds to GET /health with {"status":"ok"},
    it's likely our own stale server -- kill it via the OS.
    Otherwise, exit with a diagnostic error.

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
            pass  # Port in use -- investigate

    # Port is occupied. Try health check to see if it's our server.
    try:
        resp = urllib.request.urlopen(f"http://{host}:{port}/health", timeout=2)
        data = resp.read()
        if b'"ok"' in data:
            # It's our server. Find and kill it.
            log.warning("Port %d has a stale %s instance. Stopping it.", port, name)
            _kill_port_holder(host, port)
            # Verify port is now free
            for _ in range(10):
                time.sleep(0.5)
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s2:
                    s2.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    try:
                        s2.bind((host, port))
                        return port
                    except OSError:
                        continue
    except Exception:
        pass

    log.error(
        "Port %d on %s is already in use. Use a different port "
        "or stop the process holding it.",
        port,
        host,
    )
    sys.exit(1)


def _kill_port_holder(host: str, port: int) -> None:
    """Kill the process holding a port."""
    import subprocess

    try:
        # Use lsof to find the PID
        result = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            for pid_str in result.stdout.strip().split("\n"):
                pid_str = pid_str.strip()
                if pid_str and pid_str.isdigit():
                    pid = int(pid_str)
                    try:
                        os.kill(pid, signal.SIGTERM)
                    except (ProcessLookupError, PermissionError):
                        pass
    except (FileNotFoundError, subprocess.TimeoutExpired):
        # lsof not available -- try fuser
        try:
            result = subprocess.run(
                ["fuser", f"{port}/tcp"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                for pid_str in result.stdout.strip().split():
                    pid_str = pid_str.strip()
                    if pid_str.isdigit():
                        os.kill(int(pid_str), signal.SIGTERM)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass


def _resolve_target(target: str | Callable) -> str:
    """Convert a target to a Granian-compatible string.

    If target is already a string (e.g. "myapp:app"), return as-is.
    If target is a callable, register it on a synthetic module so Granian
    can import it via its string-based loader.
    """
    if isinstance(target, str):
        return target
    global _callable_counter
    with _callable_counter_lock:
        _callable_counter += 1
        mod_name = f"_wesktop_target_{_callable_counter}"
    mod = types.ModuleType(mod_name)
    mod.app = target  # type: ignore[attr-defined]
    sys.modules[mod_name] = mod
    return f"{mod_name}:app"


def _find_free_port(host: str = "127.0.0.1") -> int:
    """Find an ephemeral port that is currently free on *host*."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def _port_file_path(pid_path: Path) -> Path:
    """Derive the port file path from a PID file path.

    E.g. ``.pixelweaver.pid`` -> ``.pixelweaver.port``.
    """
    return pid_path.with_suffix(".port")


def _write_port_file(pid_path: Path, port: int) -> None:
    """Write the bound port alongside the PID file."""
    port_path = _port_file_path(pid_path)
    port_path.write_text(str(port))
    atexit.register(_remove_port_file, port_path)


def _remove_port_file(port_path: Path) -> None:
    """Remove a port file if it exists."""
    try:
        port_path.unlink(missing_ok=True)
    except OSError:
        pass


def read_port_file(pid_path: Path) -> int | None:
    """Read the port stored alongside a PID file. Returns None if missing or unreadable."""
    port_path = _port_file_path(pid_path)
    if not port_path.exists():
        return None
    try:
        return int(port_path.read_text().strip())
    except (ValueError, OSError):
        return None


def _resolve_host_port(
    host: str | None,
    port: int | None,
    name: str,
) -> tuple[str, int]:
    """Resolve host and port from explicit args or env vars.

    Explicit args override env vars. If neither is provided, raise ValueError.
    """
    env_prefix = name.upper()

    if host is None:
        env_host = os.environ.get(f"{env_prefix}_HOST")
        if env_host is not None:
            host = env_host
        else:
            raise ValueError(
                f"host must be provided explicitly or via {env_prefix}_HOST env var"
            )

    if port is None:
        env_port = os.environ.get(f"{env_prefix}_PORT")
        if env_port is not None:
            try:
                port = int(env_port)
            except ValueError:
                raise ValueError(
                    f"{env_prefix}_PORT env var must be an integer, got {env_port!r}"
                )
        else:
            raise ValueError(
                f"port must be provided explicitly or via {env_prefix}_PORT env var"
            )

    return host, port


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


def _run_server(target: str, host: str, port: int) -> None:
    """Create and run a Granian server. Used as the reload subprocess target."""
    server = _make_server(target, host, port)
    server.serve()


def _serve_subprocess(target: str, host: str, port: int, pid_path_str: str, name: str) -> None:
    """Entry point for the server subprocess. Runs granian in foreground mode."""
    pid_path = Path(pid_path_str)
    _write_pid(pid_path)
    _write_port_file(pid_path, port)
    server = _make_server(target, host, port)
    server.serve()


def serve_background(
    target: str | Callable,
    *,
    host: str,
    port: int,
    pid_path: Path,
    name: str = "WESKTOP",
) -> str:
    """Start the server as an independent background process. Returns the URL.

    Unlike ``serve(foreground=False)`` which uses a daemon thread (dies with the
    parent), this spawns a fully detached subprocess that survives the parent
    exiting. The subprocess writes its own PID and port files.

    Parameters
    ----------
    target:
        ASGI application -- either a module path string (e.g. "myapp:app")
        or a callable ASGI application object.
    host:
        Bind address.
    port:
        Bind port. Pass 0 to pick a random free port.
    pid_path:
        Path for the PID file. The subprocess writes this, not the caller.
    name:
        Application name for log messages.

    Returns
    -------
    str
        The URL the server is listening on (e.g. "http://127.0.0.1:8000").

    Raises
    ------
    RuntimeError
        If the server process exits prematurely or fails to start within 10s.
    """
    import subprocess as _subprocess

    target_str = _resolve_target(target)

    # Find a free port if port is 0
    if port == 0:
        port = _find_free_port(host)

    # Spawn server subprocess, fully detached from the parent process group
    proc = _subprocess.Popen(
        [
            sys.executable, "-c",
            f"from wesktop.server import _serve_subprocess; "
            f"_serve_subprocess({target_str!r}, {host!r}, {port!r}, "
            f"{str(pid_path)!r}, {name!r})",
        ],
        stdin=_subprocess.DEVNULL,
        stdout=_subprocess.DEVNULL,
        stderr=_subprocess.DEVNULL,
        start_new_session=True,
    )

    # Wait for server to be ready by polling the health endpoint
    url = f"http://{host}:{port}"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            resp = urllib.request.urlopen(f"{url}/health", timeout=1)
            if resp.status == 200:
                break
        except Exception:
            if proc.poll() is not None:
                raise RuntimeError(
                    f"Server process exited with code {proc.returncode}"
                )
            time.sleep(0.3)
    else:
        proc.terminate()
        raise RuntimeError("Server did not start within 10 seconds")

    log.info("%s started as background process (PID %d) on %s", name, proc.pid, url)
    return url


def serve(
    target: str | Callable,
    *,
    foreground: bool,
    host: str | None = None,
    port: int | None = None,
    pid_path: Path | None = None,
    name: str = "WESKTOP",
    pre_serve: Callable[[], None] | None = None,
    reload: bool = False,
    single_instance: bool = True,
) -> str | None:
    """Start Granian serving the ASGI app.

    Parameters
    ----------
    target:
        ASGI application -- either a module path string (e.g. "myapp:app")
        or a callable ASGI application object.
    foreground:
        Required. When True, blocks the calling thread. When False, spawns a
        daemon thread and returns the URL string.
    host:
        Bind address. Falls back to {NAME}_HOST env var. ValueError if neither.
    port:
        Bind port. Falls back to {NAME}_PORT env var. ValueError if neither.
    pid_path:
        If given, enables PID file management (detect existing instances,
        write PID, register cleanup).
    name:
        Application name for env var prefix (uppercased) and log messages.
        Default "WESKTOP".
    pre_serve:
        Optional callable invoked synchronously after PID/port checks but
        before Granian starts.
    reload:
        When True, watches .py files in the current working directory and
        restarts the server on changes. Requires foreground=True.
    single_instance:
        When True (default), checks for an existing running instance via the
        PID file and exits with an error if one is found. When False, skips
        the PID check (but still writes the PID file if pid_path is given).

    Returns
    -------
    str | None
        When foreground=False, returns the URL string (e.g. "http://127.0.0.1:8000").
        When foreground=True, returns None (blocks until server stops).
    """
    if reload and not foreground:
        raise ValueError("reload requires foreground=True")

    resolved_host, resolved_port = _resolve_host_port(host, port, name)
    target_str = _resolve_target(target)

    # Port 0 means "pick a random free port"
    if resolved_port == 0:
        resolved_port = _find_free_port(resolved_host)

    if pid_path is not None and single_instance:
        existing_pid = check_already_running(pid_path, name)
        if existing_pid is not None:
            log.error(
                "%s is already running (PID %d). Stop it before starting another.",
                name,
                existing_pid,
            )
            sys.exit(1)
    ensure_port_available(resolved_host, resolved_port, name)
    if pid_path is not None:
        _write_pid(pid_path)
        _write_port_file(pid_path, resolved_port)

    if pre_serve is not None:
        pre_serve()

    url = f"http://{resolved_host}:{resolved_port}"

    if reload:
        from watchfiles import PythonFilter, run_process

        log.info("Starting %s on %s (reload enabled)", name, url)
        run_process(
            ".",
            target=_run_server,
            args=(target_str, resolved_host, resolved_port),
            watch_filter=PythonFilter(),
            callback=lambda changes: log.info(
                "Detected changes, restarting: %s",
                {path for _, path in changes},
            ),
        )
        return None

    server = _make_server(target_str, resolved_host, resolved_port)

    if foreground:
        log.info("Starting %s on %s", name, url)
        server.serve()
        return None
    else:
        # Granian registers signal handlers in startup(), which fails in
        # daemon threads.  Signal handling is unnecessary here -- the daemon
        # thread dies when the main thread exits.
        from granian import _signals
        from granian.server import common as _granian_common

        _noop = lambda *a, **kw: None
        _signals.set_main_signals = _noop
        _granian_common.set_main_signals = _noop

        thread = threading.Thread(target=server.serve, daemon=True)
        thread.start()

        log.info("%s started in background on %s", name, url)
        return url


@dataclass
class ServerStatus:
    """Result of a status check on a server process."""

    running: bool
    pid: int | None
    healthy: bool | None


def _cleanup_pid_and_port(pid_path: Path) -> None:
    """Remove both the PID file and its companion port file."""
    _remove_pid(pid_path)
    _remove_port_file(_port_file_path(pid_path))


def stop(pid_path: Path) -> None:
    """Stop a server by reading its PID file.

    Sends SIGTERM, waits up to 10s polling with os.kill(pid, 0), then
    escalates to SIGKILL. Cleans up the PID file and port file.

    Raises FileNotFoundError if PID file does not exist.
    If the process is already gone (stale PID file), removes the PID file
    and returns normally.
    """
    if not pid_path.exists():
        raise FileNotFoundError(f"PID file not found: {pid_path}")

    try:
        pid = int(pid_path.read_text().strip())
    except (ValueError, OSError) as exc:
        _cleanup_pid_and_port(pid_path)
        raise FileNotFoundError(f"Corrupt or unreadable PID file: {pid_path}") from exc

    # Check if process is alive first
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        pid_path.unlink(missing_ok=True)
        _remove_port_file(_port_file_path(pid_path))
        log.info("Process %d is not running (stale PID file removed)", pid)
        return
    except PermissionError:
        pass  # process exists but we can't probe -- proceed with SIGTERM

    # Send SIGTERM
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        _cleanup_pid_and_port(pid_path)
        return
    except PermissionError:
        _cleanup_pid_and_port(pid_path)
        raise

    # Wait up to 10s for process to exit
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            # Process exited cleanly
            _cleanup_pid_and_port(pid_path)
            return
        except PermissionError:
            break  # can't check -- fall through to SIGKILL
        time.sleep(0.1)

    # Escalate to SIGKILL
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        _cleanup_pid_and_port(pid_path)
        return
    except PermissionError:
        _cleanup_pid_and_port(pid_path)
        raise

    _cleanup_pid_and_port(pid_path)


def status(pid_path: Path, health_url: str | None = None) -> ServerStatus:
    """Check the status of a server process.

    Parameters
    ----------
    pid_path:
        Path to the PID file.
    health_url:
        Optional URL to probe for health (e.g. "http://127.0.0.1:8000/health").
        If provided and the process is running, an HTTP GET is attempted with
        a short timeout.

    Returns
    -------
    ServerStatus
        Dataclass with running, pid, and healthy fields.
    """
    if not pid_path.exists():
        return ServerStatus(running=False, pid=None, healthy=None)

    try:
        pid = int(pid_path.read_text().strip())
    except (ValueError, OSError):
        return ServerStatus(running=False, pid=None, healthy=None)

    # Check liveness
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return ServerStatus(running=False, pid=pid, healthy=None)
    except PermissionError:
        # Process exists but can't signal -- still consider running
        pass

    # Process is running -- check health if URL provided
    healthy: bool | None = None
    if health_url is not None:
        try:
            req = urllib.request.Request(health_url, method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                healthy = 200 <= resp.status < 400
        except Exception:
            healthy = False

    return ServerStatus(running=True, pid=pid, healthy=healthy)
