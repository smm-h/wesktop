"""Native desktop window via pywebview, backed by a Granian server in a daemon thread."""

from __future__ import annotations

from pathlib import Path
from typing import Callable


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
    import webview

    window = webview.create_window(
        title=title,
        url=url,
        width=width,
        height=height,
        js_api=js_api,
    )

    webview.start(icon=icon)
    # When webview.start() returns, the window was closed.
    # Daemon thread (server) auto-exits with main thread.
