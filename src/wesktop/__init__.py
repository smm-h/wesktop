"""wesktop — A Python framework for building web-based desktop applications."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path

from wesktop.entries import create_entry, remove_entry
from wesktop.asgi import (
    Router,
    Request,
    State,
    WebSocket,
    JSONResponse,
    TextResponse,
    HTMLResponse,
    BytesResponse,
    StreamResponse,
    FileResponse,
    HTTPError,
    Scope,
    Receive,
    Send,
    create_app,
    send_error,
    set_cookie,
    delete_cookie,
)
from wesktop.sse import Broadcaster, sse_route

__version__ = importlib.metadata.version("wesktop")

__all__ = [
    # asgi
    "Router",
    "Request",
    "State",
    "WebSocket",
    "JSONResponse",
    "TextResponse",
    "HTMLResponse",
    "BytesResponse",
    "StreamResponse",
    "FileResponse",
    "HTTPError",
    "Scope",
    "Receive",
    "Send",
    "create_app",
    "send_error",
    "set_cookie",
    "delete_cookie",
    # sse
    "Broadcaster",
    "sse_route",
    # entries
    "create_entry",
    "remove_entry",
    # top-level
    "run",
    "serve",
    # metadata
    "__version__",
]


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
    """Start server + native desktop window."""
    from wesktop.desktop import run as _run

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
    name: str = "wesktop",
) -> None:
    """Start server in blocking/headless mode."""
    from wesktop.server import start_server

    start_server(target, host, port, pid_path=pid_path, name=name)
