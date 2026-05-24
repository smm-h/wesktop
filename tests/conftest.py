"""Shared test fixtures for wesktop tests."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from wesktop.asgi import JSONResponse, Router, create_app


@pytest.fixture
def client_for():
    """Factory fixture: pass a wesktop ASGI app, get an httpx AsyncClient."""

    def _make_client(app, base_url: str = "http://test") -> AsyncClient:
        return AsyncClient(
            transport=ASGITransport(app=app),
            base_url=base_url,
        )

    return _make_client


@pytest.fixture
def sample_app():
    """Minimal wesktop app with GET /health."""
    router = Router()

    @router.get("/health")
    async def health(req):
        return JSONResponse({"status": "ok"})

    return create_app(router)


@pytest.fixture
async def sample_client(sample_app, client_for):
    """AsyncClient pointed at sample_app."""
    async with client_for(sample_app) as client:
        yield client
