"""Tests for Phase 1 follow-up fixes.

Covers:
- 1.2: WebSocket.receive_raw() returns raw ASGI message dict
- 1.3: Broadcaster heartbeat_interval yields SSE heartbeat comments
- 1.4: Recursive Pydantic model serialization in handler responses
"""

from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import BaseModel

from wesktop.asgi import (
    JSONResponse,
    Router,
    WebSocket,
    create_app,
)
from wesktop.sse import Broadcaster


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _ws_connect(app, path, headers=None, query_string=b""):
    """Simulate a WebSocket connection via raw ASGI scope/receive/send."""
    scope = {
        "type": "websocket",
        "path": path,
        "headers": headers or [],
        "query_string": query_string,
    }
    receive_queue: asyncio.Queue = asyncio.Queue()
    sent_messages: list[dict] = []

    await receive_queue.put({"type": "websocket.connect"})

    async def receive():
        return await receive_queue.get()

    async def send(msg):
        sent_messages.append(msg)

    return scope, receive, send, receive_queue, sent_messages


# ---------------------------------------------------------------------------
# 1.2 WebSocket.receive_raw()
# ---------------------------------------------------------------------------


class TestWebSocketReceiveRaw:
    @pytest.mark.anyio
    async def test_receive_raw_returns_raw_dict(self):
        """receive_raw() returns the raw ASGI message dict with type/bytes/text keys."""
        router = Router()
        captured_msg = {}

        @router.ws("/ws/raw")
        async def handler(ws):
            await ws.accept()
            msg = await ws.receive_raw()
            captured_msg.update(msg)

        app = create_app(router)
        scope, receive, send, recv_q, sent = await _ws_connect(app, "/ws/raw")
        await recv_q.put({
            "type": "websocket.receive",
            "bytes": b"\x00\x01\x02",
        })
        await app(scope, receive, send)

        assert captured_msg["type"] == "websocket.receive"
        assert captured_msg["bytes"] == b"\x00\x01\x02"

    @pytest.mark.anyio
    async def test_receive_raw_text_frame(self):
        """receive_raw() returns text frames as-is."""
        router = Router()
        captured_msg = {}

        @router.ws("/ws/raw-text")
        async def handler(ws):
            await ws.accept()
            msg = await ws.receive_raw()
            captured_msg.update(msg)

        app = create_app(router)
        scope, receive, send, recv_q, sent = await _ws_connect(app, "/ws/raw-text")
        await recv_q.put({
            "type": "websocket.receive",
            "text": '{"type": "resize", "rows": 24, "cols": 80}',
        })
        await app(scope, receive, send)

        assert captured_msg["type"] == "websocket.receive"
        assert "text" in captured_msg
        parsed = json.loads(captured_msg["text"])
        assert parsed["type"] == "resize"

    @pytest.mark.anyio
    async def test_receive_raw_disconnect(self):
        """receive_raw() returns disconnect messages."""
        router = Router()
        captured_msg = {}

        @router.ws("/ws/raw-dc")
        async def handler(ws):
            await ws.accept()
            msg = await ws.receive_raw()
            captured_msg.update(msg)

        app = create_app(router)
        scope, receive, send, recv_q, sent = await _ws_connect(app, "/ws/raw-dc")
        await recv_q.put({"type": "websocket.disconnect"})
        await app(scope, receive, send)

        assert captured_msg["type"] == "websocket.disconnect"


# ---------------------------------------------------------------------------
# 1.3 Broadcaster heartbeat_interval
# ---------------------------------------------------------------------------


class TestBroadcasterHeartbeat:
    @pytest.mark.anyio
    async def test_heartbeat_emitted_on_timeout(self):
        """With heartbeat_interval set, a heartbeat comment is yielded on timeout."""
        b = Broadcaster(strict=False, heartbeat_interval=0.05)
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=256)
        b._clients.append(queue)

        gen = b._event_generator(queue)
        # No messages in the queue, so it should timeout and yield heartbeat
        msg = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        assert msg == ": heartbeat\n\n"

        # Clean up
        await gen.aclose()

    @pytest.mark.anyio
    async def test_real_message_before_heartbeat(self):
        """With heartbeat_interval, real messages are yielded before timeout."""
        b = Broadcaster(strict=False, heartbeat_interval=5.0)
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=256)
        b._clients.append(queue)

        # Put a real message
        queue.put_nowait("event: ping\ndata: {}\n\n")

        gen = b._event_generator(queue)
        msg = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        assert msg == "event: ping\ndata: {}\n\n"

        await gen.aclose()

    @pytest.mark.anyio
    async def test_no_heartbeat_without_interval(self):
        """Without heartbeat_interval, generator blocks and yields nothing."""
        b = Broadcaster(strict=False)
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=256)
        b._clients.append(queue)

        gen = b._event_generator(queue)
        yielded = []

        async def collect():
            async for msg in gen:
                yielded.append(msg)

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.15)
        # After 150ms with no messages, nothing should have been yielded
        assert yielded == []
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.anyio
    async def test_multiple_heartbeats(self):
        """Multiple heartbeats are emitted while idle."""
        b = Broadcaster(strict=False, heartbeat_interval=0.03)
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=256)
        b._clients.append(queue)

        gen = b._event_generator(queue)
        msg1 = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        msg2 = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        assert msg1 == ": heartbeat\n\n"
        assert msg2 == ": heartbeat\n\n"

        await gen.aclose()


# ---------------------------------------------------------------------------
# 1.4 Recursive Pydantic serialization
# ---------------------------------------------------------------------------


class UserModel(BaseModel):
    name: str
    age: int


class AddressModel(BaseModel):
    city: str
    zip: str


class TestRecursivePydanticSerialization:
    @pytest.mark.anyio
    async def test_dict_with_nested_pydantic_model(self, client_for):
        """Handler returns dict containing a Pydantic model -> fully serialized."""
        router = Router()

        @router.get("/api/nested")
        async def nested(req):
            return {"user": UserModel(name="Alice", age=30), "extra": "data"}

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/nested")
        assert resp.status_code == 200
        data = resp.json()
        assert data["user"] == {"name": "Alice", "age": 30}
        assert data["extra"] == "data"

    @pytest.mark.anyio
    async def test_list_of_pydantic_models(self, client_for):
        """Handler returns list of Pydantic models -> all serialized."""
        router = Router()

        @router.get("/api/users")
        async def users(req):
            return [
                UserModel(name="Alice", age=30),
                UserModel(name="Bob", age=25),
            ]

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/users")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0] == {"name": "Alice", "age": 30}
        assert data[1] == {"name": "Bob", "age": 25}

    @pytest.mark.anyio
    async def test_deeply_nested_pydantic(self, client_for):
        """Dict with nested dict containing Pydantic model -> recursively serialized."""
        router = Router()

        @router.get("/api/deep")
        async def deep(req):
            return {
                "result": {
                    "user": UserModel(name="Carol", age=40),
                    "address": AddressModel(city="Berlin", zip="10115"),
                },
            }

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/deep")
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"]["user"] == {"name": "Carol", "age": 40}
        assert data["result"]["address"] == {"city": "Berlin", "zip": "10115"}

    @pytest.mark.anyio
    async def test_list_in_dict_with_pydantic(self, client_for):
        """Dict containing a list of Pydantic models -> serialized."""
        router = Router()

        @router.get("/api/team")
        async def team(req):
            return {
                "team": [
                    UserModel(name="Alice", age=30),
                    UserModel(name="Bob", age=25),
                ],
                "count": 2,
            }

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/team")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert data["team"][0]["name"] == "Alice"
        assert data["team"][1]["name"] == "Bob"

    @pytest.mark.anyio
    async def test_plain_dict_unchanged(self, client_for):
        """Dict without Pydantic models passes through unchanged."""
        router = Router()

        @router.get("/api/plain")
        async def plain(req):
            return {"key": "value", "num": 42}

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/plain")
        assert resp.status_code == 200
        assert resp.json() == {"key": "value", "num": 42}
