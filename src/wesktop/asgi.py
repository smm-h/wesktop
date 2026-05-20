"""
Minimal ASGI micro-framework with zero external dependencies (stdlib + msgspec).
Provides routing, static file serving, SPA fallback, middleware, and lifespan support.
"""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Any, AsyncGenerator, Callable
from urllib.parse import parse_qs

import msgspec


# ---------------------------------------------------------------------------
# Response types
# ---------------------------------------------------------------------------

class JSONResponse:
    """JSON response with optional status code."""

    def __init__(self, data: Any, status: int = 200):
        self.data = data
        self.status = status


class TextResponse:
    """Plain text or CSS response.

    ``headers`` (optional) is merged with the framework's default response
    headers; values must already be plain strings.
    """

    def __init__(
        self,
        text: str,
        content_type: str = "text/plain",
        status: int = 200,
        headers: dict[str, str] | None = None,
    ):
        self.text = text
        self.content_type = content_type
        self.status = status
        self.headers = headers or {}


class HTMLResponse:
    """HTML response."""

    def __init__(self, html: str, status: int = 200):
        self.html = html
        self.status = status


class BytesResponse:
    """Raw bytes response with an explicit content type."""

    def __init__(self, data: bytes, content_type: str = "application/octet-stream", status: int = 200):
        self.data = data
        self.content_type = content_type
        self.status = status


class StreamResponse:
    """Streaming response (for SSE)."""

    def __init__(
        self,
        generator: AsyncGenerator,
        content_type: str,
        headers: dict[str, str] | None = None,
    ):
        self.generator = generator
        self.content_type = content_type
        self.headers = headers or {}


# ---------------------------------------------------------------------------
# Request wrapper
# ---------------------------------------------------------------------------

class Request:
    """Wraps ASGI scope with parsed body and params."""

    __slots__ = ("scope", "path_params", "_body", "_json", "_json_decoded")

    def __init__(self, scope: dict, path_params: dict, body: bytes | None):
        self.scope = scope
        self.path_params = path_params
        self._body = body
        self._json = None
        self._json_decoded = False

    @property
    def json(self) -> dict | list | None:
        """Lazily decode the JSON body on first access, then cache."""
        if not self._json_decoded:
            if self._body:
                try:
                    self._json = msgspec.json.decode(self._body)
                except (msgspec.DecodeError, ValueError):
                    self._json = None
            self._json_decoded = True
        return self._json

    @property
    def body(self) -> bytes | None:
        """Raw request body bytes."""
        return self._body

    def query(self, name: str, default: Any = None, type_: type = str) -> Any:
        """Get a query parameter by name, with optional type conversion."""
        qs = parse_qs(self.scope.get("query_string", b"").decode())
        values = qs.get(name)
        if not values:
            return default
        try:
            return type_(values[0])
        except (ValueError, TypeError):
            return default

    def header(self, name: str, default: str | None = None) -> str | None:
        """Return a request header by name (case-insensitive).

        ASGI headers arrive as a list of ``(bytes, bytes)`` tuples. This
        helper decodes both to ``str`` and looks the name up
        case-insensitively, matching HTTP semantics.
        """
        target = name.lower().encode()
        for k, v in self.scope.get("headers", []):
            if k.lower() == target:
                return v.decode("latin-1")
        return default

    @property
    def body_size(self) -> int:
        """Length in bytes of the raw request body (0 if no body)."""
        return len(self._body) if self._body is not None else 0


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

class Router:
    """Simple path-based HTTP router using {param} placeholders."""

    def __init__(self) -> None:
        # List of (method, pattern_segments, handler)
        self._routes: list[tuple[str, list[str], Callable]] = []

    def get(self, path: str) -> Callable:
        """Decorator to register a GET handler."""
        def decorator(fn: Callable) -> Callable:
            self.add_route("GET", path, fn)
            return fn
        return decorator

    def post(self, path: str) -> Callable:
        """Decorator to register a POST handler."""
        def decorator(fn: Callable) -> Callable:
            self.add_route("POST", path, fn)
            return fn
        return decorator

    def delete(self, path: str) -> Callable:
        """Decorator to register a DELETE handler."""
        def decorator(fn: Callable) -> Callable:
            self.add_route("DELETE", path, fn)
            return fn
        return decorator

    def add_route(self, method: str, path: str, handler: Callable) -> None:
        """Programmatic route registration."""
        segments = path.strip("/").split("/")
        self._routes.append((method, segments, handler))

    def match(self, method: str, path: str) -> tuple[Callable, dict[str, str]] | None:
        """Return (handler, path_params) or None if no route matches."""
        segments = path.strip("/").split("/")
        for route_method, pattern, handler in self._routes:
            if route_method != method or len(pattern) != len(segments):
                continue
            params: dict[str, str] = {}
            matched = True
            for pat_seg, req_seg in zip(pattern, segments):
                if pat_seg.startswith("{") and pat_seg.endswith("}"):
                    params[pat_seg[1:-1]] = req_seg
                elif pat_seg != req_seg:
                    matched = False
                    break
            if matched:
                return handler, params
        return None


# ---------------------------------------------------------------------------
# ASGI send helpers
# ---------------------------------------------------------------------------

async def _send_response(
    send: Callable,
    status: int,
    body: bytes,
    content_type: str,
    extra_headers: dict[str, str] | None = None,
) -> None:
    """Send a complete HTTP response (headers + body)."""
    headers: list[list[bytes]] = [
        [b"content-type", content_type.encode()],
        [b"content-length", str(len(body)).encode()],
    ]
    if extra_headers:
        for k, v in extra_headers.items():
            headers.append([k.encode(), v.encode()])
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": headers,
    })
    await send({"type": "http.response.body", "body": body})


async def _send_stream(send: Callable, resp: StreamResponse) -> None:
    """Send a streaming HTTP response, iterating the async generator."""
    headers = [
        [b"content-type", resp.content_type.encode()],
    ]
    for key, value in resp.headers.items():
        headers.append([key.encode(), value.encode()])
    await send({"type": "http.response.start", "status": 200, "headers": headers})
    async for chunk in resp.generator:
        payload = chunk.encode() if isinstance(chunk, str) else chunk
        await send({"type": "http.response.body", "body": payload, "more_body": True})
    await send({"type": "http.response.body", "body": b"", "more_body": False})


async def _send_result(send: Callable, result: Any) -> None:
    """Dispatch a handler return value to the appropriate sender."""
    # Auto-wrap plain dicts/lists as JSON responses
    if isinstance(result, (dict, list)):
        result = JSONResponse(result)

    if isinstance(result, JSONResponse):
        await _send_response(send, result.status, msgspec.json.encode(result.data), "application/json")
    elif isinstance(result, TextResponse):
        await _send_response(
            send, result.status, result.text.encode(),
            result.content_type, extra_headers=result.headers,
        )
    elif isinstance(result, HTMLResponse):
        await _send_response(send, result.status, result.html.encode(), "text/html")
    elif isinstance(result, BytesResponse):
        await _send_response(send, result.status, result.data, result.content_type)
    elif isinstance(result, StreamResponse):
        await _send_stream(send, result)
    else:
        # Fallback: try JSON-encoding anything else
        await _send_response(send, 200, msgspec.json.encode(result), "application/json")


# ---------------------------------------------------------------------------
# Static file + SPA helpers
# ---------------------------------------------------------------------------

async def _serve_static(send: Callable, static_dir: Path, rel_path: str) -> bool:
    """Serve a static file. Returns True if served, False if not found."""
    file_path = (static_dir / rel_path).resolve()
    # Prevent path traversal
    if not str(file_path).startswith(str(static_dir.resolve())):
        return False
    if not file_path.is_file():
        return False
    mime, _ = mimetypes.guess_type(str(file_path))
    body = file_path.read_bytes()
    await _send_response(send, 200, body, mime or "application/octet-stream")
    return True


async def _serve_spa_fallback(send: Callable, spa_fallback: Path) -> None:
    """Serve the SPA fallback file (typically index.html)."""
    if spa_fallback.is_file():
        body = spa_fallback.read_bytes()
        await _send_response(send, 200, body, "text/html")
    else:
        await _send_response(send, 404, msgspec.json.encode({"error": "not found"}), "application/json")


# ---------------------------------------------------------------------------
# WebSocket route registry
# ---------------------------------------------------------------------------

# Maps exact paths (e.g. "/ws/echo") to raw ASGI WebSocket handlers
# with signature (scope, receive, send) -> None.
_ws_routes: dict[str, Callable] = {}


def add_ws_route(path: str, handler: Callable) -> None:
    """Register a WebSocket handler for an exact path."""
    _ws_routes[path] = handler


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(
    router: Router,
    middleware: list[type] | None = None,
    static_dir: Path | None = None,
    static_path: str = "/assets",
    spa_fallback: Path | None = None,
    lifespan: Callable | None = None,
    name: str | None = None,
) -> Callable:
    """Create an ASGI application callable."""

    log = logging.getLogger(name or "wesktop.asgi")

    async def app(scope: dict, receive: Callable, send: Callable) -> None:
        # -- Lifespan protocol --
        if scope["type"] == "lifespan":
            message = await receive()
            if message["type"] == "lifespan.startup":
                if lifespan is not None:
                    # Enter the context manager; it stays open until shutdown
                    ctx = lifespan(app)
                    await ctx.__aenter__()
                    await send({"type": "lifespan.startup.complete"})
                    await receive()  # blocks until lifespan.shutdown
                    await ctx.__aexit__(None, None, None)
                else:
                    await send({"type": "lifespan.startup.complete"})
                    await receive()
                await send({"type": "lifespan.shutdown.complete"})
            return

        # -- WebSocket routing --
        if scope["type"] == "websocket":
            path = scope.get("path", "")
            handler = _ws_routes.get(path)
            if handler:
                await handler(scope, receive, send)
            else:
                # Reject unknown WebSocket paths
                await receive()  # consume websocket.connect per ASGI spec
                await send({"type": "websocket.close", "code": 4004})
            return

        if scope["type"] != "http":
            return

        method = scope["method"]
        path = scope["path"]

        # -- Route matching --
        match = router.match(method, path)
        if match:
            handler, path_params = match
            try:
                # Read body for POST, skip for GET/DELETE
                body = None
                if method == "POST":
                    body = b""
                    while True:
                        msg = await receive()
                        body += msg.get("body", b"")
                        if not msg.get("more_body", False):
                            break

                request = Request(scope, path_params, body)
                result = await handler(request)
                await _send_result(send, result)
            except Exception as exc:
                log.exception("Handler error on %s %s", method, path)
                await _send_response(
                    send, 500,
                    msgspec.json.encode({"error": str(exc)}),
                    "application/json",
                )
            return

        # -- Static files --
        if static_dir and path.startswith(static_path + "/"):
            rel = path[len(static_path) + 1:]
            if await _serve_static(send, static_dir, rel):
                return

        # -- SPA fallback (GET only) --
        if spa_fallback and method == "GET":
            # Before returning index.html, check if the path maps to an
            # actual file under the static root (spa_fallback's parent dir).
            # This lets sub-directories be served without registering each
            # one as a separate static_path prefix.
            static_root = spa_fallback.parent
            candidate = path.lstrip("/")
            if candidate and await _serve_static(send, static_root, candidate):
                return
            await _serve_spa_fallback(send, spa_fallback)
            return

        # -- 404 --
        await _send_response(send, 404, msgspec.json.encode({"error": "not found"}), "application/json")

    # -- Apply middleware in reverse so the first in the list is outermost --
    wrapped = app
    for mw in reversed(middleware or []):
        wrapped = mw(wrapped)

    return wrapped
