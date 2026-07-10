"""Native desktop window via pywebview, backed by a Granian ASGI server in a daemon thread, with automatic server lifecycle and window close handling."""

from __future__ import annotations

import glob
import importlib.util
import logging
import os
import platform
import shlex
import shutil
import sys
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

# Reference count of open windows per server PID path.  Keyed by the
# string representation of the PID-file Path so different Path objects
# pointing at the same file compare equal.
_window_counts: dict[str, int] = {}


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
) -> None:
    """Start server + open native desktop window. Blocks until window closes.

    The server runs as a detached subprocess (see serve_background), so
    ``pre_serve`` and ``reload`` cannot work here and are hard errors:
    pre_serve would run in this process while the server re-imports the
    target in another, and a file watcher cannot restart the detached
    server. Use :func:`wesktop.serve` for both.
    """
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

    if pid_path is None:
        # Stable per-app location so single-instance detection works
        # regardless of the directory the app is launched from.
        pid_path = _default_pid_path(name)

    if single_instance:
        from wesktop.server import check_already_running, read_port_file

        existing_pid = check_already_running(pid_path)
        if existing_pid is not None:
            # Server already running -- read the port from the port file
            existing_port = read_port_file(pid_path)
            if existing_port is not None:
                resolved_host = host or "127.0.0.1"
                url = f"http://{resolved_host}:{existing_port}"
                log.info("Joining existing instance (PID %d) at %s", existing_pid, url)
                webview.create_window(
                    title=title, url=url, width=width, height=height, js_api=js_api,
                )
                key = str(pid_path)
                _window_counts[key] = _window_counts.get(key, 0) + 1
                webview.start(icon=icon)
                # Window closed -- decrement and stop server if last window
                _window_counts[key] -= 1
                if _window_counts[key] <= 0:
                    _window_counts.pop(key, None)
                    try:
                        from wesktop.server import stop
                        stop(pid_path)
                    except (FileNotFoundError, ProcessLookupError, PermissionError):
                        pass
                return
            # No port file -- can't join. Fall through to start a new server.
            log.warning(
                "Existing instance (PID %d) has no port file. Starting new server.",
                existing_pid,
            )

    from wesktop.server import serve_background

    # Desktop mode: default to a random port when none specified
    effective_port = port if port is not None else 0
    effective_host = host or "127.0.0.1"

    url = serve_background(
        target,
        host=effective_host,
        port=effective_port,
        pid_path=pid_path,
        name=name,
    )
    key = str(pid_path)
    _window_counts[key] = _window_counts.get(key, 0) + 1

    # Auto-register desktop entry if not already present
    _auto_register_entry(title, icon)

    webview.create_window(
        title=title,
        url=url,
        width=width,
        height=height,
        js_api=js_api,
    )

    webview.start(icon=icon)
    # When webview.start() returns, the window was closed.
    # Stop the server if this was the last window.
    _window_counts[key] -= 1
    if _window_counts[key] <= 0:
        _window_counts.pop(key, None)
        try:
            from wesktop.server import stop
            stop(pid_path)
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            pass
