"""Native desktop window via pywebview, backed by a Granian server in a daemon thread."""

from __future__ import annotations

import logging
import signal
import webbrowser
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)


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


def _browser_fallback(url: str) -> None:
    """Open the URL in the default browser and block until interrupted."""
    log.warning(
        "pywebview GUI backend not available (install PyGObject or qtpy). "
        "Opened in browser instead."
    )
    print(
        "pywebview GUI backend not available (install PyGObject or qtpy). "
        f"Opened in browser instead: {url}"
    )
    webbrowser.open(url)
    # Block the main thread until Ctrl+C so the daemon server thread stays alive.
    try:
        signal.pause()
    except KeyboardInterrupt:
        pass


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
) -> None:
    """Start server + open native desktop window. Blocks until window closes."""
    from wesktop.server import serve

    url = serve(
        target,
        foreground=False,
        host=host,
        port=port,
        pid_path=pid_path,
        name=name,
        pre_serve=pre_serve,
        reload=reload,
    )

    # Late import so headless mode (serve) has no pywebview dependency
    try:
        import webview
    except ImportError:
        _browser_fallback(url)
        return

    if not _has_gui_backend():
        _browser_fallback(url)
        return

    window = webview.create_window(
        title=title,
        url=url,
        width=width,
        height=height,
        js_api=js_api,
    )

    try:
        webview.start(icon=icon)
    except webview.WebViewException:
        # Runtime failure loading the GUI backend (e.g. system packages
        # installed but invisible from inside a venv). Fall back to browser.
        _browser_fallback(url)
        return
    # When webview.start() returns, the window was closed.
    # Daemon thread (server) auto-exits with main thread.
