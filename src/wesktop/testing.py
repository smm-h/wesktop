"""Test client utilities for wesktop apps.

Provides sync and async test clients that wrap httpx with ASGITransport,
so tests can exercise a wesktop app without starting a real server.
Both clients run the ASGI lifespan protocol on enter and shut down on exit.

httpx is a dev/test dependency -- this module should only be imported
in test contexts.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from httpx import ASGITransport, AsyncClient


class AsyncTestClient:
    """Async test client for wesktop apps.

    Use as an async context manager::

        async with AsyncTestClient(app) as client:
            resp = await client.get("/health")
    """

    def __init__(self, app: Any, base_url: str = "http://test") -> None:
        self._app = app
        self._base_url = base_url
        self._client: AsyncClient | None = None

    async def __aenter__(self) -> AsyncClient:
        self._client = AsyncClient(
            transport=ASGITransport(app=self._app),
            base_url=self._base_url,
        )
        return self._client

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()


class _SyncTestClient:
    """Sync test client for wesktop apps.

    Runs an ``AsyncClient`` on a background event loop so that sync test
    code can call ``.get()``, ``.post()`` etc. without ``await``.

    Usage::

        with _SyncTestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == 200

    The class is named ``_SyncTestClient`` internally and exported as
    ``TestClient`` to avoid pytest treating it as a test class (pytest
    skips classes whose name starts with ``_``).
    """

    def __init__(self, app: Any, base_url: str = "http://test") -> None:
        self._app = app
        self._base_url = base_url
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._client: AsyncClient | None = None

    def _start_loop(self) -> None:
        """Run the event loop in a background thread."""
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _run(self, coro: Any) -> Any:
        """Schedule a coroutine on the background loop and wait for result."""
        assert self._loop is not None
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=30)

    def _open(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._start_loop, daemon=True)
        self._thread.start()
        self._client = self._run(self._create_client())

    async def _create_client(self) -> AsyncClient:
        return AsyncClient(
            transport=ASGITransport(app=self._app),
            base_url=self._base_url,
        )

    def _close(self) -> None:
        if self._client:
            self._run(self._client.aclose())
            self._client = None
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        if self._loop:
            self._loop.close()
            self._loop = None

    def _ensure_open(self) -> None:
        if self._client is None:
            self._open()

    def get(self, *args: Any, **kwargs: Any) -> Any:
        self._ensure_open()
        return self._run(self._client.get(*args, **kwargs))

    def post(self, *args: Any, **kwargs: Any) -> Any:
        self._ensure_open()
        return self._run(self._client.post(*args, **kwargs))

    def put(self, *args: Any, **kwargs: Any) -> Any:
        self._ensure_open()
        return self._run(self._client.put(*args, **kwargs))

    def patch(self, *args: Any, **kwargs: Any) -> Any:
        self._ensure_open()
        return self._run(self._client.patch(*args, **kwargs))

    def delete(self, *args: Any, **kwargs: Any) -> Any:
        self._ensure_open()
        return self._run(self._client.delete(*args, **kwargs))

    def options(self, *args: Any, **kwargs: Any) -> Any:
        self._ensure_open()
        return self._run(self._client.options(*args, **kwargs))

    def head(self, *args: Any, **kwargs: Any) -> Any:
        self._ensure_open()
        return self._run(self._client.head(*args, **kwargs))

    def close(self) -> None:
        self._close()

    def __enter__(self) -> _SyncTestClient:
        self._open()
        return self

    def __exit__(self, *args: Any) -> None:
        self._close()


# Export with a pytest-friendly name (not starting with "Test")
TestClient = _SyncTestClient
