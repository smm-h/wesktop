"""
Minimal ASGI micro-framework with zero external dependencies (stdlib + msgspec).
Provides routing, static file serving, SPA fallback, middleware, and lifespan support.
"""

from __future__ import annotations

import asyncio
import http.cookies
import logging
import mimetypes
from pathlib import Path
from typing import Any, AsyncGenerator, Callable
from urllib.parse import parse_qs

import msgspec

# ---------------------------------------------------------------------------
# ASGI type aliases
# ---------------------------------------------------------------------------

Scope = dict[str, Any]
Receive = Any
Send = Any


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------

def set_cookie(
    name: str,
    value: str,
    *,
    httponly: bool = False,
    samesite: str = "lax",
    max_age: int | None = None,
    path: str = "/",
    secure: bool = False,
) -> str:
    """Build a Set-Cookie header string."""
    parts = [f"{name}={value}", f"Path={path}", f"SameSite={samesite}"]
    if httponly:
        parts.append("HttpOnly")
    if secure:
        parts.append("Secure")
    if max_age is not None:
        parts.append(f"Max-Age={max_age}")
    return "; ".join(parts)


def delete_cookie(name: str, *, path: str = "/") -> str:
    """Build a Set-Cookie header string that clears the cookie."""
    return f"{name}=; Path={path}; Max-Age=0"


# ---------------------------------------------------------------------------
# HTTPError exception
# ---------------------------------------------------------------------------

class HTTPError(Exception):
    """Raise from handlers to return a specific HTTP error status."""

    def __init__(self, status_code: int, detail: str = ""):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


# ---------------------------------------------------------------------------
# Response types
# ---------------------------------------------------------------------------

class JSONResponse:
    """JSON response with optional status code, headers, and cookies."""

    def __init__(
        self,
        data: Any,
        status: int = 200,
        headers: dict[str, str] | None = None,
        cookies: list[str] | None = None,
    ):
        self.data = data
        self.status = status
        self.headers = headers or {}
        self.cookies = cookies or []


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
        cookies: list[str] | None = None,
    ):
        self.text = text
        self.content_type = content_type
        self.status = status
        self.headers = headers or {}
        self.cookies = cookies or []


class HTMLResponse:
    """HTML response."""

    def __init__(
        self,
        html: str,
        status: int = 200,
        headers: dict[str, str] | None = None,
        cookies: list[str] | None = None,
    ):
        self.html = html
        self.status = status
        self.headers = headers or {}
        self.cookies = cookies or []


class BytesResponse:
    """Raw bytes response with an explicit content type."""

    def __init__(
        self,
        data: bytes,
        content_type: str = "application/octet-stream",
        status: int = 200,
        headers: dict[str, str] | None = None,
        cookies: list[str] | None = None,
    ):
        self.data = data
        self.content_type = content_type
        self.status = status
        self.headers = headers or {}
        self.cookies = cookies or []


class StreamResponse:
    """Streaming response (for SSE)."""

    def __init__(
        self,
        generator: AsyncGenerator,
        content_type: str,
        headers: dict[str, str] | None = None,
        status: int = 200,
        cookies: list[str] | None = None,
    ):
        self.generator = generator
        self.content_type = content_type
        self.headers = headers or {}
        self.status = status
        self.cookies = cookies or []


# ---------------------------------------------------------------------------
# State wrapper
# ---------------------------------------------------------------------------

class State:
    """Dict-backed state that supports both attribute and dict access.

    ``state.key``, ``state["key"]``, and ``state.get("key")`` all work.
    Attribute assignment (``state.key = val``) also works.
    """

    def __init__(self, data: dict[str, Any] | None = None):
        # Use object.__setattr__ to avoid triggering our custom __setattr__
        object.__setattr__(self, "_data", data if data is not None else {})

    def __getattr__(self, name: str) -> Any:
        data = object.__getattribute__(self, "_data")
        try:
            return data[name]
        except KeyError:
            raise AttributeError(f"State has no attribute {name!r}") from None

    def __setattr__(self, name: str, value: Any) -> None:
        object.__getattribute__(self, "_data")[name] = value

    def __getitem__(self, key: str) -> Any:
        return object.__getattribute__(self, "_data")[key]

    def __setitem__(self, key: str, value: Any) -> None:
        object.__getattribute__(self, "_data")[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return object.__getattribute__(self, "_data").get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in object.__getattribute__(self, "_data")


# ---------------------------------------------------------------------------
# Sentinel for missing query parameter defaults
# ---------------------------------------------------------------------------

_MISSING = object()


# ---------------------------------------------------------------------------
# Request wrapper
# ---------------------------------------------------------------------------

class Request:
    """Wraps ASGI scope with parsed body and params."""

    __slots__ = (
        "scope", "path_params", "_body", "_json", "_json_decoded",
        "_receive", "_disconnected", "_cookies", "_cookies_parsed",
        "_query_params",
    )

    def __init__(
        self,
        scope: dict,
        path_params: dict,
        body: bytes | None,
        receive: Callable | None = None,
    ):
        self.scope = scope
        self.path_params = path_params
        self._body = body
        self._json = None
        self._json_decoded = False
        self._receive = receive
        self._disconnected = False
        self._cookies = None
        self._cookies_parsed = False
        self._query_params = None

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

    def query(
        self,
        name: str,
        default: Any = _MISSING,
        *,
        type_: type = str,
        ge: int | float | None = None,
        le: int | float | None = None,
        min_length: int | None = None,
        max_length: int | None = None,
    ) -> Any:
        """Get a query parameter by name, with optional type conversion and constraints.

        The *default* is only used when the key is **absent** from the query
        string.  When no default is given and the key is absent, returns
        ``None``.

        Type coercion failure (key present but unconvertible) always raises
        ``HTTPError(422)`` -- the default is **not** used as a fallback for
        bad input.

        Constraints (checked after type coercion):
        - ``ge``: value must be >= this (numeric)
        - ``le``: value must be <= this (numeric)
        - ``min_length``: len(value) must be >= this (strings)
        - ``max_length``: len(value) must be <= this (strings)

        Raises HTTPError(422) on coercion failure or constraint violation.
        """
        qs = parse_qs(self.scope.get("query_string", b"").decode())
        values = qs.get(name)
        if not values:
            if default is _MISSING:
                return None
            return default
        raw = values[0]
        try:
            value = type_(raw)
        except (ValueError, TypeError):
            raise HTTPError(
                422,
                f"Query parameter '{name}': cannot convert '{raw}' to {type_.__name__}",
            )
        # Validate constraints
        if ge is not None and value < ge:
            raise HTTPError(422, f"Query parameter '{name}' must be >= {ge}")
        if le is not None and value > le:
            raise HTTPError(422, f"Query parameter '{name}' must be <= {le}")
        if min_length is not None and len(value) < min_length:
            raise HTTPError(422, f"Query parameter '{name}' must have length >= {min_length}")
        if max_length is not None and len(value) > max_length:
            raise HTTPError(422, f"Query parameter '{name}' must have length <= {max_length}")
        return value

    def query_list(self, name: str, type_: type = str) -> list:
        """Return all values for a multi-value query key with optional type coercion.

        Returns an empty list if the key is absent.
        """
        qs = parse_qs(self.scope.get("query_string", b"").decode())
        values = qs.get(name)
        if not values:
            return []
        return [type_(v) for v in values]

    @property
    def query_params(self) -> dict[str, str]:
        """Parsed query string as a dict (first value per key). Cached."""
        if self._query_params is None:
            qs = parse_qs(self.scope.get("query_string", b"").decode())
            self._query_params = {k: v[0] for k, v in qs.items()}
        return self._query_params

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

    @property
    def state(self) -> State:
        """Lifespan + per-request state, supporting both attribute and dict access."""
        return State(self.scope.get("state", {}))

    @property
    def method(self) -> str:
        """HTTP method (GET, POST, etc.)."""
        return self.scope["method"]

    @property
    def path(self) -> str:
        """Request path."""
        return self.scope.get("path", "")

    async def is_disconnected(self) -> bool:
        """Check whether the client has disconnected."""
        if self._disconnected:
            return True
        if self._receive is None:
            return False
        try:
            msg = await asyncio.wait_for(self._receive(), timeout=0.0)
            if msg.get("type") == "http.disconnect":
                self._disconnected = True
                return True
        except (asyncio.TimeoutError, Exception):
            pass
        return False

    @property
    def cookies(self) -> dict[str, str]:
        """Parse Cookie header and return a dict of cookie name-value pairs."""
        if not self._cookies_parsed:
            cookie_header = self.header("cookie", "")
            result: dict[str, str] = {}
            if cookie_header:
                sc = http.cookies.SimpleCookie()
                sc.load(cookie_header)
                for key, morsel in sc.items():
                    result[key] = morsel.value
            self._cookies = result
            self._cookies_parsed = True
        return self._cookies  # type: ignore[return-value]

    def cookie(self, name: str, default: str | None = None) -> str | None:
        """Get a single cookie value by name."""
        return self.cookies.get(name, default)


# ---------------------------------------------------------------------------
# Path parameter type converters
# ---------------------------------------------------------------------------

_TYPE_CONVERTERS: dict[str, type] = {
    "str": str,
    "int": int,
}


def _parse_segment(seg: str) -> tuple[str | None, str | None, type | None]:
    """Parse a route pattern segment into (literal, param_name, converter).

    Returns one of:
    - (literal_str, None, None) for plain segments like "api"
    - (None, param_name, converter) for parameterized segments like {id:int}
    - (None, param_name, None) for :path segments (greedy)
    """
    if not (seg.startswith("{") and seg.endswith("}")):
        return (seg, None, None)
    inner = seg[1:-1]
    if ":" in inner:
        name, type_name = inner.split(":", 1)
        if type_name == "path":
            # Greedy path segment -- converter is None, caller checks name
            return (None, name, None)
        converter = _TYPE_CONVERTERS.get(type_name)
        if converter is None:
            raise ValueError(f"Unknown path parameter type: {type_name!r}")
        return (None, name, converter)
    # Plain {param} -- defaults to str
    return (None, inner, str)


# Parsed segment tuple: (literal | None, param_name | None, converter | None)
ParsedSegment = tuple[str | None, str | None, type | None]


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

class Router:
    """Simple path-based HTTP router using {param} placeholders and type coercion.

    Supports {param}, {param:str}, {param:int}, and {param:path} syntax.
    """

    def __init__(self) -> None:
        # (method, parsed_segments, handler, dependencies)
        self._routes: list[tuple[str, list[ParsedSegment], Callable, list]] = []

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

    def put(self, path: str) -> Callable:
        """Decorator to register a PUT handler."""
        def decorator(fn: Callable) -> Callable:
            self.add_route("PUT", path, fn)
            return fn
        return decorator

    def patch(self, path: str) -> Callable:
        """Decorator to register a PATCH handler."""
        def decorator(fn: Callable) -> Callable:
            self.add_route("PATCH", path, fn)
            return fn
        return decorator

    def add_route(self, method: str, path: str, handler: Callable) -> None:
        """Programmatic route registration."""
        raw_segments = path.strip("/").split("/")
        parsed = [_parse_segment(s) for s in raw_segments]
        self._routes.append((method, parsed, handler, []))

    def include_router(
        self,
        other: Router,
        prefix: str | None = None,
        dependencies: list[Callable] | None = None,
    ) -> None:
        """Copy all routes from *other* into this router.

        If *prefix* is given (e.g. ``"/api/v1"``), its segments are
        prepended to every copied route's pattern.

        If *dependencies* is given, the list is stored alongside each
        copied route (merged with any deps the route already carries).
        DI resolution is not wired yet (Phase 3 scaffolding).
        """
        prefix_segs: list[ParsedSegment] = []
        if prefix:
            prefix_segs = [_parse_segment(s) for s in prefix.strip("/").split("/")]

        extra_deps = dependencies or []

        for method, pattern, handler, existing_deps in other._routes:
            merged_pattern = prefix_segs + pattern
            merged_deps = extra_deps + existing_deps
            self._routes.append((method, merged_pattern, handler, merged_deps))

    def match(self, method: str, path: str) -> tuple[Callable, dict[str, Any]] | None:
        """Return (handler, path_params) or None if no route matches.

        Path parameter values are coerced to their declared types (e.g.,
        {id:int} produces an int).  If coercion fails the route does not
        match, allowing fall-through to 404.
        """
        segments = path.strip("/").split("/")
        for route_method, pattern, handler, _deps in self._routes:
            if route_method != method:
                continue

            # Check for :path segments -- they change matching semantics
            path_seg_idx = None
            for i, (lit, name, conv) in enumerate(pattern):
                if name is not None and lit is None and conv is None:
                    path_seg_idx = i
                    break

            if path_seg_idx is not None:
                # Greedy :path matching
                result = self._match_with_path_param(
                    pattern, segments, path_seg_idx
                )
                if result is not None:
                    return handler, result
                continue

            # Normal segment-count matching
            if len(pattern) != len(segments):
                continue

            params: dict[str, Any] = {}
            matched = True
            for (lit, name, conv), req_seg in zip(pattern, segments):
                if lit is not None:
                    # Literal segment
                    if lit != req_seg:
                        matched = False
                        break
                else:
                    # Parameterized segment -- attempt type coercion
                    try:
                        params[name] = conv(req_seg)
                    except (ValueError, TypeError):
                        matched = False
                        break
            if matched:
                return handler, params
        return None

    @staticmethod
    def _match_with_path_param(
        pattern: list[ParsedSegment],
        segments: list[str],
        path_idx: int,
    ) -> dict[str, Any] | None:
        """Match a route pattern containing a :path greedy parameter.

        Literal/typed segments before the :path param must match exactly.
        Literal/typed segments after the :path param are matched from the
        end of the path.  Everything in between is consumed by the :path
        parameter (joined with "/").
        """
        prefix = pattern[:path_idx]
        suffix = pattern[path_idx + 1:]
        _, path_name, _ = pattern[path_idx]

        # Need enough segments for prefix + suffix + at least 1 for :path
        if len(segments) < len(prefix) + len(suffix) + 1:
            return None

        params: dict[str, Any] = {}

        # Match prefix (literal and typed segments before :path)
        for (lit, name, conv), req_seg in zip(prefix, segments):
            if lit is not None:
                if lit != req_seg:
                    return None
            else:
                try:
                    params[name] = conv(req_seg)
                except (ValueError, TypeError):
                    return None

        # Match suffix from the end
        suffix_start = len(segments) - len(suffix)
        for i, (lit, name, conv) in enumerate(suffix):
            req_seg = segments[suffix_start + i]
            if lit is not None:
                if lit != req_seg:
                    return None
            else:
                try:
                    params[name] = conv(req_seg)
                except (ValueError, TypeError):
                    return None

        # Everything between prefix and suffix is the :path value
        path_segments = segments[len(prefix):suffix_start]
        params[path_name] = "/".join(path_segments)

        return params


# ---------------------------------------------------------------------------
# ASGI send helpers
# ---------------------------------------------------------------------------

async def _send_response(
    send: Callable,
    status: int,
    body: bytes,
    content_type: str,
    extra_headers: dict[str, str] | None = None,
    cookies: list[str] | None = None,
) -> None:
    """Send a complete HTTP response (headers + body)."""
    headers: list[list[bytes]] = [
        [b"content-type", content_type.encode()],
        [b"content-length", str(len(body)).encode()],
    ]
    if extra_headers:
        for k, v in extra_headers.items():
            headers.append([k.encode(), v.encode()])
    if cookies:
        for cookie in cookies:
            headers.append([b"set-cookie", cookie.encode()])
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
    for cookie in resp.cookies:
        headers.append([b"set-cookie", cookie.encode()])
    await send({"type": "http.response.start", "status": resp.status, "headers": headers})
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
        await _send_response(
            send, result.status, msgspec.json.encode(result.data),
            "application/json", extra_headers=result.headers, cookies=result.cookies,
        )
    elif isinstance(result, TextResponse):
        await _send_response(
            send, result.status, result.text.encode(),
            result.content_type, extra_headers=result.headers, cookies=result.cookies,
        )
    elif isinstance(result, HTMLResponse):
        await _send_response(
            send, result.status, result.html.encode(),
            "text/html", extra_headers=result.headers, cookies=result.cookies,
        )
    elif isinstance(result, BytesResponse):
        await _send_response(
            send, result.status, result.data,
            result.content_type, extra_headers=result.headers, cookies=result.cookies,
        )
    elif isinstance(result, StreamResponse):
        await _send_stream(send, result)
    else:
        # Fallback: try JSON-encoding anything else
        await _send_response(send, 200, msgspec.json.encode(result), "application/json")


async def send_error(send: Callable, status: int, detail: str) -> None:
    """Send a complete JSON error response via raw ASGI send calls.

    Intended for use by middleware that needs to short-circuit with an error
    without constructing response objects.
    """
    await _send_response(
        send, status,
        msgspec.json.encode({"detail": detail}),
        "application/json",
    )


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
        await _send_response(send, 404, msgspec.json.encode({"detail": "Not found"}), "application/json")


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
    middleware: list[Callable] | None = None,
    static_dir: Path | None = None,
    static_path: str = "/assets",
    spa_fallback: Path | None = None,
    lifespan: Callable | None = None,
    name: str | None = None,
    exception_handlers: dict[type, Callable] | None = None,
) -> Callable:
    """Create an ASGI application callable."""

    log = logging.getLogger(name or "wesktop.asgi")

    # Pre-sort exception handlers by MRO depth (most specific first) so
    # that a handler for a subclass is checked before a handler for its
    # parent.  Ties are broken by insertion order.
    _exc_handlers: list[tuple[type, Callable]] = []
    if exception_handlers:
        _exc_handlers = sorted(
            exception_handlers.items(),
            key=lambda pair: len(pair[0].__mro__),
            reverse=True,
        )
    _lifespan_state: dict[str, Any] = {}

    async def app(scope: dict, receive: Callable, send: Callable) -> None:
        nonlocal _lifespan_state

        # -- Lifespan protocol --
        if scope["type"] == "lifespan":
            message = await receive()
            if message["type"] == "lifespan.startup":
                if lifespan is not None:
                    # Enter the context manager; it stays open until shutdown
                    ctx = lifespan(app)
                    yielded = await ctx.__aenter__()
                    if isinstance(yielded, dict):
                        _lifespan_state = yielded
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

        # Merge lifespan state into scope for every request
        if "state" not in scope:
            scope["state"] = {}
        scope["state"].update(_lifespan_state)

        method = scope["method"]
        path = scope["path"]

        # -- Route matching --
        match = router.match(method, path)
        if match:
            handler, path_params = match
            try:
                # Read body for all methods (GET with empty body costs nothing)
                body = b""
                while True:
                    msg = await receive()
                    body += msg.get("body", b"")
                    if not msg.get("more_body", False):
                        break
                body = body or None

                request = Request(scope, path_params, body, receive=receive)
                result = await handler(request)
                await _send_result(send, result)
            except HTTPError as exc:
                await _send_response(
                    send, exc.status_code,
                    msgspec.json.encode({"detail": exc.detail}),
                    "application/json",
                )
            except Exception as exc:
                # Check registered exception handlers (most specific first)
                handled = False
                for exc_type, exc_handler in _exc_handlers:
                    if isinstance(exc, exc_type):
                        try:
                            result = await exc_handler(request, exc)
                            await _send_result(send, result)
                            handled = True
                        except Exception:
                            log.exception(
                                "Exception handler error on %s %s",
                                method, path,
                            )
                        break
                if not handled:
                    log.exception("Handler error on %s %s", method, path)
                    await _send_response(
                        send, 500,
                        msgspec.json.encode({"detail": "Internal server error"}),
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
        await _send_response(send, 404, msgspec.json.encode({"detail": "Not found"}), "application/json")

    # -- Apply middleware in reverse so the first in the list is outermost --
    wrapped = app
    for mw in reversed(middleware or []):
        wrapped = mw(wrapped)

    return wrapped
