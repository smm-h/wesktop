"""Native desktop window via pywebview, backed by a Granian server in a daemon thread."""

from __future__ import annotations

from pathlib import Path


def run(
    target: str,
    *,
    title: str = "wesktop",
    width: int = 1280,
    height: int = 800,
    icon: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    pid_path: Path | None = None,
) -> None:
    """Start server + open native desktop window. Blocks until window closes."""
    from wesktop.server import start_server_in_background

    url = start_server_in_background(target, host, port, pid_path=pid_path)

    # Late import so headless mode (serve) has no pywebview dependency
    import webview

    window = webview.create_window(
        title=title,
        url=url,
        width=width,
        height=height,
    )
    if icon:
        # pywebview supports icon parameter on some platforms
        pass

    webview.start()
    # When webview.start() returns, the window was closed.
    # Daemon thread (server) auto-exits with main thread.
