"""Native desktop window via pywebview, backed by a Granian server in a daemon thread."""

from __future__ import annotations

import glob
import logging
import os
import platform
import shutil
import stat
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


def _entry_exists(name: str) -> bool:
    """Check whether a desktop entry already exists for *name* on the current platform."""
    system = platform.system()
    if system == "Linux":
        return (Path.home() / ".local" / "share" / "applications" / f"{name}.desktop").exists()
    elif system == "Darwin":
        return (Path.home() / "Applications" / f"{name}.app").exists()
    elif system == "Windows":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            return (
                Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{name}.lnk"
            ).exists()
    return False


def _auto_register_entry(title: str, icon: str | None) -> None:
    """Create a desktop entry for this app if one doesn't exist.

    Self-heals: if an existing entry points to a missing launcher script
    (e.g. the package was reinstalled to a different venv), remove the
    broken entry so it can be recreated with the current launcher path.
    """
    try:
        # Self-heal: remove desktop entry if its launcher is broken
        if _entry_exists(title):
            launcher_name = title.lower().replace(" ", "-") + "-open"
            launcher = Path.home() / ".local" / "bin" / launcher_name
            if not launcher.exists():
                # Launcher is gone (package uninstalled/moved). Clean up.
                from wesktop.entries import remove_entry

                remove_entry(title)
            else:
                return  # Entry exists and is valid

        # Resolve the command that launched us (sys.argv[0]) to an absolute path
        command = sys.argv[0]
        if not Path(command).is_absolute():
            found = shutil.which(command)
            if found:
                command = found

        # Reconstruct the full launch command from sys.argv
        argv_rest = " ".join(sys.argv[1:])
        full_command = f"{command} {argv_rest}".strip()

        # Create a launcher script so .desktop Exec= and venv binaries work reliably
        launcher_name = title.lower().replace(" ", "-") + "-open"
        launcher = Path.home() / ".local" / "bin" / launcher_name
        launcher.parent.mkdir(parents=True, exist_ok=True)
        launcher.write_text(f"#!/bin/sh\nexec {full_command}\n")
        launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        icon_path: str | None = None
        if icon and Path(icon).is_file():
            icon_path = str(Path(icon).resolve())

        from wesktop.entries import create_entry

        create_entry(
            name=title,
            command=str(launcher),
            icon=icon_path,
            comment="",
        )
    except Exception:
        pass  # Never fail the app launch over a desktop entry


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
