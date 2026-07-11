"""Native desktop window via pywebview, backed by a detached Granian ASGI server subprocess, with cross-process window refcounting and automatic server lifecycle.

Process-group / coordination story
----------------------------------
wesktop group-manages exactly ONE child: the detached server subprocess spawned
by ``serve_background`` (which becomes its own process-group leader so ``stop``
can signal the whole group and reap granian workers). wesktop does NOT own the
renderer child processes -- pywebview spawns and owns those (WebKitGTK/WebView2/
Cocoa) inside ``webview.start()``.

Because a single wesktop process can neither see nor count another wesktop
process's windows, window lifecycle is coordinated through the filesystem, not
in-process state:

- **Window markers** (``kind="window"`` in the fastware instance registry): one
  marker file per open native window, carrying ``{pid, window_id}``. Written
  before ``webview.start()`` and removed after it returns. The live-marker count
  (dead PIDs pruned by ``kill -0``) is the true number of open windows across
  ALL wesktop processes sharing this app's server. The server is stopped only
  when zero live window markers remain after this process's window closes -- so
  process A closing its last window never kills the server under process B's
  still-open window.
- **Focus-request markers** (``kind="focus-request"``): a platform-neutral,
  file-based focus signal. With ``second_open="focus-existing"``, a second
  launch drops a focus-request marker and exits; the window-owning process runs
  a ~1s daemon poll that consumes the request and raises its window. No DBus, no
  AppleEvents.
- **Registry entries** (``list_instances``): the detached server registers its
  own ``{pid, port, name}`` descriptor. Together the registry entry and the live
  window markers are the cross-process enumeration surface (see
  :func:`list_app_instances`).
"""

from __future__ import annotations

import glob
import importlib.util
import json
import logging
import os
import platform
import shlex
import shutil
import sys
import threading
import time
import urllib.parse
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

# Allowed second-launch behaviours (see run(second_open=...)).
_SECOND_OPEN_MODES = ("new-window", "focus-existing")

# Registry marker kinds coordinated through the fastware instance-registry dir.
_WINDOW_MARKER_KIND = "window"
_FOCUS_REQUEST_MARKER_KIND = "focus-request"

# The most recently created native window handle. Captured from
# webview.create_window so reset/update flows (and tests) can reach the live
# window via the host-side runtime bridge.
_active_window: object | None = None


def _wire_runtime_bridge(window: object, url: str) -> None:
    """Best-effort host-side update wiring for a native window.

    Captures the window and, where pywebview exposes a focus event, polls
    ``/__fastware/version`` on focus to reload on a changed build id. This is a
    no-op on pywebview builds without a focus event -- native windows load the
    same page + client.js, which is the primary (poll-free) update path.
    """
    global _active_window
    _active_window = window
    try:
        from wesktop import runtime_bridge

        version_url = url.rstrip("/") + "/__fastware/version"
        runtime_bridge.install_focus_poll(window, version_url)
    except Exception:
        # A bridge wiring failure must never take down the window.
        log.debug("runtime bridge focus poll not installed", exc_info=True)


def _app_url(host: str, port: int) -> str:
    """Compose the same-origin packaged app URL from *host* and *port*.

    The single source of truth for the URL an app window loads. In the join
    path the port comes from the port file; in the new-server path
    ``serve_background`` returns the same ``http://host:port`` form.
    """
    return f"http://{host}:{port}"


def _version_url(url: str) -> str:
    """The fastware version endpoint for a given app URL."""
    return url.rstrip("/") + "/__fastware/version"


def _port_from_url(url: str) -> int:
    """Extract the TCP port from an ``http://host:port`` URL."""
    parsed = urllib.parse.urlparse(url)
    if parsed.port is None:
        raise ValueError(f"URL has no port: {url!r}")
    return parsed.port


def _startup_handshake(url: str, *, timeout: float = 5.0) -> str | None:
    """Fetch ``/__fastware/version`` after window creation; loud stderr on failure.

    Returns the observed build id, or ``None`` if the server is unreachable or
    the payload is malformed within *timeout*. The window is NEVER torn down on
    failure -- the user's window stays -- but the failure is logged loudly to
    stderr so it is unmissable.
    """
    from wesktop import runtime_bridge

    version_url = _version_url(url)
    build_id = runtime_bridge.fetch_build_id(version_url, timeout=timeout)
    if build_id is None:
        print(
            "wesktop: STARTUP HANDSHAKE FAILED -- the app window opened but the "
            f"fastware server at {version_url} did not return a valid build id "
            f"within {timeout:g}s (unreachable or malformed). The window stays "
            "open, but live-reload and runtime-config injection may not work.",
            file=sys.stderr,
            flush=True,
        )
    return build_id


def _inject_runtime_config(
    window: object,
    build_id: str | None,
    port: int,
    app_name: str,
) -> bool:
    """Best-effort: set ``window.__wesktop = {buildId, port, appName}`` via JS.

    Runtime-config injection is best-effort by nature -- pywebview's
    ``evaluate_js`` timing depends on the page being loaded. Retries ONCE on
    failure. Returns ``True`` if a call succeeded, ``False`` otherwise.
    """
    payload = json.dumps(
        {"buildId": build_id, "port": port, "appName": app_name}
    )
    script = f"window.__wesktop = {payload};"
    for _attempt in range(2):
        try:
            window.evaluate_js(script)  # type: ignore[attr-defined]
            return True
        except Exception:
            log.debug("runtime-config injection attempt failed", exc_info=True)
    return False


def _wire_runtime_config_injection(
    window: object,
    build_id: str | None,
    port: int,
    app_name: str,
) -> None:
    """Wire runtime-config injection to the window's ``loaded`` event if present.

    Injecting after page load is the reliable moment; when pywebview exposes no
    ``loaded`` event the injection is attempted immediately (best-effort).
    """
    events = getattr(window, "events", None)
    loaded = getattr(events, "loaded", None) if events is not None else None
    iadd = getattr(loaded, "__iadd__", None)
    if iadd is not None:
        def _on_loaded(*_args: object) -> None:
            _inject_runtime_config(window, build_id, port, app_name)

        setattr(events, "loaded", iadd(_on_loaded))
        return
    _inject_runtime_config(window, build_id, port, app_name)


def _raise_window(window: object) -> None:
    """Best-effort raise-to-front of *window*.

    Calls ``restore()`` (un-minimize) then ``show()``. Raising a window ABOVE
    other applications' windows is window-manager dependent and not guaranteed
    on every platform -- this is the documented limitation of the platform-
    neutral, file-based focus signal.
    """
    for method_name in ("restore", "show"):
        method = getattr(window, method_name, None)
        if callable(method):
            try:
                method()
            except Exception:
                log.debug("focus raise via %s() failed", method_name, exc_info=True)


def _request_focus_existing(pid_path: Path, existing_pid: int) -> None:
    """Drop a focus-request marker for the window-owning process and return.

    Platform-neutral: the joining process writes a marker into the instance-
    registry dir and exits; the owning process's focus poll consumes it and
    raises its window.
    """
    from wesktop import server as _srv

    _srv.write_marker(
        pid_path,
        _FOCUS_REQUEST_MARKER_KIND,
        str(os.getpid()),
        fields={"requested_at": time.time()},
    )
    log.info(
        "Requested focus on existing instance (PID %d) and exiting.", existing_pid
    )


def _install_focus_request_poll(
    window: object,
    pid_path: Path,
    stop_event: threading.Event,
    *,
    interval: float = 1.0,
) -> threading.Thread:
    """Poll for focus-request markers while the window is open; raise on request.

    Runs a lightweight daemon thread that, every *interval* seconds until
    *stop_event* is set, consumes any focus-request markers (deleting them, even
    those owned by other/dead PIDs) and raises this window.
    """
    def _loop() -> None:
        from wesktop import server as _srv

        while not stop_event.wait(interval):
            try:
                markers = _srv.list_markers(
                    pid_path, _FOCUS_REQUEST_MARKER_KIND, prune_dead=False
                )
            except Exception:
                log.debug("focus-request poll read failed", exc_info=True)
                continue
            if not markers:
                continue
            for marker in markers:
                _srv.remove_marker(
                    pid_path,
                    _FOCUS_REQUEST_MARKER_KIND,
                    marker["marker_id"],
                    pid=marker.get("pid"),
                )
            _raise_window(window)

    thread = threading.Thread(target=_loop, daemon=True, name="wesktop-focus-poll")
    thread.start()
    return thread


@dataclass
class AppInstances:
    """A snapshot of an app's live server + windows from the registry."""

    servers: list = field(default_factory=list)
    windows: list = field(default_factory=list)


def list_app_instances(pid_path: Path) -> AppInstances:
    """Enumerate the app's live server instance(s) and open window markers.

    Reads the fastware instance registry for *pid_path*: ``servers`` are the
    registered server descriptors (``RegistryEntry``); ``windows`` are the live
    per-window marker payloads (dicts with ``pid`` and ``window_id``). Stale
    entries are pruned by the underlying registry reads.
    """
    from wesktop import server as _srv

    return AppInstances(
        servers=_srv.list_instances(pid_path),
        windows=_srv.list_markers(pid_path, _WINDOW_MARKER_KIND),
    )


def _require_webview_gui() -> object:
    """Import pywebview and verify a GUI backend, returning the ``webview`` module.

    Raises RuntimeError with an actionable message if pywebview is not installed
    or no GUI backend is available. Only called on paths that actually open a
    native window (the focus-existing early exit needs neither).
    """
    try:
        import webview
    except ImportError:
        raise RuntimeError(
            "pywebview is not installed. Install it: pip install pywebview"
        )

    # Single probe. On Linux this also makes system PyGObject importable in
    # isolated venvs (via ensure_gui_backend) before pywebview loads its GUI.
    if not _has_gui_backend():
        raise RuntimeError(
            "pywebview GUI backend not available. "
            "Install PyGObject: pip install PyGObject pycairo "
            "(requires gobject-introspection-devel on Fedora, "
            "libgirepository1.0-dev on Debian/Ubuntu)"
        )
    return webview


def _run_window(
    webview: object,
    window: object,
    url: str,
    pid_path: Path,
    port: int,
    app_name: str,
    icon: str | None,
) -> None:
    """Manage a single native window's full lifecycle around ``webview.start()``.

    Writes a per-window marker (cross-process refcount), runs the startup
    handshake, wires the runtime bridge + runtime-config injection + focus-
    request poll, blocks in ``webview.start()``, then removes the marker and
    stops the server only when zero live window markers remain.
    """
    from wesktop import server as _srv

    window_id = uuid.uuid4().hex
    _srv.write_marker(
        pid_path, _WINDOW_MARKER_KIND, window_id, fields={"window_id": window_id}
    )

    # Loud-on-failure startup handshake (never tears the window down).
    build_id = _startup_handshake(url)
    _wire_runtime_bridge(window, url)
    _wire_runtime_config_injection(window, build_id, port, app_name)

    stop_event = threading.Event()
    _install_focus_request_poll(window, pid_path, stop_event)

    try:
        webview.start(icon=icon)  # type: ignore[attr-defined]
    finally:
        stop_event.set()
        _srv.remove_marker(pid_path, _WINDOW_MARKER_KIND, window_id)
        # Stop the server only when no live window remains across ALL processes.
        if not _srv.list_markers(pid_path, _WINDOW_MARKER_KIND):
            try:
                _srv.stop(pid_path)
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                pass


def ensure_gui_backend() -> bool:
    """Report whether a native pywebview GUI backend is available, truthfully per platform.

    On Linux, this additionally makes the system PyGObject importable in
    isolated venvs: if gi is not importable, common system site-packages
    locations are searched and the first one found is added to sys.path.
    """
    if sys.platform == "win32":
        # pywebview drives the EdgeWebView2 runtime through pythonnet (clr);
        # Qt is the alternative backend. Without pywebview itself there is
        # nothing to back.
        if importlib.util.find_spec("webview") is None:
            return False
        return (
            importlib.util.find_spec("clr") is not None
            or importlib.util.find_spec("qtpy") is not None
        )

    if sys.platform == "darwin":
        # The Cocoa backend needs pyobjc (objc) -- no gi involved.
        return (
            importlib.util.find_spec("objc") is not None
            or importlib.util.find_spec("qtpy") is not None
        )

    # Linux: GTK backend via gi
    try:
        import gi  # noqa: F401

        return True
    except ImportError:
        pass

    # gi not in venv -- search system site-packages
    patterns = [
        "/usr/lib64/python3.*/site-packages",
        "/usr/lib/python3.*/site-packages",
        "/usr/lib/python3/dist-packages",  # Debian/Ubuntu
    ]

    for pattern in patterns:
        for path in sorted(glob.glob(pattern), reverse=True):
            gi_path = os.path.join(path, "gi")
            if os.path.isdir(gi_path) and path not in sys.path:
                sys.path.insert(0, path)
                try:
                    import gi  # noqa: F401

                    return True
                except ImportError:
                    sys.path.remove(path)

    return False


def _has_gui_backend() -> bool:
    """Probe whether pywebview can load a GUI backend.

    Non-Linux platforms delegate to ensure_gui_backend(), which reports
    availability truthfully per platform. On Linux, honours the
    PYWEBVIEW_GUI env var and probes GTK first (via ensure_gui_backend,
    which also makes system PyGObject importable in isolated venvs),
    then Qt.
    """
    if sys.platform != "linux":
        return ensure_gui_backend()

    # Honour the PYWEBVIEW_GUI env var -- if set, only probe that backend
    forced = os.environ.get("PYWEBVIEW_GUI", "").lower()
    if forced:
        if forced in ("gtk", "gtk3"):
            return ensure_gui_backend()
        if forced in ("qt", "qt5", "qt6"):
            try:
                import qtpy  # noqa: F401

                return True
            except ImportError:
                return False
        # Unknown backend -- let pywebview deal with it
        return True

    # Default Linux order: GTK first, then Qt
    if ensure_gui_backend():
        return True
    try:
        import qtpy  # noqa: F401

        return True
    except ImportError:
        return False


def _default_pid_path(name: str) -> Path:
    """Stable per-app PID file path under the platform runtime/state dir.

    A CWD-relative default would defeat single-instance detection when the
    app is launched from different directories.
    """
    slug = name.lower().replace(" ", "-")
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            raise OSError("LOCALAPPDATA environment variable not set")
        run_dir = Path(base) / "wesktop"
    elif system == "Darwin":
        run_dir = Path.home() / "Library" / "Application Support" / "wesktop"
    else:
        xdg = os.environ.get("XDG_RUNTIME_DIR")
        base_dir = Path(xdg) if xdg else Path.home() / ".local" / "state"
        run_dir = base_dir / "wesktop"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir / f"{slug}.pid"


def _launch_command_parts() -> list[str]:
    """Reconstruct a runnable command line (as argv parts) for this process.

    Handles the ``python -m pkg`` case, where sys.argv[0] is the package's
    __main__.py (a module file, not an executable): rebuilds
    ``sys.executable -m pkg`` instead.
    """
    argv0 = sys.argv[0]
    if Path(argv0).name == "__main__.py":
        spec = getattr(sys.modules.get("__main__"), "__spec__", None)
        if spec is not None and spec.name:
            module = spec.name
            if module.endswith(".__main__"):
                module = module[: -len(".__main__")]
        else:
            # No import spec available -- derive the package from the path
            module = Path(argv0).parent.name
        return [sys.executable, "-m", module, *sys.argv[1:]]
    if not Path(argv0).is_absolute():
        found = shutil.which(argv0)
        if found:
            argv0 = found
    return [argv0, *sys.argv[1:]]


def _auto_register_entry(title: str, icon: str | None) -> None:
    """Create a desktop entry for this app if one doesn't exist.

    On Linux/macOS a launcher script is created in ~/.local/bin and the entry
    points at it; this also self-heals: if an existing entry points to a
    missing launcher (e.g. the package was reinstalled to a different venv),
    the broken entry is removed and recreated with the current launcher path.
    On Windows the Start Menu shortcut points directly at the target -- a
    POSIX shell script cannot execute there.
    """
    try:
        from wesktop import entries

        system = platform.system()

        if entries.entry_exists(title):
            if system == "Windows" or entries.launcher_path(title).exists():
                return  # Entry exists and is valid
            # Launcher is gone (package uninstalled/moved). Clean up.
            entries.remove_entry(title)

        parts = _launch_command_parts()

        icon_path: str | None = None
        if icon and Path(icon).is_file():
            icon_path = str(Path(icon).resolve())

        if system == "Windows":
            # Direct-target shortcut, quoted per entries' Windows contract.
            command = entries.quote_windows_command(parts)
        else:
            # Launcher script so .desktop Exec= and venv binaries work reliably
            full_command = " ".join(shlex.quote(part) for part in parts)
            launcher = entries.create_launcher(title, full_command)
            command = shlex.quote(str(launcher))

        entries.create_entry(
            name=title,
            command=command,
            icon=icon_path,
            comment="",
        )
    except Exception:
        # Never fail the app launch over a desktop entry
        log.debug("Desktop entry auto-registration failed", exc_info=True)


def run(
    target: str | Callable,
    *,
    title: str = "wesktop",
    width: int = 1280,
    height: int = 800,
    icon: str | None = None,
    host: str | None = None,
    port: int | None = None,
    pid_path: Path | None = None,
    name: str = "WESKTOP",
    pre_serve: Callable[[], None] | None = None,
    reload: bool = False,
    js_api: object | None = None,
    single_instance: bool = True,
    second_open: str = "new-window",
) -> None:
    """Start server + open native desktop window. Blocks until window closes.

    The server runs as a detached subprocess (see serve_background), so
    ``pre_serve`` and ``reload`` cannot work here and are hard errors:
    pre_serve would run in this process while the server re-imports the
    target in another, and a file watcher cannot restart the detached
    server. Use :func:`wesktop.serve` for both.

    ``second_open`` selects what happens on a second launch while an instance is
    already running (single-instance join). It must be chosen explicitly from:

    - ``"new-window"`` (default): open an additional native window joined to the
      existing server. Windows are refcounted across processes via marker files;
      the server stops only when the last window (in any process) closes.
    - ``"focus-existing"``: do NOT open a new window. Drop a platform-neutral
      focus-request marker and exit; the process that owns the window raises it
      via a ~1s file-based poll. Raising above other apps is WM-dependent.
    """
    if second_open not in _SECOND_OPEN_MODES:
        raise ValueError(
            f"invalid second_open {second_open!r}; must be one of "
            f"{', '.join(_SECOND_OPEN_MODES)}."
        )
    if pre_serve is not None:
        raise ValueError(
            "run() does not support pre_serve: the desktop server runs in a "
            "detached subprocess that re-imports the target, so pre_serve "
            "would only run in this process and its in-memory effects would "
            "be invisible to the server. Do initialization at your app "
            "module's import time, or use wesktop.serve(..., pre_serve=...) "
            "instead."
        )
    if reload:
        raise ValueError(
            "run() does not support reload: the desktop server runs as a "
            "detached subprocess that a file watcher cannot restart. Use "
            "wesktop.serve(target, foreground=True, reload=True) during "
            "development instead."
        )

    if pid_path is None:
        # Stable per-app location so single-instance detection works
        # regardless of the directory the app is launched from.
        pid_path = _default_pid_path(name)

    resolved_host = host or "127.0.0.1"

    if single_instance:
        from wesktop.server import check_already_running, read_port_file

        existing_pid = check_already_running(pid_path)
        if existing_pid is not None:
            # Server already running -- read the port from the port file
            existing_port = read_port_file(pid_path)
            if existing_port is not None:
                if second_open == "focus-existing":
                    # No window, no GUI backend needed: signal and exit fast.
                    _request_focus_existing(pid_path, existing_pid)
                    return
                url = _app_url(resolved_host, existing_port)
                log.info("Joining existing instance (PID %d) at %s", existing_pid, url)
                webview = _require_webview_gui()
                window = webview.create_window(
                    title=title, url=url, width=width, height=height, js_api=js_api,
                )
                _run_window(webview, window, url, pid_path, existing_port, name, icon)
                return
            # No port file -- can't join. Fall through to start a new server.
            log.warning(
                "Existing instance (PID %d) has no port file. Starting new server.",
                existing_pid,
            )

    webview = _require_webview_gui()

    from wesktop.server import serve_background

    # Desktop mode: default to a random port when none specified
    effective_port = port if port is not None else 0

    url = serve_background(
        target,
        host=resolved_host,
        port=effective_port,
        pid_path=pid_path,
        name=name,
    )
    port_num = _port_from_url(url)

    # Auto-register desktop entry if not already present
    _auto_register_entry(title, icon)

    window = webview.create_window(
        title=title,
        url=url,
        width=width,
        height=height,
        js_api=js_api,
    )
    _run_window(webview, window, url, pid_path, port_num, name, icon)
