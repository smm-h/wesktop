"""Comprehensive tests for the wesktop ASGI micro-framework."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from wesktop.asgi import (
    BytesResponse,
    HTMLResponse,
    JSONResponse,
    Request,
    Router,
    StreamResponse,
    TextResponse,
    _serve_spa_fallback,
    _serve_static,
    create_app,
)


# ---------------------------------------------------------------------------
# Router matching
# ---------------------------------------------------------------------------


class TestRouterMatching:
    def test_exact_path_match(self):
        r = Router()
        r.add_route("GET", "/api/health", lambda req: None)
        match = r.match("GET", "/api/health")
        assert match is not None
        handler, params = match
        assert params == {}

    def test_parameterized_path(self):
        r = Router()
        r.add_route("GET", "/api/users/{id}", lambda req: None)
        match = r.match("GET", "/api/users/42")
        assert match is not None
        _, params = match
        assert params == {"id": "42"}

    def test_multiple_params(self):
        r = Router()
        r.add_route("GET", "/api/{org}/repos/{repo}", lambda req: None)
        match = r.match("GET", "/api/acme/repos/widgets")
        assert match is not None
        _, params = match
        assert params == {"org": "acme", "repo": "widgets"}

    def test_method_filtering(self):
        """POST handler does not match GET request."""
        r = Router()
        r.add_route("POST", "/api/items", lambda req: None)
        assert r.match("GET", "/api/items") is None

    def test_no_match_returns_none(self):
        r = Router()
        r.add_route("GET", "/api/health", lambda req: None)
        assert r.match("GET", "/api/other") is None

    def test_no_match_different_segment_count(self):
        r = Router()
        r.add_route("GET", "/api/health", lambda req: None)
        assert r.match("GET", "/api/health/extra") is None

    def test_first_match_wins(self):
        r = Router()
        first = lambda req: "first"
        second = lambda req: "second"
        r.add_route("GET", "/api/{id}", first)
        r.add_route("GET", "/api/{name}", second)
        handler, _ = r.match("GET", "/api/42")
        assert handler is first

    def test_exact_beats_nothing_when_registered_first(self):
        """When an exact route is registered before a parameterized one,
        the exact route matches first."""
        r = Router()
        exact = lambda req: "exact"
        param = lambda req: "param"
        r.add_route("GET", "/api/health", exact)
        r.add_route("GET", "/api/{id}", param)
        handler, params = r.match("GET", "/api/health")
        assert handler is exact
        assert params == {}


# ---------------------------------------------------------------------------
# Router decorators
# ---------------------------------------------------------------------------


class TestRouterDecorators:
    def test_get_decorator(self):
        r = Router()

        @r.get("/path")
        async def handler(req):
            return {"ok": True}

        match = r.match("GET", "/path")
        assert match is not None
        assert match[0] is handler

    def test_post_decorator(self):
        r = Router()

        @r.post("/path")
        async def handler(req):
            return {"ok": True}

        match = r.match("POST", "/path")
        assert match is not None
        assert match[0] is handler

    def test_delete_decorator(self):
        r = Router()

        @r.delete("/path")
        async def handler(req):
            return {"ok": True}

        match = r.match("DELETE", "/path")
        assert match is not None
        assert match[0] is handler

    def test_add_route_put(self):
        r = Router()

        async def handler(req):
            return {"ok": True}

        r.add_route("PUT", "/path", handler)
        match = r.match("PUT", "/path")
        assert match is not None
        assert match[0] is handler

    def test_decorator_returns_original_function(self):
        """The decorator should return the original function unchanged."""
        r = Router()

        @r.get("/path")
        async def handler(req):
            return {"ok": True}

        # handler should still be callable as-is
        assert callable(handler)


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


class TestRequest:
    def _make_scope(self, **overrides):
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "query_string": b"",
            "headers": [],
        }
        scope.update(overrides)
        return scope

    def test_path_params(self):
        req = Request(self._make_scope(), {"id": "42"}, None)
        assert req.path_params == {"id": "42"}

    def test_json_decodes_body(self):
        body = json.dumps({"name": "alice"}).encode()
        req = Request(self._make_scope(), {}, body)
        assert req.json == {"name": "alice"}

    def test_json_none_when_no_body(self):
        req = Request(self._make_scope(), {}, None)
        assert req.json is None

    def test_json_none_on_invalid_json(self):
        req = Request(self._make_scope(), {}, b"not json")
        assert req.json is None

    def test_json_list_body(self):
        body = json.dumps([1, 2, 3]).encode()
        req = Request(self._make_scope(), {}, body)
        assert req.json == [1, 2, 3]

    def test_query_string_parameter(self):
        scope = self._make_scope(query_string=b"key=hello")
        req = Request(scope, {}, None)
        assert req.query("key") == "hello"

    def test_query_default_when_missing(self):
        scope = self._make_scope(query_string=b"")
        req = Request(scope, {}, None)
        assert req.query("missing", default="fallback") == "fallback"

    def test_query_type_coercion_int(self):
        scope = self._make_scope(query_string=b"page=5")
        req = Request(scope, {}, None)
        assert req.query("page", type_=int) == 5

    def test_query_type_coercion_failure_returns_default(self):
        scope = self._make_scope(query_string=b"page=abc")
        req = Request(scope, {}, None)
        assert req.query("page", default=1, type_=int) == 1

    def test_header_case_insensitive(self):
        scope = self._make_scope(headers=[
            (b"content-type", b"application/json"),
            (b"x-custom", b"value"),
        ])
        req = Request(scope, {}, None)
        assert req.header("Content-Type") == "application/json"
        assert req.header("CONTENT-TYPE") == "application/json"
        assert req.header("content-type") == "application/json"

    def test_header_default_when_missing(self):
        req = Request(self._make_scope(), {}, None)
        assert req.header("X-Missing") is None
        assert req.header("X-Missing", default="nope") == "nope"

    def test_body_property(self):
        body = b"raw bytes"
        req = Request(self._make_scope(), {}, body)
        assert req.body == b"raw bytes"

    def test_body_none(self):
        req = Request(self._make_scope(), {}, None)
        assert req.body is None

    def test_body_size(self):
        req = Request(self._make_scope(), {}, b"hello")
        assert req.body_size == 5

    def test_body_size_none(self):
        req = Request(self._make_scope(), {}, None)
        assert req.body_size == 0

    def test_json_is_lazy(self, monkeypatch):
        """JSON decoding should not happen until .json is accessed."""
        import msgspec as _msgspec

        calls = []
        original_decode = _msgspec.json.decode

        def tracking_decode(*args, **kwargs):
            calls.append(1)
            return original_decode(*args, **kwargs)

        monkeypatch.setattr(_msgspec.json, "decode", tracking_decode)

        body = b'{"key": "value"}'
        req = Request(self._make_scope(), {}, body)
        assert len(calls) == 0, "decode called eagerly during __init__"

        result = req.json
        assert len(calls) == 1, "decode not called on first .json access"
        assert result == {"key": "value"}

        result2 = req.json
        assert len(calls) == 1, "decode called again on second .json access"
        assert result2 == {"key": "value"}


# ---------------------------------------------------------------------------
# Response types
# ---------------------------------------------------------------------------


class TestResponses:
    def test_json_response_defaults(self):
        resp = JSONResponse({"key": "value"})
        assert resp.data == {"key": "value"}
        assert resp.status == 200

    def test_json_response_custom_status(self):
        resp = JSONResponse({"error": "bad"}, status=400)
        assert resp.status == 400

    def test_text_response_defaults(self):
        resp = TextResponse("hello")
        assert resp.text == "hello"
        assert resp.content_type == "text/plain"
        assert resp.status == 200
        assert resp.headers == {}

    def test_text_response_custom(self):
        resp = TextResponse("body", content_type="text/css", status=201, headers={"X-Foo": "bar"})
        assert resp.content_type == "text/css"
        assert resp.status == 201
        assert resp.headers == {"X-Foo": "bar"}

    def test_html_response_defaults(self):
        resp = HTMLResponse("<h1>Hi</h1>")
        assert resp.html == "<h1>Hi</h1>"
        assert resp.status == 200

    def test_html_response_custom_status(self):
        resp = HTMLResponse("<h1>Not Found</h1>", status=404)
        assert resp.status == 404

    def test_bytes_response_defaults(self):
        resp = BytesResponse(b"\x00\x01")
        assert resp.data == b"\x00\x01"
        assert resp.content_type == "application/octet-stream"
        assert resp.status == 200

    def test_bytes_response_custom(self):
        resp = BytesResponse(b"png-data", content_type="image/png", status=201)
        assert resp.content_type == "image/png"
        assert resp.status == 201

    def test_stream_response(self):
        async def gen():
            yield "chunk1"
            yield "chunk2"

        resp = StreamResponse(gen(), content_type="text/event-stream", headers={"X-Stream": "1"})
        assert resp.content_type == "text/event-stream"
        assert resp.headers == {"X-Stream": "1"}


# ---------------------------------------------------------------------------
# create_app integration (via httpx AsyncClient + ASGITransport)
# ---------------------------------------------------------------------------


def _make_test_app(**kwargs) -> Router:
    """Build a minimal router + app for integration tests."""
    router = Router()

    @router.get("/api/health")
    async def health(req):
        return JSONResponse({"status": "ok"})

    @router.get("/api/users/{id}")
    async def get_user(req):
        return JSONResponse({"id": req.path_params["id"]})

    @router.post("/api/echo")
    async def echo(req):
        return JSONResponse({"body": req.json, "ct": req.header("Content-Type")})

    @router.get("/api/search")
    async def search(req):
        q = req.query("q", default="")
        page = req.query("page", default=1, type_=int)
        return JSONResponse({"q": q, "page": page})

    @router.get("/api/text")
    async def text(req):
        return TextResponse("plain text")

    @router.get("/api/html")
    async def html(req):
        return HTMLResponse("<h1>Hello</h1>")

    @router.get("/api/bytes")
    async def raw(req):
        return BytesResponse(b"\x89PNG", content_type="image/png")

    @router.get("/api/bare-dict")
    async def bare_dict(req):
        return {"auto": "wrapped"}

    @router.get("/api/bare-list")
    async def bare_list(req):
        return [1, 2, 3]

    @router.get("/api/error")
    async def broken(req):
        raise RuntimeError("boom")

    return create_app(router, **kwargs)


@pytest.mark.anyio
async def test_get_json():
    app = _make_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert resp.headers["content-type"] == "application/json"


@pytest.mark.anyio
async def test_parameterized_route():
    app = _make_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/users/42")
    assert resp.status_code == 200
    assert resp.json() == {"id": "42"}


@pytest.mark.anyio
async def test_post_json_body():
    app = _make_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/echo",
            json={"msg": "hello"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["body"] == {"msg": "hello"}
    assert data["ct"] == "application/json"


@pytest.mark.anyio
async def test_query_params():
    app = _make_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/search?q=test&page=3")
    assert resp.json() == {"q": "test", "page": 3}


@pytest.mark.anyio
async def test_text_response():
    app = _make_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/text")
    assert resp.status_code == 200
    assert resp.text == "plain text"
    assert resp.headers["content-type"] == "text/plain"


@pytest.mark.anyio
async def test_html_response():
    app = _make_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/html")
    assert resp.status_code == 200
    assert resp.text == "<h1>Hello</h1>"
    assert resp.headers["content-type"] == "text/html"


@pytest.mark.anyio
async def test_bytes_response():
    app = _make_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/bytes")
    assert resp.status_code == 200
    assert resp.content == b"\x89PNG"
    assert resp.headers["content-type"] == "image/png"


@pytest.mark.anyio
async def test_bare_dict_auto_wraps_json():
    app = _make_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/bare-dict")
    assert resp.status_code == 200
    assert resp.json() == {"auto": "wrapped"}
    assert resp.headers["content-type"] == "application/json"


@pytest.mark.anyio
async def test_bare_list_auto_wraps_json():
    app = _make_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/bare-list")
    assert resp.status_code == 200
    assert resp.json() == [1, 2, 3]


@pytest.mark.anyio
async def test_404_on_unknown_route():
    app = _make_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/nonexistent")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Not found"}


@pytest.mark.anyio
async def test_404_on_method_mismatch():
    """GET to a POST-only route should 404."""
    app = _make_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/echo")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_handler_error_returns_500():
    app = _make_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/error")
    assert resp.status_code == 500
    assert resp.json() == {"detail": "Internal server error"}


# ---------------------------------------------------------------------------
# Static file serving
# ---------------------------------------------------------------------------


class TestStaticFiles:
    @pytest.mark.anyio
    async def test_serves_existing_file(self, tmp_path):
        static = tmp_path / "assets"
        static.mkdir()
        (static / "style.css").write_text("body { color: red; }")

        router = Router()
        app = create_app(router, static_dir=static, static_path="/assets")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/assets/style.css")
        assert resp.status_code == 200
        assert resp.text == "body { color: red; }"
        assert "text/css" in resp.headers["content-type"]

    @pytest.mark.anyio
    async def test_rejects_path_traversal(self, tmp_path):
        static = tmp_path / "assets"
        static.mkdir()
        # Create a file outside static dir
        (tmp_path / "secret.txt").write_text("secret")

        router = Router()
        app = create_app(router, static_dir=static, static_path="/assets")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/assets/../secret.txt")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_returns_404_for_nonexistent_file(self, tmp_path):
        static = tmp_path / "assets"
        static.mkdir()

        router = Router()
        app = create_app(router, static_dir=static, static_path="/assets")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/assets/nope.js")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_nested_static_file(self, tmp_path):
        static = tmp_path / "assets"
        (static / "js").mkdir(parents=True)
        (static / "js" / "app.js").write_text("console.log('hi')")

        router = Router()
        app = create_app(router, static_dir=static, static_path="/assets")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/assets/js/app.js")
        assert resp.status_code == 200
        assert resp.text == "console.log('hi')"


# ---------------------------------------------------------------------------
# SPA fallback
# ---------------------------------------------------------------------------


class TestSpaFallback:
    @pytest.mark.anyio
    async def test_get_unknown_path_returns_index_html(self, tmp_path):
        index = tmp_path / "index.html"
        index.write_text("<!DOCTYPE html><html></html>")

        router = Router()
        app = create_app(router, spa_fallback=index)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/some/client/route")
        assert resp.status_code == 200
        assert resp.text == "<!DOCTYPE html><html></html>"
        assert resp.headers["content-type"] == "text/html"

    @pytest.mark.anyio
    async def test_post_unknown_path_returns_404(self, tmp_path):
        """SPA fallback is GET-only; POST to unknown path should 404."""
        index = tmp_path / "index.html"
        index.write_text("<!DOCTYPE html>")

        router = Router()
        app = create_app(router, spa_fallback=index)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/some/client/route")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_spa_fallback_missing_file_returns_404(self, tmp_path):
        """When the fallback file doesn't exist, return 404."""
        missing = tmp_path / "missing.html"

        router = Router()
        app = create_app(router, spa_fallback=missing)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/some/client/route")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_spa_serves_sibling_static_file_before_fallback(self, tmp_path):
        """Files adjacent to index.html are served directly."""
        index = tmp_path / "index.html"
        index.write_text("<!DOCTYPE html>")
        (tmp_path / "favicon.ico").write_bytes(b"\x00\x00\x01\x00")

        router = Router()
        app = create_app(router, spa_fallback=index)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/favicon.ico")
        assert resp.status_code == 200
        assert resp.content == b"\x00\x00\x01\x00"

    @pytest.mark.anyio
    async def test_api_routes_take_priority_over_spa(self, tmp_path):
        """Registered API routes should match before the SPA fallback."""
        index = tmp_path / "index.html"
        index.write_text("<!DOCTYPE html>")

        router = Router()

        @router.get("/api/health")
        async def health(req):
            return JSONResponse({"status": "ok"})

        app = create_app(router, spa_fallback=index)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class TestMiddleware:
    @pytest.mark.anyio
    async def test_middleware_wraps_app(self):
        """A middleware can modify the response."""
        call_order = []

        class OuterMiddleware:
            def __init__(self, app):
                self.app = app

            async def __call__(self, scope, receive, send):
                call_order.append("outer")
                await self.app(scope, receive, send)

        class InnerMiddleware:
            def __init__(self, app):
                self.app = app

            async def __call__(self, scope, receive, send):
                call_order.append("inner")
                await self.app(scope, receive, send)

        router = Router()

        @router.get("/api/health")
        async def health(req):
            return {"status": "ok"}

        # OuterMiddleware listed first = outermost wrapper
        app = create_app(router, middleware=[OuterMiddleware, InnerMiddleware])
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/health")
        assert resp.status_code == 200
        assert call_order == ["outer", "inner"]

    @pytest.mark.anyio
    async def test_single_middleware(self):
        """Single middleware wraps correctly."""
        invoked = []

        class LogMiddleware:
            def __init__(self, app):
                self.app = app

            async def __call__(self, scope, receive, send):
                invoked.append(scope.get("path"))
                await self.app(scope, receive, send)

        router = Router()

        @router.get("/test")
        async def handler(req):
            return {"ok": True}

        app = create_app(router, middleware=[LogMiddleware])
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.get("/test")
        assert invoked == ["/test"]


# ---------------------------------------------------------------------------
# _serve_static and _serve_spa_fallback unit tests (lower level)
# ---------------------------------------------------------------------------


class TestServeStaticUnit:
    @pytest.mark.anyio
    async def test_serve_static_returns_true_for_existing(self, tmp_path):
        (tmp_path / "file.txt").write_text("content")
        events = []

        async def mock_send(event):
            events.append(event)

        result = await _serve_static(mock_send, tmp_path, "file.txt")
        assert result is True
        assert events[0]["type"] == "http.response.start"
        assert events[0]["status"] == 200
        assert events[1]["body"] == b"content"

    @pytest.mark.anyio
    async def test_serve_static_returns_false_for_missing(self, tmp_path):
        async def mock_send(event):
            pass

        result = await _serve_static(mock_send, tmp_path, "nope.txt")
        assert result is False

    @pytest.mark.anyio
    async def test_serve_static_rejects_traversal(self, tmp_path):
        """Path traversal outside static_dir returns False."""
        (tmp_path / "secret").mkdir()
        (tmp_path / "secret" / "key.pem").write_text("private")
        static = tmp_path / "public"
        static.mkdir()

        async def mock_send(event):
            pass

        result = await _serve_static(mock_send, static, "../secret/key.pem")
        assert result is False


class TestServeSpaFallbackUnit:
    @pytest.mark.anyio
    async def test_serves_index_html(self, tmp_path):
        index = tmp_path / "index.html"
        index.write_text("<html></html>")
        events = []

        async def mock_send(event):
            events.append(event)

        await _serve_spa_fallback(mock_send, index)
        assert events[0]["status"] == 200
        assert events[1]["body"] == b"<html></html>"

    @pytest.mark.anyio
    async def test_returns_404_when_missing(self, tmp_path):
        missing = tmp_path / "missing.html"
        events = []

        async def mock_send(event):
            events.append(event)

        await _serve_spa_fallback(mock_send, missing)
        assert events[0]["status"] == 404


# ---------------------------------------------------------------------------
# TextResponse extra headers integration
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_text_response_extra_headers():
    """TextResponse custom headers appear in the HTTP response."""
    router = Router()

    @router.get("/styled")
    async def styled(req):
        return TextResponse(
            "body{}",
            content_type="text/css",
            headers={"Cache-Control": "max-age=3600"},
        )

    app = create_app(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/styled")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "max-age=3600"
    assert resp.headers["content-type"] == "text/css"


# ---------------------------------------------------------------------------
# StreamResponse integration
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_stream_response():
    """StreamResponse sends chunks iteratively."""
    router = Router()

    @router.get("/stream")
    async def stream(req):
        async def gen():
            yield "data: one\n\n"
            yield "data: two\n\n"

        return StreamResponse(gen(), content_type="text/event-stream")

    app = create_app(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/stream")
    assert resp.status_code == 200
    assert "data: one" in resp.text
    assert "data: two" in resp.text


# ---------------------------------------------------------------------------
# Combined static + SPA + routes
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_combined_static_spa_routes(tmp_path):
    """Ensure routing priority: API routes > static files > SPA fallback."""
    static = tmp_path / "assets"
    static.mkdir()
    (static / "app.js").write_text("// JS")

    index = tmp_path / "index.html"
    index.write_text("<!DOCTYPE html><html>SPA</html>")

    router = Router()

    @router.get("/api/data")
    async def data(req):
        return {"data": 42}

    app = create_app(
        router,
        static_dir=static,
        static_path="/assets",
        spa_fallback=index,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # API route
        resp = await c.get("/api/data")
        assert resp.status_code == 200
        assert resp.json() == {"data": 42}

        # Static file
        resp = await c.get("/assets/app.js")
        assert resp.status_code == 200
        assert resp.text == "// JS"

        # SPA fallback
        resp = await c.get("/some/page")
        assert resp.status_code == 200
        assert "SPA" in resp.text

        # POST to unknown still 404
        resp = await c.post("/unknown")
        assert resp.status_code == 404
