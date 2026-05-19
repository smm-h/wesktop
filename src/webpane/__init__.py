"""webpane — A Python framework for building web-based desktop applications."""

from __future__ import annotations

from pathlib import Path

from webpane.asgi import (
    Router,
    Request,
    JSONResponse,
    TextResponse,
    HTMLResponse,
    BytesResponse,
    StreamResponse,
    create_app,
    add_ws_route,
)
from webpane.sse import Broadcaster, sse_route


def run(
    target: str,
    *,
    title: str = "webpane",
    width: int = 1280,
    height: int = 800,
    icon: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    pid_path: Path | None = None,
) -> None:
    """Start server + native desktop window."""
    from webpane.desktop import run as _run

    _run(
        target,
        title=title,
        width=width,
        height=height,
        icon=icon,
        host=host,
        port=port,
        pid_path=pid_path,
    )


def serve(
    target: str,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    pid_path: Path | None = None,
    name: str = "webpane",
) -> None:
    """Start server in blocking/headless mode."""
    from webpane.server import start_server

    start_server(target, host, port, pid_path=pid_path, name=name)
