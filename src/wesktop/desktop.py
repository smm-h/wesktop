"""Native desktop window via pywebview, backed by a Granian ASGI server in a daemon thread, with automatic server lifecycle and window close handling."""

from __future__ import annotations

import glob
import logging
import os
import platform
import shlex
import shutil
import sys
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)


def ensure_gui_backend() -> bool:
    """Make pywebview's GUI backend importable in isolated venvs.

    If gi (PyGObject) is not importable, searches common system
    site-packages locations and adds the first one found to sys.path.
    Returns True if a backend is available, False otherwise.
    """
    try:
        import gi  # noqa: F401

        return True
    except ImportError:
        pass

    # On Windows, PyGObject is typically installed via pip or MSYS2
    # and already on the path. If gi isn't importable, there's nothing
    # to search for.
    if sys.platform == "win32":
        return False

    # gi not in venv -- search system site-packages
    patterns = [
        # Linux
        "/usr/lib64/python3.*/site-packages",
        "/usr/lib/python3.*/site-packages",
        "/usr/lib/python3/dist-packages",  # Debian/Ubuntu
        # macOS (Homebrew)
        "/opt/homebrew/lib/python3.*/site-packages",
        "/usr/local/lib/python3.*/site-packages",
        # macOS (Framework)
        "/Library/Frameworks/Python.framework/Versions/3.*/lib/python3.*/site-packages",
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
    """Probe whether pywebview can load a GUI backend (GTK or Qt).

    Returns True if at least one backend is loadable, False otherwise.
    On non-Linux platforms, always returns True (pywebview uses native APIs).
    """
    import sys

    if sys.platform != "linux":
        return True

    import os

    # Honour the PYWEBVIEW_GUI env var -- if set, only probe that backend
    forced = os.environ.get("PYWEBVIEW_GUI", "").lower()
    if forced:
        if forced in ("gtk", "gtk3"):
            try:
                import gi  # noqa: F401

                return True
            except ImportError:
                return False
        if forced in ("qt", "qt5", "qt6"):
            try:
                import qtpy  # noqa: F401

                return True
            except ImportError:
                return False
        # Unknown backend -- let pywebview deal with it
        return True

    # Default Linux order: GTK first, then Qt
    try:
        import gi  # noqa: F401

        return True
    except ImportError:
        pass
    try:
        import qtpy  # noqa: F401

        return True
    except ImportError:
        pass
    return False


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
    """Start server + open native desktop window. Blocks until window closes."""
    # Make system PyGObject visible in isolated venvs before importing webview
    ensure_gui_backend()

    try:
        import webview
    except ImportError:
        raise RuntimeError(
            "pywebview is not installed. Install it: pip install pywebview"
        )

    if not _has_gui_backend():
        raise RuntimeError(
            "pywebview GUI backend not available. "
            "Install PyGObject: pip install PyGObject pycairo "
            "(requires gobject-introspection-devel on Fedora, "
            "libgirepository1.0-dev on Debian/Ubuntu)"
        )

    if pid_path and single_instance:
        from wesktop.server import check_already_running, read_port_file

        existing_pid = check_already_running(pid_path, name)
        if existing_pid is not None:
            # Server already running -- read the port from the port file
            existing_port = read_port_file(pid_path)
            if existing_port is not None:
                resolved_host = host or "127.0.0.1"
                url = f"http://{resolved_host}:{existing_port}"
                log.info("Joining existing instance (PID %d) at %s", existing_pid, url)
                window = webview.create_window(
                    title=title, url=url, width=width, height=height, js_api=js_api,
                )
                webview.start(icon=icon)
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

    if pre_serve is not None:
        pre_serve()

    url = serve_background(
        target,
        host=effective_host,
        port=effective_port,
        pid_path=pid_path or Path(".wesktop.pid"),
        name=name,
    )

    # Auto-register desktop entry if not already present
    _auto_register_entry(title, icon)

    window = webview.create_window(
        title=title,
        url=url,
        width=width,
        height=height,
        js_api=js_api,
    )

    webview.start(icon=icon)
    # When webview.start() returns, the window was closed.
    # The server process keeps running independently.
