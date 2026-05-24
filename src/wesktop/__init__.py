"""wesktop — A Python framework for building web-based desktop applications."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path
from typing import Callable

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
from wesktop.di import DependencyResolver
from wesktop.server import ServerStatus
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
    # di
    "DependencyResolver",
    # sse
    "Broadcaster",
    "sse_route",
    # entries
    "create_entry",
    "remove_entry",
    # server lifecycle
    "serve",
    "stop",
    "status",
    "ServerStatus",
    "run",
    # metadata
    "__version__",
]


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
        name=name,
        pre_serve=pre_serve,
    )


def serve(
    target: str | Callable,
    *,
    foreground: bool,
    host: str | None = None,
    port: int | None = None,
    pid_path: Path | None = None,
    name: str = "WESKTOP",
    pre_serve: Callable[[], None] | None = None,
) -> str | None:
    """Start server. Blocks if foreground=True, returns URL if foreground=False."""
    from wesktop.server import serve as _serve

    return _serve(
        target,
        foreground=foreground,
        host=host,
        port=port,
        pid_path=pid_path,
        name=name,
        pre_serve=pre_serve,
    )


def stop(pid_path: Path) -> None:
    """Stop a running server by PID file."""
    from wesktop.server import stop as _stop

    _stop(pid_path)


def status(pid_path: Path, health_url: str | None = None) -> ServerStatus:
    """Check server status by PID file and optional health URL."""
    from wesktop.server import status as _status

    return _status(pid_path, health_url=health_url)
