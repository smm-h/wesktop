"""Request tracing, CORS, and trusted-host middleware.

All middleware classes are pure ASGI — no framework dependency beyond
wesktop's own ``send_error`` helper.  This keeps them streaming-safe
(SSE, WebSocket) and avoids the response-buffering issues of
BaseHTTPMiddleware-style wrappers.

Classes:
    RequestIDMiddleware   — assigns/propagates X-Request-Id per request
    RequestTimingMiddleware — logs method, path, status, duration; ring buffer
    CORSMiddleware        — preflight OPTIONS + response header injection
    TrustedHostMiddleware — rejects requests from unlisted Host headers
"""

from __future__ import annotations

import time
import uuid
from collections import deque
from typing import Any, Callable

from wesktop.asgi import Scope, Receive, Send, send_error

try:
    import structlog
    _HAS_STRUCTLOG = True
except ImportError:
    _HAS_STRUCTLOG = False


# ---------------------------------------------------------------------------
# Request ID
# ---------------------------------------------------------------------------

class RequestIDMiddleware:
    """Assign or propagate a unique request ID per request.

    If the incoming request carries an ``X-Request-Id`` header, that value
    is reused.  Otherwise a new UUID4 is generated.  The ID is stored in
    ``scope["state"]["request_id"]`` and returned as an ``X-Request-Id``
    response header.

    When structlog is available, contextvars are cleared at the start of
    each request (preventing context leak from a previous request) and the
    request ID is bound so all log entries within the request include it.
    """

    def __init__(self, app: Callable) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract or generate request ID.
        headers = dict(scope.get("headers", []))
        request_id = headers.get(b"x-request-id", b"").decode() or str(uuid.uuid4())

        scope.setdefault("state", {})["request_id"] = request_id

        # Bind to structlog contextvars (clear first to prevent leaks).
        if _HAS_STRUCTLOG:
            structlog.contextvars.clear_contextvars()
            structlog.contextvars.bind_contextvars(request_id=request_id)

        async def send_with_request_id(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": response_headers}
            await send(message)

        await self.app(scope, receive, send_with_request_id)


# ---------------------------------------------------------------------------
# Request Timing
# ---------------------------------------------------------------------------

# Ring buffer entry: (timestamp, method, path, status_code, duration_ms)
RequestEntry = tuple[float, str, str, int, float]


class RequestTimingMiddleware:
    """Log every HTTP request with method, path, status, and duration.

    Wraps ``send`` to capture the status code from ``http.response.start``,
    then uses ``try/finally`` so timing fires even for long-lived SSE
    streams (when the client disconnects the ASGI handler returns).

    Args:
        app: The inner ASGI application.
        error_log: Optional ``ErrorLog`` instance.  On 5xx responses the
                   middleware calls ``error_log.append(...)`` to persist the
                   failure for dashboard visibility.
        exclude_paths: Iterable of path prefixes to exclude from the ring
                       buffer (e.g. ``["/events"]``).  Excluded requests
                       are still logged, just not stored.
        maxlen: Maximum number of entries in the ring buffer (default 10000).
    """

    def __init__(
        self,
        app: Callable,
        *,
        error_log: Any | None = None,
        exclude_paths: list[str] | None = None,
        maxlen: int = 10_000,
    ) -> None:
        self.app = app
        self.error_log = error_log
        self._exclude_paths: frozenset[str] = frozenset(exclude_paths or [])
        self.request_history: deque[RequestEntry] = deque(maxlen=maxlen)
        self.request_count: int = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        method = scope["method"]
        start = time.monotonic()
        status_code = 0

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.monotonic() - start) * 1000, 2)
            self.request_count += 1

            # Append to ring buffer unless path is excluded.
            if not any(path.startswith(p) for p in self._exclude_paths):
                self.request_history.append(
                    (time.time(), method, path, status_code, duration_ms)
                )

            # On 5xx, escalate to the error log if provided.
            if status_code >= 500 and self.error_log is not None:
                state = scope.get("state", {})
                request_id = state.get("request_id")
                self.error_log.append(
                    method=method,
                    path=path,
                    status_code=status_code,
                    detail=f"{method} {path} returned {status_code}",
                    request_id=request_id or "",
                )

            # Structured log entry.
            if _HAS_STRUCTLOG:
                _logger = structlog.get_logger(component="request")
                _logger.debug(
                    "request",
                    method=method,
                    path=path,
                    status=status_code,
                    duration_ms=duration_ms,
                )


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

_DEFAULT_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD")
_DEFAULT_HEADERS = ("accept", "authorization", "content-type", "x-request-id")


class CORSMiddleware:
    """Add CORS headers to responses and handle preflight OPTIONS requests.

    Args:
        app: The inner ASGI application.
        allow_origins: List of allowed origins (e.g. ``["http://localhost:5173"]``).
                       Use ``["*"]`` to allow any origin.
        allow_methods: HTTP methods to advertise.  Defaults to common methods.
        allow_headers: Request headers the client may send.  Defaults to
                       common headers.
        allow_credentials: Whether to set ``Access-Control-Allow-Credentials``.
    """

    def __init__(
        self,
        app: Callable,
        *,
        allow_origins: list[str],
        allow_methods: list[str] | None = None,
        allow_headers: list[str] | None = None,
        allow_credentials: bool = True,
    ) -> None:
        self.app = app
        self.allow_origins = allow_origins
        self.allow_methods = allow_methods or list(_DEFAULT_METHODS)
        self.allow_headers = allow_headers or list(_DEFAULT_HEADERS)
        self.allow_credentials = allow_credentials
        self._wildcard = "*" in allow_origins

    def _origin_allowed(self, origin: str) -> bool:
        if self._wildcard:
            return True
        return origin in self.allow_origins

    def _cors_headers(self, origin: str) -> list[tuple[bytes, bytes]]:
        """Build the list of CORS response headers for *origin*."""
        headers: list[tuple[bytes, bytes]] = [
            (b"access-control-allow-origin", origin.encode()),
            (b"access-control-allow-methods", ", ".join(self.allow_methods).encode()),
            (b"access-control-allow-headers", ", ".join(self.allow_headers).encode()),
        ]
        if self.allow_credentials:
            headers.append((b"access-control-allow-credentials", b"true"))
        return headers

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        raw_headers = dict(scope.get("headers", []))
        origin = raw_headers.get(b"origin", b"").decode()

        # No Origin header — not a CORS request, pass through.
        if not origin:
            await self.app(scope, receive, send)
            return

        if not self._origin_allowed(origin):
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        cors_headers = self._cors_headers(origin)

        # Preflight
        if method == "OPTIONS":
            response_headers = cors_headers[:]
            # Max age for preflight cache (1 hour).
            response_headers.append((b"access-control-max-age", b"3600"))
            await send({
                "type": "http.response.start",
                "status": 204,
                "headers": response_headers,
            })
            await send({"type": "http.response.body", "body": b""})
            return

        # Normal request — inject CORS headers into the response.
        async def send_with_cors(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.extend(cors_headers)
                message = {**message, "headers": response_headers}
            await send(message)

        await self.app(scope, receive, send_with_cors)


# ---------------------------------------------------------------------------
# Trusted Host
# ---------------------------------------------------------------------------

class TrustedHostMiddleware:
    """Reject requests whose Host header is not in the allow-list.

    Prevents DNS rebinding attacks for servers bound to localhost.

    Args:
        app: The inner ASGI application.
        allowed_hosts: List of hostnames (with optional port) to allow.
                       Use ``["*"]`` to disable the check.
    """

    def __init__(self, app: Callable, *, allowed_hosts: list[str]) -> None:
        self.app = app
        self.allowed_hosts = allowed_hosts
        self._wildcard = "*" in allowed_hosts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if self._wildcard:
            await self.app(scope, receive, send)
            return

        raw_headers = dict(scope.get("headers", []))
        host = raw_headers.get(b"host", b"").decode()

        if host not in self.allowed_hosts:
            await send_error(send, 400, "Invalid host header")
            return

        await self.app(scope, receive, send)
