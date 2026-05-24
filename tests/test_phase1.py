"""Tests for Phase 1 Batch 1 of the codehome/CT migration plan.

Covers: body reading for all methods (1.1), HTTPError and error format (1.5),
PUT/PATCH decorators (1.9), lifespan state / request.state / method / path /
is_disconnected (1.11), StreamResponse status code (1.12), ASGI helpers and
type aliases (1.13), response headers and cookies (1.14), cookie extraction
on Request (1.15), and middleware constructor API (1.19).
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from functools import partial

import pytest
from httpx import ASGITransport, AsyncClient

from wesktop.asgi import (
    HTTPError,
    JSONResponse,
    Router,
    State,
    StreamResponse,
    TextResponse,
    create_app,
    delete_cookie,
    send_error,
    set_cookie,
)


async def _run_lifespan_startup(app):
    """Manually trigger ASGI lifespan startup on an app."""
    startup_done = asyncio.Event()
    shutdown_trigger = asyncio.Event()

    async def receive():
        if not startup_done.is_set():
            return {"type": "lifespan.startup"}
        # Block until shutdown is requested
        await shutdown_trigger.wait()
        return {"type": "lifespan.shutdown"}

    async def send(msg):
        if msg["type"] == "lifespan.startup.complete":
            startup_done.set()

    # Run the lifespan in a background task
    task = asyncio.create_task(app({"type": "lifespan"}, receive, send))
    await startup_done.wait()
    return task, shutdown_trigger


async def _run_lifespan_shutdown(task, shutdown_trigger):
    """Trigger shutdown and wait for the lifespan task to complete."""
    shutdown_trigger.set()
    await task


# ---------------------------------------------------------------------------
# 1.1 Body reading for all methods
# ---------------------------------------------------------------------------


class TestBodyReadingAllMethods:
    @pytest.mark.anyio
    async def test_delete_with_json_body(self, client_for):
        """DELETE with a JSON body can be read by the handler."""
        router = Router()

        @router.delete("/api/items/{id}")
        async def delete_item(req):
            return JSONResponse({"deleted": req.path_params["id"], "body": req.json})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.request("DELETE", "/api/items/42", json={"reason": "obsolete"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted"] == "42"
        assert data["body"] == {"reason": "obsolete"}

    @pytest.mark.anyio
    async def test_get_with_no_body(self, client_for):
        """GET with no body still works (body is None)."""
        router = Router()

        @router.get("/api/check")
        async def check(req):
            return JSONResponse({"body_is_none": req.json is None})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/check")
        assert resp.status_code == 200
        assert resp.json()["body_is_none"] is True


# ---------------------------------------------------------------------------
# 1.5 HTTPError exception and error format
# ---------------------------------------------------------------------------


class TestHTTPErrorAndErrorFormat:
    @pytest.mark.anyio
    async def test_httperror_returns_correct_status_and_detail(self, client_for):
        """HTTPError(404, "not found") -> 404 with {"detail": "not found"}."""
        router = Router()

        @router.get("/api/missing")
        async def missing(req):
            raise HTTPError(404, "not found")

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/missing")
        assert resp.status_code == 404
        assert resp.json() == {"detail": "not found"}

    @pytest.mark.anyio
    async def test_unhandled_exception_returns_500_internal_server_error(self, client_for):
        """Unhandled exception -> 500 with {"detail": "Internal server error"}."""
        router = Router()

        @router.get("/api/boom")
        async def boom(req):
            raise RuntimeError("unexpected failure")

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/boom")
        assert resp.status_code == 500
        assert resp.json() == {"detail": "Internal server error"}

    @pytest.mark.anyio
    async def test_404_fallback_uses_detail_format(self, client_for):
        """Unmatched route returns {"detail": "Not found"}."""
        router = Router()
        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/nonexistent")
        assert resp.status_code == 404
        assert resp.json() == {"detail": "Not found"}

    @pytest.mark.anyio
    async def test_httperror_with_custom_status(self, client_for):
        """HTTPError with 422 status code."""
        router = Router()

        @router.post("/api/validate")
        async def validate(req):
            raise HTTPError(422, "invalid input")

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.post("/api/validate")
        assert resp.status_code == 422
        assert resp.json() == {"detail": "invalid input"}


# ---------------------------------------------------------------------------
# 1.9 PUT and PATCH method decorators
# ---------------------------------------------------------------------------


class TestPutPatchDecorators:
    @pytest.mark.anyio
    async def test_put_route_matches_and_executes(self, client_for):
        router = Router()

        @router.put("/api/items/{id}")
        async def update_item(req):
            return JSONResponse({"updated": req.path_params["id"], "body": req.json})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.put("/api/items/7", json={"name": "new"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["updated"] == "7"
        assert data["body"] == {"name": "new"}

    @pytest.mark.anyio
    async def test_patch_route_matches_and_executes(self, client_for):
        router = Router()

        @router.patch("/api/items/{id}")
        async def patch_item(req):
            return JSONResponse({"patched": req.path_params["id"], "body": req.json})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.patch("/api/items/3", json={"name": "patched"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["patched"] == "3"
        assert data["body"] == {"name": "patched"}

    def test_put_decorator_registers_route(self):
        router = Router()

        @router.put("/path")
        async def handler(req):
            return {"ok": True}

        match = router.match("PUT", "/path")
        assert match is not None
        assert match[0] is handler

    def test_patch_decorator_registers_route(self):
        router = Router()

        @router.patch("/path")
        async def handler(req):
            return {"ok": True}

        match = router.match("PATCH", "/path")
        assert match is not None
        assert match[0] is handler


# ---------------------------------------------------------------------------
# 1.11 Lifespan state, request.state, request.method, request.path,
#      request.is_disconnected
# ---------------------------------------------------------------------------


class TestState:
    """Unit tests for the State wrapper class."""

    def test_dict_access(self):
        s = State({"db": "test"})
        assert s["db"] == "test"

    def test_attribute_access(self):
        s = State({"db": "test"})
        assert s.db == "test"

    def test_get_method(self):
        s = State({"db": "test"})
        assert s.get("db") == "test"
        assert s.get("missing") is None
        assert s.get("missing", "default") == "default"

    def test_attribute_assignment(self):
        s = State()
        s.custom = "val"
        assert s["custom"] == "val"
        assert s.custom == "val"

    def test_dict_assignment(self):
        s = State()
        s["key"] = "value"
        assert s.key == "value"

    def test_contains(self):
        s = State({"db": "test"})
        assert "db" in s
        assert "missing" not in s

    def test_missing_attribute_raises(self):
        s = State()
        with pytest.raises(AttributeError, match="no attribute"):
            _ = s.nonexistent

    def test_missing_key_raises(self):
        s = State()
        with pytest.raises(KeyError):
            _ = s["nonexistent"]


class TestLifespanState:
    @pytest.mark.anyio
    async def test_lifespan_state_propagates_to_request(self, client_for):
        """Lifespan yields {"db": "test"}, handler reads via dict and attribute."""

        @asynccontextmanager
        async def lifespan(app):
            yield {"db": "test"}

        router = Router()

        @router.get("/api/state")
        async def read_state(req):
            return JSONResponse({
                "dict_access": req.state["db"],
                "attr_access": req.state.db,
                "get_access": req.state.get("db"),
            })

        app = create_app(router, lifespan=lifespan)

        # Manually trigger lifespan since httpx ASGITransport doesn't
        task, shutdown = await _run_lifespan_startup(app)
        try:
            async with client_for(app) as client:
                resp = await client.get("/api/state")
            assert resp.status_code == 200
            data = resp.json()
            assert data["dict_access"] == "test"
            assert data["attr_access"] == "test"
            assert data["get_access"] == "test"
        finally:
            await _run_lifespan_shutdown(task, shutdown)

    @pytest.mark.anyio
    async def test_state_attribute_assignment(self, client_for):
        """req.state.custom = 'val' works."""
        router = Router()

        @router.get("/api/assign")
        async def assign_state(req):
            req.state.custom = "val"
            return JSONResponse({"custom": req.state.custom})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/assign")
        assert resp.status_code == 200
        assert resp.json()["custom"] == "val"

    @pytest.mark.anyio
    async def test_no_lifespan_state_is_empty(self, client_for):
        """Without lifespan, req.state is an empty State."""
        router = Router()

        @router.get("/api/empty-state")
        async def empty_state(req):
            return JSONResponse({"has_db": "db" in req.state})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/empty-state")
        assert resp.status_code == 200
        assert resp.json()["has_db"] is False


class TestRequestMethodAndPath:
    @pytest.mark.anyio
    async def test_request_method(self, client_for):
        router = Router()

        @router.get("/api/method")
        async def get_method(req):
            return JSONResponse({"method": req.method})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/method")
        assert resp.status_code == 200
        assert resp.json()["method"] == "GET"

    @pytest.mark.anyio
    async def test_request_path(self, client_for):
        router = Router()

        @router.get("/api/health")
        async def health(req):
            return JSONResponse({"path": req.path})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["path"] == "/api/health"

    @pytest.mark.anyio
    async def test_request_method_post(self, client_for):
        router = Router()

        @router.post("/api/data")
        async def post_data(req):
            return JSONResponse({"method": req.method})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.post("/api/data")
        assert resp.status_code == 200
        assert resp.json()["method"] == "POST"


class TestRequestIsDisconnected:
    @pytest.mark.anyio
    async def test_is_disconnected_returns_false_when_connected(self, client_for):
        """is_disconnected returns False for a normal connected request."""
        router = Router()

        @router.get("/api/connected")
        async def connected(req):
            disconnected = await req.is_disconnected()
            return JSONResponse({"disconnected": disconnected})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/connected")
        assert resp.status_code == 200
        assert resp.json()["disconnected"] is False

    @pytest.mark.anyio
    async def test_is_disconnected_without_receive(self):
        """is_disconnected returns False when no receive callable is available."""
        from wesktop.asgi import Request

        scope = {"type": "http", "method": "GET", "path": "/test", "headers": []}
        req = Request(scope, {}, None, receive=None)
        assert await req.is_disconnected() is False


# ---------------------------------------------------------------------------
# 1.12 StreamResponse status code
# ---------------------------------------------------------------------------


class TestStreamResponseStatusCode:
    @pytest.mark.anyio
    async def test_stream_response_custom_status(self, client_for):
        """StreamResponse(gen, status=202) sends 202 status code."""
        router = Router()

        @router.get("/api/stream-202")
        async def stream_202(req):
            async def gen():
                yield "data: started\n\n"

            return StreamResponse(gen(), content_type="text/event-stream", status=202)

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/stream-202")
        assert resp.status_code == 202

    @pytest.mark.anyio
    async def test_stream_response_default_status_200(self, client_for):
        """StreamResponse default status is 200."""
        router = Router()

        @router.get("/api/stream-default")
        async def stream_default(req):
            async def gen():
                yield "data: ok\n\n"

            return StreamResponse(gen(), content_type="text/event-stream")

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/stream-default")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 1.13 ASGI helpers and type aliases
# ---------------------------------------------------------------------------


class TestAsgiHelpers:
    def test_type_aliases_exist(self):
        """Scope, Receive, Send are importable from wesktop."""
        from wesktop import Scope, Receive, Send
        # They should be type aliases, not None
        assert Scope is not None
        assert Receive is not None
        assert Send is not None

    @pytest.mark.anyio
    async def test_send_error_in_middleware(self, client_for):
        """send_error sends a JSON error response from middleware context."""
        router = Router()

        @router.get("/api/data")
        async def data(req):
            return JSONResponse({"ok": True})

        def blocking_middleware(app):
            async def mw(scope, receive, send):
                if scope["type"] == "http" and scope["path"] == "/api/blocked":
                    await send_error(send, 403, "forbidden")
                    return
                await app(scope, receive, send)
            return mw

        app = create_app(router, middleware=[blocking_middleware])
        async with client_for(app) as client:
            resp = await client.get("/api/blocked")
            assert resp.status_code == 403
            assert resp.json() == {"detail": "forbidden"}

            # Other routes still work
            resp = await client.get("/api/data")
            assert resp.status_code == 200
            assert resp.json() == {"ok": True}


# ---------------------------------------------------------------------------
# 1.14 Response headers and cookies
# ---------------------------------------------------------------------------


class TestResponseHeadersAndCookies:
    @pytest.mark.anyio
    async def test_json_response_with_cookies(self, client_for):
        """JSONResponse with cookies sends Set-Cookie header."""
        router = Router()

        @router.get("/api/login")
        async def login(req):
            cookie = set_cookie("session", "abc123", httponly=True)
            return JSONResponse({"logged_in": True}, cookies=[cookie])

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/login")
        assert resp.status_code == 200
        assert resp.json() == {"logged_in": True}
        cookie_header = resp.headers.get("set-cookie")
        assert cookie_header is not None
        assert "session=abc123" in cookie_header
        assert "HttpOnly" in cookie_header

    @pytest.mark.anyio
    async def test_json_response_with_custom_headers(self, client_for):
        """JSONResponse with headers dict."""
        router = Router()

        @router.get("/api/custom")
        async def custom(req):
            return JSONResponse({"ok": True}, headers={"X-Custom": "val"})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/custom")
        assert resp.status_code == 200
        assert resp.headers["x-custom"] == "val"

    @pytest.mark.anyio
    async def test_delete_cookie_clears(self, client_for):
        """delete_cookie produces Set-Cookie with Max-Age=0."""
        router = Router()

        @router.get("/api/logout")
        async def logout(req):
            return JSONResponse({"logged_out": True}, cookies=[delete_cookie("session")])

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/logout")
        assert resp.status_code == 200
        cookie_header = resp.headers.get("set-cookie")
        assert cookie_header is not None
        assert "session=" in cookie_header
        assert "Max-Age=0" in cookie_header

    def test_set_cookie_format(self):
        """set_cookie produces a valid Set-Cookie string."""
        result = set_cookie("token", "xyz", httponly=True, samesite="strict", max_age=3600, secure=True)
        assert "token=xyz" in result
        assert "HttpOnly" in result
        assert "SameSite=strict" in result
        assert "Max-Age=3600" in result
        assert "Secure" in result
        assert "Path=/" in result

    def test_delete_cookie_format(self):
        """delete_cookie produces a valid clearing Set-Cookie string."""
        result = delete_cookie("session")
        assert result == "session=; Path=/; Max-Age=0"

    def test_delete_cookie_custom_path(self):
        result = delete_cookie("session", path="/api")
        assert result == "session=; Path=/api; Max-Age=0"


# ---------------------------------------------------------------------------
# 1.15 Cookie extraction on Request
# ---------------------------------------------------------------------------


class TestCookieExtraction:
    @pytest.mark.anyio
    async def test_request_cookies_property(self, client_for):
        """Request with Cookie header, req.cookies returns parsed dict."""
        router = Router()

        @router.get("/api/cookies")
        async def read_cookies(req):
            return JSONResponse({"cookies": req.cookies})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get(
                "/api/cookies",
                headers={"cookie": "session=abc123; theme=dark"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["cookies"] == {"session": "abc123", "theme": "dark"}

    @pytest.mark.anyio
    async def test_request_cookie_method(self, client_for):
        """req.cookie("session") returns value, req.cookie("missing") returns None."""
        router = Router()

        @router.get("/api/cookie")
        async def read_cookie(req):
            return JSONResponse({
                "session": req.cookie("session"),
                "missing": req.cookie("missing"),
                "default": req.cookie("missing", "fallback"),
            })

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get(
                "/api/cookie",
                headers={"cookie": "session=abc123"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session"] == "abc123"
        assert data["missing"] is None
        assert data["default"] == "fallback"

    @pytest.mark.anyio
    async def test_no_cookie_header(self, client_for):
        """No Cookie header -> empty dict."""
        router = Router()

        @router.get("/api/no-cookies")
        async def no_cookies(req):
            return JSONResponse({"cookies": req.cookies})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/no-cookies")
        assert resp.status_code == 200
        assert resp.json()["cookies"] == {}


# ---------------------------------------------------------------------------
# 1.19 Middleware constructor API
# ---------------------------------------------------------------------------


class TestMiddlewareConstructorAPI:
    @pytest.mark.anyio
    async def test_callable_middleware_factory(self, client_for):
        """A pre-configured middleware (lambda/partial) adds a custom header."""
        router = Router()

        @router.get("/api/data")
        async def data(req):
            return JSONResponse({"ok": True})

        def header_middleware(app, *, header_name, header_value):
            async def mw(scope, receive, send):
                if scope["type"] == "http":
                    async def wrapped_send(message):
                        if message["type"] == "http.response.start":
                            message["headers"] = list(message.get("headers", []))
                            message["headers"].append(
                                [header_name.encode(), header_value.encode()]
                            )
                        await send(message)
                    await app(scope, receive, wrapped_send)
                else:
                    await app(scope, receive, send)
            return mw

        configured_mw = partial(header_middleware, header_name="X-Powered-By", header_value="wesktop")
        app = create_app(router, middleware=[configured_mw])
        async with client_for(app) as client:
            resp = await client.get("/api/data")
        assert resp.status_code == 200
        assert resp.headers["x-powered-by"] == "wesktop"

    @pytest.mark.anyio
    async def test_lambda_middleware(self, client_for):
        """A lambda middleware factory works."""
        router = Router()

        @router.get("/api/test")
        async def test_handler(req):
            return JSONResponse({"ok": True})

        invoked = []

        def make_logging_mw(marker):
            def factory(app):
                async def mw(scope, receive, send):
                    invoked.append(marker)
                    await app(scope, receive, send)
                return mw
            return factory

        app = create_app(router, middleware=[make_logging_mw("A")])
        async with client_for(app) as client:
            resp = await client.get("/api/test")
        assert resp.status_code == 200
        assert "A" in invoked


# ---------------------------------------------------------------------------
# 1.2 query_list(name)
# ---------------------------------------------------------------------------


class TestQueryList:
    @pytest.mark.anyio
    async def test_multi_value_query_param(self, client_for):
        """?tag=a&tag=b -> req.query_list("tag") returns ["a", "b"]."""
        router = Router()

        @router.get("/api/tags")
        async def tags(req):
            return JSONResponse({"tags": req.query_list("tag")})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/tags?tag=a&tag=b")
        assert resp.status_code == 200
        assert resp.json()["tags"] == ["a", "b"]

    @pytest.mark.anyio
    async def test_query_list_with_type_coercion(self, client_for):
        """?n=1&n=2 with type_=int -> [1, 2]."""
        router = Router()

        @router.get("/api/numbers")
        async def numbers(req):
            return JSONResponse({"numbers": req.query_list("n", type_=int)})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/numbers?n=1&n=2")
        assert resp.status_code == 200
        assert resp.json()["numbers"] == [1, 2]

    @pytest.mark.anyio
    async def test_query_list_missing_key(self, client_for):
        """Missing key -> empty list."""
        router = Router()

        @router.get("/api/empty")
        async def empty(req):
            return JSONResponse({"items": req.query_list("missing")})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/empty")
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    @pytest.mark.anyio
    async def test_query_list_single_value(self, client_for):
        """?tag=only -> returns ["only"]."""
        router = Router()

        @router.get("/api/single")
        async def single(req):
            return JSONResponse({"tags": req.query_list("tag")})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/single?tag=only")
        assert resp.status_code == 200
        assert resp.json()["tags"] == ["only"]


# ---------------------------------------------------------------------------
# 1.3 Query parameter validation (constraints)
# ---------------------------------------------------------------------------


class TestQueryParameterValidation:
    @pytest.mark.anyio
    async def test_ge_violation_returns_422(self, client_for):
        """?limit=-1 with ge=0 -> 422."""
        router = Router()

        @router.get("/api/items")
        async def items(req):
            limit = req.query("limit", type_=int, ge=0)
            return JSONResponse({"limit": limit})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/items?limit=-1")
        assert resp.status_code == 422
        assert "must be >= 0" in resp.json()["detail"]

    @pytest.mark.anyio
    async def test_le_violation_returns_422(self, client_for):
        """?limit=200 with le=100 -> 422."""
        router = Router()

        @router.get("/api/items")
        async def items(req):
            limit = req.query("limit", type_=int, le=100)
            return JSONResponse({"limit": limit})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/items?limit=200")
        assert resp.status_code == 422
        assert "must be <= 100" in resp.json()["detail"]

    @pytest.mark.anyio
    async def test_min_length_violation_returns_422(self, client_for):
        """?q=ab with min_length=3 -> 422."""
        router = Router()

        @router.get("/api/search")
        async def search(req):
            q = req.query("q", min_length=3)
            return JSONResponse({"q": q})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/search?q=ab")
        assert resp.status_code == 422
        assert "length >= 3" in resp.json()["detail"]

    @pytest.mark.anyio
    async def test_max_length_violation_returns_422(self, client_for):
        """?q=toolong with max_length=5 -> 422."""
        router = Router()

        @router.get("/api/search")
        async def search(req):
            q = req.query("q", max_length=5)
            return JSONResponse({"q": q})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/search?q=toolong")
        assert resp.status_code == 422
        assert "length <= 5" in resp.json()["detail"]

    @pytest.mark.anyio
    async def test_valid_values_pass_constraints(self, client_for):
        """Valid values within constraints pass through."""
        router = Router()

        @router.get("/api/items")
        async def items(req):
            limit = req.query("limit", type_=int, ge=0, le=100)
            return JSONResponse({"limit": limit})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/items?limit=50")
        assert resp.status_code == 200
        assert resp.json()["limit"] == 50

    @pytest.mark.anyio
    async def test_ge_and_le_combined(self, client_for):
        """ge and le can be combined; boundary values pass."""
        router = Router()

        @router.get("/api/range")
        async def range_check(req):
            val = req.query("v", type_=int, ge=1, le=10)
            return JSONResponse({"v": val})

        app = create_app(router)
        async with client_for(app) as client:
            # Boundary: exactly ge
            resp = await client.get("/api/range?v=1")
            assert resp.status_code == 200
            assert resp.json()["v"] == 1

            # Boundary: exactly le
            resp = await client.get("/api/range?v=10")
            assert resp.status_code == 200
            assert resp.json()["v"] == 10

            # Below ge
            resp = await client.get("/api/range?v=0")
            assert resp.status_code == 422

            # Above le
            resp = await client.get("/api/range?v=11")
            assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_string_length_valid(self, client_for):
        """String length within bounds passes."""
        router = Router()

        @router.get("/api/search")
        async def search(req):
            q = req.query("q", min_length=2, max_length=10)
            return JSONResponse({"q": q})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/search?q=hello")
        assert resp.status_code == 200
        assert resp.json()["q"] == "hello"


# ---------------------------------------------------------------------------
# 1.18 query_params property and coercion failure
# ---------------------------------------------------------------------------


class TestQueryParams:
    @pytest.mark.anyio
    async def test_query_params_returns_dict(self, client_for):
        """req.query_params returns dict with first value per key."""
        router = Router()

        @router.get("/api/params")
        async def params(req):
            return JSONResponse({"params": req.query_params})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/params?token=abc&page=2")
        assert resp.status_code == 200
        data = resp.json()["params"]
        assert data["token"] == "abc"
        assert data["page"] == "2"

    @pytest.mark.anyio
    async def test_query_params_first_value_wins(self, client_for):
        """With ?tag=a&tag=b, query_params["tag"] returns "a" (first value)."""
        router = Router()

        @router.get("/api/first")
        async def first(req):
            return JSONResponse({"tag": req.query_params.get("tag")})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/first?tag=a&tag=b")
        assert resp.status_code == 200
        assert resp.json()["tag"] == "a"

    @pytest.mark.anyio
    async def test_query_params_empty_when_no_query_string(self, client_for):
        """No query string -> empty dict."""
        router = Router()

        @router.get("/api/empty")
        async def empty(req):
            return JSONResponse({"params": req.query_params})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/empty")
        assert resp.status_code == 200
        assert resp.json()["params"] == {}

    @pytest.mark.anyio
    async def test_query_params_get_method(self, client_for):
        """query_params.get("token") works like dict.get()."""
        router = Router()

        @router.get("/api/auth")
        async def auth(req):
            token = req.query_params.get("token")
            return JSONResponse({"token": token})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/auth?token=mytoken")
        assert resp.status_code == 200
        assert resp.json()["token"] == "mytoken"


class TestQueryCoercionFailure:
    @pytest.mark.anyio
    async def test_coercion_failure_raises_422(self, client_for):
        """?limit=abc with type_=int -> 422, not silent default."""
        router = Router()

        @router.get("/api/items")
        async def items(req):
            limit = req.query("limit", default=10, type_=int)
            return JSONResponse({"limit": limit})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/items?limit=abc")
        assert resp.status_code == 422
        assert "cannot convert" in resp.json()["detail"]
        assert "'abc'" in resp.json()["detail"]
        assert "int" in resp.json()["detail"]

    @pytest.mark.anyio
    async def test_absent_key_uses_default(self, client_for):
        """?limit absent with default=10 -> returns 10."""
        router = Router()

        @router.get("/api/items")
        async def items(req):
            limit = req.query("limit", default=10, type_=int)
            return JSONResponse({"limit": limit})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/items")
        assert resp.status_code == 200
        assert resp.json()["limit"] == 10

    @pytest.mark.anyio
    async def test_absent_key_no_default_returns_none(self, client_for):
        """Absent key with no default -> returns None."""
        router = Router()

        @router.get("/api/items")
        async def items(req):
            limit = req.query("limit", type_=int)
            return JSONResponse({"limit": limit})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/items")
        assert resp.status_code == 200
        assert resp.json()["limit"] is None

    @pytest.mark.anyio
    async def test_coercion_failure_does_not_use_default(self, client_for):
        """Even with a default, coercion failure raises 422."""
        router = Router()

        @router.get("/api/items")
        async def items(req):
            limit = req.query("limit", default=50, type_=int)
            return JSONResponse({"limit": limit})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/items?limit=notanumber")
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_valid_coercion_works(self, client_for):
        """?limit=42 with type_=int -> 42."""
        router = Router()

        @router.get("/api/items")
        async def items(req):
            limit = req.query("limit", type_=int)
            return JSONResponse({"limit": limit})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/items?limit=42")
        assert resp.status_code == 200
        assert resp.json()["limit"] == 42


# ---------------------------------------------------------------------------
# 1.4 Path parameter type coercion
# ---------------------------------------------------------------------------


class TestPathParameterTypeCoercion:
    @pytest.mark.anyio
    async def test_int_param_matches_numeric(self, client_for):
        """/{id:int} matches /42 with params["id"] == 42 (int, not str)."""
        router = Router()

        @router.get("/items/{id:int}")
        async def get_item(req):
            item_id = req.path_params["id"]
            return JSONResponse({
                "id": item_id,
                "type": type(item_id).__name__,
            })

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/items/42")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 42
        assert data["type"] == "int"

    @pytest.mark.anyio
    async def test_int_param_rejects_non_numeric(self, client_for):
        """/{id:int} does not match /abc -> 404."""
        router = Router()

        @router.get("/items/{id:int}")
        async def get_item(req):
            return JSONResponse({"id": req.path_params["id"]})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/items/abc")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_str_param_explicit(self, client_for):
        """{param:str} works the same as {param}."""
        router = Router()

        @router.get("/users/{name:str}")
        async def get_user(req):
            return JSONResponse({
                "name": req.path_params["name"],
                "type": type(req.path_params["name"]).__name__,
            })

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/users/alice")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "alice"
        assert data["type"] == "str"

    @pytest.mark.anyio
    async def test_plain_param_is_string(self, client_for):
        """{param} without type annotation is str by default."""
        router = Router()

        @router.get("/items/{slug}")
        async def get_item(req):
            return JSONResponse({
                "slug": req.path_params["slug"],
                "type": type(req.path_params["slug"]).__name__,
            })

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/items/my-slug")
        assert resp.status_code == 200
        data = resp.json()
        assert data["slug"] == "my-slug"
        assert data["type"] == "str"

    @pytest.mark.anyio
    async def test_int_param_negative_number(self, client_for):
        """Negative integers should match {id:int} since int() handles them."""
        router = Router()

        @router.get("/items/{id:int}")
        async def get_item(req):
            return JSONResponse({"id": req.path_params["id"]})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/items/-5")
        assert resp.status_code == 200
        assert resp.json()["id"] == -5

    @pytest.mark.anyio
    async def test_multiple_typed_params(self, client_for):
        """Multiple typed params in one route."""
        router = Router()

        @router.get("/users/{user_id:int}/posts/{post_id:int}")
        async def get_post(req):
            return JSONResponse({
                "user_id": req.path_params["user_id"],
                "post_id": req.path_params["post_id"],
            })

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/users/1/posts/42")
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == 1
        assert data["post_id"] == 42

    def test_unknown_type_raises(self):
        """Unknown type annotation raises ValueError during add_route."""
        router = Router()
        with pytest.raises(ValueError, match="Unknown path parameter type"):
            router.add_route("GET", "/items/{id:float}", lambda r: None)


# ---------------------------------------------------------------------------
# 1.6 Exception handler registry
# ---------------------------------------------------------------------------


class TestExceptionHandlerRegistry:
    @pytest.mark.anyio
    async def test_registered_handler_for_valueerror(self, client_for):
        """Register handler for ValueError -> 422. Handler raises ValueError."""
        router = Router()

        @router.get("/api/validate")
        async def validate(req):
            raise ValueError("bad value")

        async def handle_value_error(request, exc):
            return JSONResponse({"detail": str(exc)}, status=422)

        app = create_app(
            router,
            exception_handlers={ValueError: handle_value_error},
        )
        async with client_for(app) as client:
            resp = await client.get("/api/validate")
        assert resp.status_code == 422
        assert resp.json()["detail"] == "bad value"

    @pytest.mark.anyio
    async def test_unregistered_exception_falls_through_to_500(self, client_for):
        """Exception type not in registry -> generic 500."""
        router = Router()

        @router.get("/api/crash")
        async def crash(req):
            raise RuntimeError("boom")

        async def handle_value_error(request, exc):
            return JSONResponse({"detail": str(exc)}, status=422)

        app = create_app(
            router,
            exception_handlers={ValueError: handle_value_error},
        )
        async with client_for(app) as client:
            resp = await client.get("/api/crash")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Internal server error"

    @pytest.mark.anyio
    async def test_most_specific_handler_wins(self, client_for):
        """Subclass handler takes priority over parent handler."""
        router = Router()

        class CustomError(ValueError):
            pass

        @router.get("/api/specific")
        async def specific(req):
            raise CustomError("specific error")

        async def handle_value_error(request, exc):
            return JSONResponse({"detail": "generic ValueError"}, status=400)

        async def handle_custom_error(request, exc):
            return JSONResponse({"detail": "specific CustomError"}, status=422)

        app = create_app(
            router,
            exception_handlers={
                ValueError: handle_value_error,
                CustomError: handle_custom_error,
            },
        )
        async with client_for(app) as client:
            resp = await client.get("/api/specific")
        assert resp.status_code == 422
        assert resp.json()["detail"] == "specific CustomError"

    @pytest.mark.anyio
    async def test_httperror_still_takes_priority(self, client_for):
        """HTTPError is caught before checking exception_handlers."""
        router = Router()

        @router.get("/api/http-error")
        async def http_error(req):
            raise HTTPError(403, "forbidden")

        async def handle_all(request, exc):
            return JSONResponse({"detail": "caught by handler"}, status=500)

        app = create_app(
            router,
            exception_handlers={Exception: handle_all},
        )
        async with client_for(app) as client:
            resp = await client.get("/api/http-error")
        assert resp.status_code == 403
        assert resp.json()["detail"] == "forbidden"

    @pytest.mark.anyio
    async def test_no_exception_handlers_parameter(self, client_for):
        """create_app with no exception_handlers still works normally."""
        router = Router()

        @router.get("/api/ok")
        async def ok(req):
            return JSONResponse({"ok": True})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/ok")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
