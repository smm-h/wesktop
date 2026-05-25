"""Request tracing, CORS, trusted-host, and Vite dev proxy middleware.

All middleware classes are pure ASGI — no framework dependency beyond
wesktop's own ``send_error`` helper.  This keeps them streaming-safe
(SSE, WebSocket) and avoids the response-buffering issues of
BaseHTTPMiddleware-style wrappers.

Classes:
    RequestIDMiddleware   — assigns/propagates X-Request-Id per request
    RequestTimingMiddleware — logs method, path, status, duration; ring buffer
    CORSMiddleware        — preflight OPTIONS + response header injection
    TrustedHostMiddleware — rejects requests from unlisted Host headers
    ViteDevProxy          — proxies non-API requests to a Vite dev server
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


# ---------------------------------------------------------------------------
# Vite Dev Proxy
# ---------------------------------------------------------------------------

class ViteDevProxy:
    """ASGI middleware that proxies unmatched requests to a Vite dev server.

    Uses a backend-first routing strategy for HTTP: every request hits the
    backend first.  If the backend returns 404 (no route matched), the
    request is proxied to Vite instead.  This means backend routes like
    ``/health`` or ``/metrics`` work without being under an API prefix.

    WebSocket upgrades cannot be retried, so they still use prefix-based
    routing: paths matching *api_prefix* or ``/events`` go to the backend;
    everything else is proxied to Vite (for HMR).

    Args:
        app: The inner ASGI application.
        vite_port: Port the Vite dev server is listening on.
        api_prefix: Path prefix for backend WebSocket routes (default
            ``"/api"``).  Only used for WebSocket routing decisions.
    """

    def __init__(
        self,
        app: Callable,
        *,
        vite_port: int,
        api_prefix: str = "/api",
    ) -> None:
        self.app = app
        self.vite_port = vite_port
        self.api_prefix = api_prefix
        self._http_client: Any | None = None

    def _is_api_request(self, path: str) -> bool:
        """Return True if this path should go to the app, not be proxied."""
        return (
            path.startswith(self.api_prefix + "/")
            or path == self.api_prefix
            or path.startswith("/events")
        )

    def _get_client(self) -> Any:
        if self._http_client is None:
            import httpx as _httpx
            self._http_client = _httpx.AsyncClient(
                timeout=60, follow_redirects=False,
            )
        return self._http_client

    async def close(self) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            # Backend-first: buffer the response to check the status code.
            # If the backend returns 404, proxy to Vite instead.
            #
            # We also capture the request body via a wrapping receive so it
            # can be replayed to Vite when the backend doesn't match.
            response_parts: list[dict[str, Any]] = []
            captured_body = bytearray()

            async def capture_receive() -> dict[str, Any]:
                msg = await receive()
                if msg.get("type") == "http.request":
                    captured_body.extend(msg.get("body", b""))
                return msg

            async def buffer_send(message: dict[str, Any]) -> None:
                response_parts.append(message)

            await self.app(scope, capture_receive, buffer_send)

            status = None
            for part in response_parts:
                if part["type"] == "http.response.start":
                    status = part["status"]
                    break

            if status == 404:
                await self._proxy_http(scope, send, body=bytes(captured_body))
            else:
                for part in response_parts:
                    await send(part)
            return

        elif scope["type"] == "websocket":
            path = scope.get("path", "")
            if not self._is_api_request(path):
                await self._proxy_ws(scope, receive, send)
                return

        await self.app(scope, receive, send)

    async def _proxy_http(
        self, scope: Scope, send: Send, *, body: bytes = b"",
    ) -> None:
        """Forward an HTTP request to the Vite dev server.

        The *body* parameter contains the pre-captured request body (already
        consumed from ``receive`` by the backend during the try-first phase).
        """
        import httpx as _httpx

        path = scope.get("path", "/")
        qs = scope.get("query_string", b"")
        target = f"http://localhost:{self.vite_port}{path}"
        if qs:
            target += f"?{qs.decode('latin-1')}"

        method = scope.get("method", "GET")

        # Forward a subset of headers.
        fwd_headers: dict[str, str] = {}
        for raw_name, raw_val in scope.get("headers", []):
            name = raw_name.decode("latin-1").lower()
            if name in (
                "accept", "accept-encoding", "accept-language",
                "cookie", "if-none-match", "if-modified-since",
                "cache-control", "content-type",
            ):
                fwd_headers[name] = raw_val.decode("latin-1")

        client = self._get_client()
        try:
            resp = await client.request(
                method=method,
                url=target,
                headers=fwd_headers,
                content=body or None,
            )
        except _httpx.ConnectError:
            await send_error(send, 502, "Vite dev server not reachable")
            return

        # Build response headers, excluding hop-by-hop headers.
        excluded = {"transfer-encoding", "content-encoding", "content-length"}
        resp_headers = [
            (k.encode("latin-1"), v.encode("latin-1"))
            for k, v in resp.headers.items()
            if k.lower() not in excluded
        ]
        resp_headers.append(
            (b"content-length", str(len(resp.content)).encode("latin-1"))
        )

        await send({
            "type": "http.response.start",
            "status": resp.status_code,
            "headers": resp_headers,
        })
        await send({
            "type": "http.response.body",
            "body": resp.content,
        })

    async def _proxy_ws(
        self, scope: Scope, receive: Receive, send: Send,
    ) -> None:
        """Bidirectional WebSocket proxy to Vite (for HMR).

        Uses the ``websockets`` library if available. Falls back to
        closing the connection with an error code if not installed.
        """
        import asyncio

        path = scope.get("path", "/")
        qs = scope.get("query_string", b"")
        target_path = path
        if qs:
            target_path += f"?{qs.decode('latin-1')}"

        # Accept the client WebSocket.
        msg = await receive()
        if msg.get("type") != "websocket.connect":
            return

        # Extract subprotocol from client headers.
        subprotocol = None
        for raw_name, raw_val in scope.get("headers", []):
            if raw_name.decode("latin-1").lower() == "sec-websocket-protocol":
                subprotocol = raw_val.decode("latin-1")
                break

        accept_msg: dict[str, Any] = {"type": "websocket.accept"}
        if subprotocol:
            accept_msg["subprotocol"] = subprotocol
        await send(accept_msg)

        # Connect to Vite's WebSocket.
        try:
            from websockets.asyncio.client import connect

            ws_kwargs: dict[str, Any] = {
                "ping_interval": None, "close_timeout": 5,
            }
            if subprotocol:
                ws_kwargs["subprotocols"] = [subprotocol]

            ws_url = f"ws://localhost:{self.vite_port}{target_path}"
            async with connect(ws_url, **ws_kwargs) as vite_ws:

                async def client_to_vite() -> None:
                    while True:
                        inner_msg = await receive()
                        if inner_msg["type"] == "websocket.receive":
                            text = inner_msg.get("text")
                            if text is not None:
                                await vite_ws.send(text)
                            else:
                                await vite_ws.send(inner_msg.get("bytes", b""))
                        elif inner_msg["type"] == "websocket.disconnect":
                            break

                async def vite_to_client() -> None:
                    async for data in vite_ws:
                        if isinstance(data, str):
                            await send({"type": "websocket.send", "text": data})
                        else:
                            await send({"type": "websocket.send", "bytes": data})

                _done, pending = await asyncio.wait(
                    [
                        asyncio.ensure_future(client_to_vite()),
                        asyncio.ensure_future(vite_to_client()),
                    ],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
        except ImportError:
            pass
        except Exception:
            pass
        finally:
            try:
                await send({"type": "websocket.close", "code": 1000})
            except Exception:
                pass
