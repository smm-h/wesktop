"""Tests for Phase 1 follow-up fixes.

Covers:
- 1.2: WebSocket.receive_raw() returns raw ASGI message dict
- 1.3: Broadcaster heartbeat_interval yields SSE heartbeat comments
- 1.4: Recursive Pydantic model serialization in handler responses
- 3.1: serve(reload=True) requires foreground=True and invokes watchfiles
"""

from __future__ import annotations

import asyncio
import json
import socket
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from wesktop.asgi import (
    AppConfig,
    JSONResponse,
    Router,
    WebSocket,
    create_app,
)
from wesktop.server import serve
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


# ---------------------------------------------------------------------------
# 2.1 + 2.2 AppConfig and create_app backward compatibility
# ---------------------------------------------------------------------------


class TestAppConfig:
    @pytest.mark.anyio
    async def test_create_app_no_config(self, client_for):
        """create_app(router) still works without config or kwargs."""
        router = Router()

        @router.get("/api/ping")
        async def ping(req):
            return {"ok": True}

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api/ping")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    @pytest.mark.anyio
    async def test_create_app_with_config(self, client_for):
        """create_app(router, AppConfig(cors_origins=...)) works."""
        router = Router()

        @router.get("/api/ping")
        async def ping(req):
            return {"ok": True}

        cfg = AppConfig(cors_origins=["http://localhost"])
        app = create_app(router, config=cfg)
        async with client_for(app) as client:
            resp = await client.get(
                "/api/ping",
                headers={"origin": "http://localhost"},
            )
        assert resp.status_code == 200
        # CORS header is present when Origin matches an allowed origin
        assert resp.headers.get("access-control-allow-origin") == "http://localhost"

    @pytest.mark.anyio
    async def test_create_app_kwargs_still_work(self, client_for):
        """create_app(router, cors_origins=...) still works (backward compat)."""
        router = Router()

        @router.get("/api/ping")
        async def ping(req):
            return {"ok": True}

        app = create_app(router, cors_origins=["http://localhost"])
        async with client_for(app) as client:
            resp = await client.get(
                "/api/ping",
                headers={"origin": "http://localhost"},
            )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "http://localhost"

    @pytest.mark.anyio
    async def test_kwargs_override_config(self, client_for):
        """Keyword arguments override matching config fields."""
        router = Router()

        @router.get("/api/ping")
        async def ping(req):
            return {"ok": True}

        # Config says no request_id, kwarg overrides to True
        cfg = AppConfig(request_id=False)
        app = create_app(router, config=cfg, request_id=True)
        async with client_for(app) as client:
            resp = await client.get("/api/ping")
        assert resp.status_code == 200
        # RequestIDMiddleware adds x-request-id to the response header
        assert resp.headers.get("x-request-id") is not None

    @pytest.mark.anyio
    async def test_config_request_id_false_no_header(self, client_for):
        """AppConfig(request_id=False) suppresses the x-request-id header."""
        router = Router()

        @router.get("/api/ping")
        async def ping(req):
            return {"ok": True}

        cfg = AppConfig(request_id=False, request_timing=False)
        app = create_app(router, config=cfg)
        async with client_for(app) as client:
            resp = await client.get("/api/ping")
        assert resp.status_code == 200
        assert resp.headers.get("x-request-id") is None

    def test_unknown_kwarg_raises_type_error(self):
        """Passing an unknown keyword argument raises TypeError."""
        router = Router()
        with pytest.raises(TypeError, match="unexpected keyword argument"):
            create_app(router, bogus_param=True)

    def test_appconfig_importable_from_wesktop(self):
        """AppConfig is importable from the top-level wesktop package."""
        from wesktop import AppConfig as AC
        assert AC is AppConfig


# ---------------------------------------------------------------------------
# 3.1 serve(reload=True) -- auto-restart on .py file changes
# ---------------------------------------------------------------------------


class TestServeReload:
    def test_reload_requires_foreground(self):
        """reload=True with foreground=False raises ValueError."""
        with pytest.raises(ValueError, match="reload requires foreground=True"):
            serve(
                "myapp:app",
                foreground=False,
                reload=True,
                host="127.0.0.1",
                port=9999,
            )

    @patch("wesktop.server.ensure_port_available")
    @patch("wesktop.server._resolve_target", return_value="myapp:app")
    def test_reload_calls_run_process(self, mock_resolve, mock_port):
        """reload=True invokes watchfiles.run_process with correct args."""
        mock_port.return_value = 9999
        mock_run = MagicMock(return_value=0)

        with patch.dict(
            "sys.modules",
            {"watchfiles": MagicMock(run_process=mock_run, PythonFilter=MagicMock)},
        ):
            # Re-import so the lazy import inside serve() picks up the mock
            import importlib
            import wesktop.server as srv
            importlib.reload(srv)

            srv.serve(
                "myapp:app",
                foreground=True,
                reload=True,
                host="127.0.0.1",
                port=9999,
            )

        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args
        # First positional arg is the watch path
        assert call_kwargs[0][0] == "."
        # target is _run_server
        assert call_kwargs[1]["target"].__name__ == "_run_server"
        # args pass the resolved target, host, port
        assert call_kwargs[1]["args"] == ("myapp:app", "127.0.0.1", 9999)

    @patch("wesktop.server.Granian")
    def test_reload_false_does_not_import_watchfiles(self, mock_granian):
        """reload=False (default) does not touch watchfiles."""
        mock_instance = MagicMock()
        mock_granian.return_value = mock_instance

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            free_port = s.getsockname()[1]

        # Should work fine without watchfiles installed
        url = serve("myapp:app", foreground=False, host="127.0.0.1", port=free_port)
        assert url == f"http://127.0.0.1:{free_port}"
        mock_instance.serve.assert_called_once()


# ---------------------------------------------------------------------------
# 4.1 MCP module -- role definitions and server creation
# ---------------------------------------------------------------------------


class TestMCPModule:
    def test_roles_importable(self):
        """ROLES and DEFAULT_ROLE are importable from wesktop.mcp."""
        from wesktop.mcp import ROLES, DEFAULT_ROLE

        assert isinstance(ROLES, dict)
        assert "implementor" in ROLES
        assert "auditor" in ROLES
        assert "reviewer" in ROLES
        assert "deployer" in ROLES
        assert DEFAULT_ROLE == "auditor"

    def test_role_tool_sets(self):
        """Each role has a 'tools' list and a 'level' string."""
        from wesktop.mcp import ROLES

        for name, config in ROLES.items():
            assert "level" in config, f"Role {name} missing 'level'"
            assert "tools" in config, f"Role {name} missing 'tools'"
            assert isinstance(config["tools"], list)
            assert len(config["tools"]) > 0

    def test_implementor_has_write_tools(self):
        """Implementor role includes write_file and edit_file."""
        from wesktop.mcp import ROLES

        impl_tools = ROLES["implementor"]["tools"]
        assert "write_file" in impl_tools
        assert "edit_file" in impl_tools
        assert "git_commit" in impl_tools

    def test_auditor_lacks_write_tools(self):
        """Auditor role does NOT include write_file or edit_file."""
        from wesktop.mcp import ROLES

        aud_tools = ROLES["auditor"]["tools"]
        assert "write_file" not in aud_tools
        assert "edit_file" not in aud_tools
        assert "git_commit" not in aud_tools

    def test_reviewer_has_post_review_comment(self):
        """Reviewer role includes post_review_comment."""
        from wesktop.mcp import ROLES

        rev_tools = ROLES["reviewer"]["tools"]
        assert "post_review_comment" in rev_tools

    def test_deployer_has_pipeline_tools(self):
        """Deployer role includes deployment tools."""
        from wesktop.mcp import ROLES

        dep_tools = ROLES["deployer"]["tools"]
        assert "stage_branch" in dep_tools
        assert "create_prod_pr" in dep_tools
        assert "check_pipeline" in dep_tools

    def test_all_roles_have_ask_user(self):
        """Every role includes the ask_user tool."""
        from wesktop.mcp import ROLES

        for name, config in ROLES.items():
            assert "ask_user" in config["tools"], f"Role {name} missing ask_user"

    def test_create_mcp_server_without_mcp_package(self, monkeypatch):
        """create_mcp_server raises RuntimeError when mcp is not installed."""
        import wesktop.mcp as mcp_mod

        monkeypatch.setattr(mcp_mod, "_MCP_AVAILABLE", False)
        with pytest.raises(RuntimeError, match="mcp.*package.*required"):
            mcp_mod.create_mcp_server()

    def test_register_tools_for_role_filters_correctly(self):
        """register_tools_for_role only registers tools allowed by the role."""
        from types import ModuleType

        from wesktop.mcp import register_tools_for_role

        # Build a fake module with a TOOLS dict.
        mod = ModuleType("fake_tools")
        mod.TOOLS = {
            "read_file": lambda: "read",
            "write_file": lambda: "write",
            "git_commit": lambda: "commit",
        }

        # Build a fake server that tracks add_tool calls.
        registered = {}

        class FakeServer:
            def add_tool(self, fn, *, name):
                registered[name] = fn

        # Auditor should get read_file but not write_file or git_commit.
        result = register_tools_for_role(FakeServer(), "auditor", [mod])
        assert "read_file" in result
        assert "write_file" not in result
        assert "git_commit" not in result
        assert "read_file" in registered
        assert "write_file" not in registered

    def test_register_tools_unknown_role_falls_back_to_default(self):
        """Unknown role falls back to DEFAULT_ROLE (auditor)."""
        from types import ModuleType

        from wesktop.mcp import ROLES, DEFAULT_ROLE, register_tools_for_role

        mod = ModuleType("fake_tools")
        mod.TOOLS = {
            "read_file": lambda: "read",
            "write_file": lambda: "write",
        }

        registered = {}

        class FakeServer:
            def add_tool(self, fn, *, name):
                registered[name] = fn

        result = register_tools_for_role(FakeServer(), "nonexistent_role", [mod])
        # Should behave like the default role
        default_tools = set(ROLES[DEFAULT_ROLE]["tools"])
        for name in result:
            assert name in default_tools

    def test_mcp_exports_from_top_level(self):
        """MCP symbols are importable from the top-level wesktop package."""
        from wesktop import (
            ROLES,
            DEFAULT_ROLE,
            create_mcp_server,
            register_tools_for_role,
        )

        assert ROLES is not None
        assert DEFAULT_ROLE == "auditor"
        assert callable(create_mcp_server)
        assert callable(register_tools_for_role)


# ---------------------------------------------------------------------------
# 4.2 MCP tool modules -- basic import and function signatures
# ---------------------------------------------------------------------------


class TestMCPToolModules:
    def test_filesystem_module_importable(self):
        """Filesystem tool module is importable with expected functions."""
        from wesktop.mcp_tools import filesystem

        assert callable(filesystem.read_file)
        assert callable(filesystem.write_file)
        assert callable(filesystem.edit_file)
        assert callable(filesystem.list_files)
        assert callable(filesystem.search_files)

    def test_git_module_importable(self):
        """Git tool module is importable with expected functions."""
        from wesktop.mcp_tools import git

        assert callable(git.git_status)
        assert callable(git.git_diff)
        assert callable(git.git_commit)
        assert callable(git.git_log)

    def test_testing_module_importable(self):
        """Testing tool module is importable with expected functions."""
        from wesktop.mcp_tools import testing

        assert callable(testing.run_tests)

    def test_deployment_module_importable(self):
        """Deployment tool module is importable with expected functions."""
        from wesktop.mcp_tools import deployment

        assert callable(deployment.stage_branch)
        assert callable(deployment.create_prod_pr)
        assert callable(deployment.check_pipeline)

    def test_review_module_importable(self):
        """Review tool module is importable with expected functions."""
        from wesktop.mcp_tools import review

        assert callable(review.post_review_comment)

    def test_ask_user_module_importable(self):
        """Ask-user tool module is importable with expected functions."""
        from wesktop.mcp_tools import ask_user

        assert callable(ask_user.ask_user)

    def test_filesystem_read_file_nonexistent(self, tmp_path):
        """read_file returns error for nonexistent file."""
        from wesktop.mcp_tools.filesystem import read_file

        result = read_file(str(tmp_path), "nonexistent.txt")
        assert result.startswith("Error:")

    def test_filesystem_write_and_read(self, tmp_path):
        """write_file + read_file round-trip works."""
        from wesktop.mcp_tools.filesystem import read_file, write_file

        result = write_file(str(tmp_path), "test.txt", "hello world")
        assert "Wrote" in result

        content = read_file(str(tmp_path), "test.txt")
        assert content == "hello world"

    def test_filesystem_path_traversal_blocked(self, tmp_path):
        """Path traversal attempts are blocked."""
        from wesktop.mcp_tools.filesystem import read_file

        with pytest.raises(ValueError, match="Path traversal"):
            read_file(str(tmp_path), "../../../etc/passwd")

    def test_filesystem_list_files(self, tmp_path):
        """list_files returns directory listing."""
        from wesktop.mcp_tools.filesystem import list_files, write_file

        write_file(str(tmp_path), "a.txt", "a")
        (tmp_path / "subdir").mkdir()

        result = list_files(str(tmp_path))
        assert "subdir/" in result
        assert "a.txt" in result

    def test_filesystem_edit_file(self, tmp_path):
        """edit_file performs find-and-replace."""
        from wesktop.mcp_tools.filesystem import edit_file, read_file, write_file

        write_file(str(tmp_path), "test.txt", "hello world")
        result = edit_file(str(tmp_path), "test.txt", "hello", "goodbye")
        assert "Replaced" in result

        content = read_file(str(tmp_path), "test.txt")
        assert content == "goodbye world"

    def test_git_status_in_repo(self, tmp_path):
        """git_status works in an initialized repo."""
        import subprocess

        from wesktop.mcp_tools.git import git_status

        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        result = git_status(str(tmp_path))
        assert "Error" not in result
