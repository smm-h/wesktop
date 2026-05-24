"""Tests for Phase 7: Dev experience (TestClient, ViteDevProxy, load_config)."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from wesktop.asgi import JSONResponse, Router, create_app
from wesktop.config import load_config
from wesktop.middleware import ViteDevProxy
from wesktop.testing import AsyncTestClient, TestClient


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------


def _make_app(**kwargs):
    """Build a minimal app with GET /api/health."""
    router = Router()

    @router.get("/api/health")
    async def health(req):
        return JSONResponse({"status": "ok"})

    return create_app(router, request_id=False, request_timing=False, **kwargs)


# -----------------------------------------------------------------------
# 7.1 TestClient
# -----------------------------------------------------------------------


class TestSyncTestClient:
    """Sync TestClient wrapping httpx."""

    def test_get(self):
        app = _make_app()
        with TestClient(app) as client:
            resp = client.get("/api/health")
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}

    def test_post(self):
        router = Router()

        @router.post("/api/echo")
        async def echo(req):
            return JSONResponse(req.json)

        app = create_app(router, request_id=False, request_timing=False)
        with TestClient(app) as client:
            resp = client.post("/api/echo", json={"hello": "world"})
            assert resp.status_code == 200
            assert resp.json() == {"hello": "world"}

    def test_put(self):
        router = Router()

        @router.put("/api/item")
        async def update(req):
            return JSONResponse({"method": "PUT"})

        app = create_app(router, request_id=False, request_timing=False)
        with TestClient(app) as client:
            resp = client.put("/api/item")
            assert resp.status_code == 200
            assert resp.json()["method"] == "PUT"

    def test_patch(self):
        router = Router()

        @router.patch("/api/item")
        async def patch_item(req):
            return JSONResponse({"method": "PATCH"})

        app = create_app(router, request_id=False, request_timing=False)
        with TestClient(app) as client:
            resp = client.patch("/api/item")
            assert resp.status_code == 200
            assert resp.json()["method"] == "PATCH"

    def test_delete(self):
        router = Router()

        @router.delete("/api/item")
        async def delete_item(req):
            return JSONResponse({"method": "DELETE"})

        app = create_app(router, request_id=False, request_timing=False)
        with TestClient(app) as client:
            resp = client.delete("/api/item")
            assert resp.status_code == 200
            assert resp.json()["method"] == "DELETE"

    def test_404(self):
        app = _make_app()
        with TestClient(app) as client:
            resp = client.get("/nonexistent")
            assert resp.status_code == 404

    def test_context_manager(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/api/health")
        assert resp.status_code == 200
        client.close()

    def test_without_lifespan(self):
        """Basic requests work without lifespan (ASGITransport does not
        trigger ASGI lifespan events -- lifespan testing requires
        a real server or a dedicated lifespan runner)."""
        router = Router()

        @router.get("/api/check")
        async def check(req):
            return JSONResponse({"ok": True})

        app = create_app(
            router, request_id=False, request_timing=False,
        )
        with TestClient(app) as client:
            resp = client.get("/api/check")
            assert resp.status_code == 200
            assert resp.json() == {"ok": True}


@pytest.mark.anyio
class TestAsyncTestClient:
    """Async TestClient wrapping httpx AsyncClient."""

    async def test_get(self):
        app = _make_app()
        async with AsyncTestClient(app) as client:
            resp = await client.get("/api/health")
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}

    async def test_post(self):
        router = Router()

        @router.post("/api/echo")
        async def echo(req):
            return JSONResponse(req.json)

        app = create_app(router, request_id=False, request_timing=False)
        async with AsyncTestClient(app) as client:
            resp = await client.post("/api/echo", json={"data": 42})
            assert resp.status_code == 200
            assert resp.json() == {"data": 42}

    async def test_multiple_requests(self):
        """Async client handles multiple sequential requests."""
        router = Router()

        counter = {"n": 0}

        @router.get("/api/count")
        async def count(req):
            counter["n"] += 1
            return JSONResponse({"count": counter["n"]})

        app = create_app(router, request_id=False, request_timing=False)
        async with AsyncTestClient(app) as client:
            r1 = await client.get("/api/count")
            r2 = await client.get("/api/count")
            assert r1.json()["count"] == 1
            assert r2.json()["count"] == 2


# -----------------------------------------------------------------------
# 7.2 ViteDevProxy
# -----------------------------------------------------------------------


def _make_fake_vite_app(*, html_body: str = "<html>vite</html>"):
    """Build a tiny ASGI app that pretends to be Vite."""

    async def vite_app(scope, receive, send):
        if scope["type"] == "http":
            body = html_body.encode()
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    [b"content-type", b"text/html"],
                    [b"content-length", str(len(body)).encode()],
                ],
            })
            await send({"type": "http.response.body", "body": body})
        elif scope["type"] == "lifespan":
            msg = await receive()
            if msg["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
                await receive()
                await send({"type": "lifespan.shutdown.complete"})

    return vite_app


class TestViteDevProxyRouting:
    """Test that ViteDevProxy correctly routes API vs non-API requests."""

    def test_is_api_request_default_prefix(self):
        proxy = ViteDevProxy(lambda *a: None, vite_port=5173)
        assert proxy._is_api_request("/api/health") is True
        assert proxy._is_api_request("/api") is True
        assert proxy._is_api_request("/api/v1/data") is True
        assert proxy._is_api_request("/events") is True
        assert proxy._is_api_request("/events/stream") is True
        assert proxy._is_api_request("/") is False
        assert proxy._is_api_request("/index.html") is False
        assert proxy._is_api_request("/assets/style.css") is False

    def test_is_api_request_custom_prefix(self):
        proxy = ViteDevProxy(lambda *a: None, vite_port=5173, api_prefix="/v2")
        assert proxy._is_api_request("/v2/health") is True
        assert proxy._is_api_request("/v2") is True
        assert proxy._is_api_request("/api/health") is False
        assert proxy._is_api_request("/") is False


@pytest.mark.anyio
class TestViteDevProxyHTTP:
    """Test HTTP proxying to a mock Vite server."""

    async def test_api_request_passes_through(self):
        """API requests go to the inner app, not to Vite."""
        app = _make_app()
        proxy = ViteDevProxy(app, vite_port=59999)

        async with AsyncClient(
            transport=ASGITransport(app=proxy),
            base_url="http://test",
        ) as client:
            resp = await client.get("/api/health")
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}

    async def test_non_api_request_proxied(self):
        """Non-API requests are forwarded to the Vite server."""
        app = _make_app()

        # Mock httpx.AsyncClient to simulate Vite response
        mock_response = httpx.Response(
            200,
            content=b"<html>vite homepage</html>",
            headers={"content-type": "text/html"},
        )

        proxy = ViteDevProxy(app, vite_port=5173)

        with patch.object(proxy, "_get_client") as mock_get:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_get.return_value = mock_client

            async with AsyncClient(
                transport=ASGITransport(app=proxy),
                base_url="http://test",
            ) as client:
                resp = await client.get("/")
                assert resp.status_code == 200
                assert b"vite homepage" in resp.content

            mock_client.request.assert_called_once()
            call_kwargs = mock_client.request.call_args
            assert call_kwargs.kwargs["method"] == "GET" or call_kwargs[1].get("method") == "GET"

    async def test_events_path_passes_through(self):
        """/events path goes to the inner app."""
        router = Router()

        @router.get("/events")
        async def events(req):
            return JSONResponse({"type": "sse"})

        app = create_app(router, request_id=False, request_timing=False)
        proxy = ViteDevProxy(app, vite_port=59999)

        async with AsyncClient(
            transport=ASGITransport(app=proxy),
            base_url="http://test",
        ) as client:
            resp = await client.get("/events")
            assert resp.status_code == 200
            assert resp.json() == {"type": "sse"}

    async def test_vite_unreachable_returns_502(self):
        """When Vite server is not running, proxy returns 502."""
        app = _make_app()
        proxy = ViteDevProxy(app, vite_port=59999)

        with patch.object(proxy, "_get_client") as mock_get:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(
                side_effect=httpx.ConnectError("connection refused"),
            )
            mock_get.return_value = mock_client

            async with AsyncClient(
                transport=ASGITransport(app=proxy),
                base_url="http://test",
            ) as client:
                resp = await client.get("/")
                assert resp.status_code == 502

    async def test_query_string_forwarded(self):
        """Query string is included in the proxied URL."""
        app = _make_app()
        proxy = ViteDevProxy(app, vite_port=5173)

        captured_urls = []

        with patch.object(proxy, "_get_client") as mock_get:
            mock_response = httpx.Response(200, content=b"ok")
            mock_client = AsyncMock()

            async def capture_request(**kwargs):
                captured_urls.append(kwargs.get("url"))
                return mock_response

            mock_client.request = AsyncMock(side_effect=capture_request)
            mock_get.return_value = mock_client

            async with AsyncClient(
                transport=ASGITransport(app=proxy),
                base_url="http://test",
            ) as client:
                await client.get("/page?foo=bar")

            assert len(captured_urls) == 1
            assert "foo=bar" in str(captured_urls[0])


@pytest.mark.anyio
class TestViteDevProxyCreateApp:
    """Test vite_dev_port parameter on create_app."""

    async def test_create_app_with_vite_dev_port(self):
        """create_app(vite_dev_port=...) wraps the app in ViteDevProxy."""
        router = Router()

        @router.get("/api/health")
        async def health(req):
            return JSONResponse({"status": "ok"})

        app = create_app(
            router,
            vite_dev_port=5173,
            request_id=False,
            request_timing=False,
        )

        # API requests should still work (pass through proxy)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/api/health")
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}


# -----------------------------------------------------------------------
# 7.3 load_config
# -----------------------------------------------------------------------


class TestLoadConfig:
    """Test TOML config loading."""

    def test_load_basic_toml(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text(textwrap.dedent("""\
            [server]
            host = "127.0.0.1"
            port = 8080

            [plugins]
            paths = ["/home/user/plugins"]
        """))

        result = load_config(config_file)
        assert result["server"]["host"] == "127.0.0.1"
        assert result["server"]["port"] == 8080
        assert result["plugins"]["paths"] == ["/home/user/plugins"]

    def test_load_with_pydantic_schema(self, tmp_path):
        from pydantic import BaseModel

        class ServerConfig(BaseModel):
            host: str
            port: int

        class AppConfig(BaseModel):
            server: ServerConfig

        config_file = tmp_path / "config.toml"
        config_file.write_text(textwrap.dedent("""\
            [server]
            host = "0.0.0.0"
            port = 9100
        """))

        result = load_config(config_file, schema=AppConfig)
        assert isinstance(result, AppConfig)
        assert result.server.host == "0.0.0.0"
        assert result.server.port == 9100

    def test_load_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nonexistent.toml")

    def test_load_invalid_toml(self, tmp_path):
        import tomllib

        config_file = tmp_path / "bad.toml"
        config_file.write_text("this is not valid toml [[[")

        with pytest.raises(tomllib.TOMLDecodeError):
            load_config(config_file)

    def test_load_schema_validation_error(self, tmp_path):
        from pydantic import BaseModel, ValidationError

        class StrictConfig(BaseModel):
            name: str
            count: int

        config_file = tmp_path / "config.toml"
        config_file.write_text(textwrap.dedent("""\
            name = "test"
            count = "not_a_number"
        """))

        with pytest.raises(ValidationError):
            load_config(config_file, schema=StrictConfig)

    def test_load_empty_toml(self, tmp_path):
        config_file = tmp_path / "empty.toml"
        config_file.write_text("")

        result = load_config(config_file)
        assert result == {}

    def test_load_string_path(self, tmp_path):
        """load_config accepts str paths, not just Path objects."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('key = "value"\n')

        result = load_config(str(config_file))
        assert result["key"] == "value"


# -----------------------------------------------------------------------
# Export verification
# -----------------------------------------------------------------------


class TestExports:
    """Verify all Phase 7 symbols are exported from wesktop."""

    def test_test_client_exported(self):
        from wesktop import TestClient as TC
        assert TC is TestClient

    def test_async_test_client_exported(self):
        from wesktop import AsyncTestClient as ATC
        assert ATC is AsyncTestClient

    def test_vite_dev_proxy_exported(self):
        from wesktop import ViteDevProxy as VDP
        assert VDP is ViteDevProxy

    def test_load_config_exported(self):
        from wesktop import load_config as lc
        assert lc is load_config
