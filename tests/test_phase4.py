"""Tests for Phase 4: Auth module.

Covers:
- 4.1 JWT token operations (create, verify, expiry, tampering)
- 4.2 Password hashing (hash, verify correct/wrong)
- 4.3 User storage (JSONFileUserStore CRUD, errors)
- 4.4 Auth dependencies (get_current_user, require_role with DI)
- 4.5 CSRF double-submit middleware
- 4.6 Session cookie helpers
- 4.7 Rate limiting decorator
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient

from wesktop.asgi import (
    HTTPError,
    JSONResponse,
    Router,
    create_app,
)
from wesktop.auth import (
    CSRFMiddleware,
    JSONFileUserStore,
    clear_session_cookies,
    create_token,
    get_current_user,
    hash_password,
    rate_limit,
    require_role,
    set_session_cookies,
    verify_password,
    verify_token,
)


# ---------------------------------------------------------------------------
# 4.1 JWT token operations
# ---------------------------------------------------------------------------


class TestJWTTokens:
    """create_token and verify_token."""

    def test_create_and_verify(self):
        secret = "test-secret-key-that-is-at-least-thirty-two-bytes-long"
        token = create_token("alice", "admin", secret)
        claims = verify_token(token, secret)
        assert claims is not None
        assert claims["sub"] == "alice"
        assert claims["role"] == "admin"
        assert "iat" in claims
        assert "exp" in claims

    def test_expired_token_returns_none(self):
        secret = "test-secret-key-that-is-at-least-thirty-two-bytes-long"
        token = create_token("alice", "admin", secret, expires_hours=-1)
        assert verify_token(token, secret) is None

    def test_tampered_token_returns_none(self):
        secret = "test-secret-key-that-is-at-least-thirty-two-bytes-long"
        token = create_token("alice", "admin", secret)
        # Flip a character in the signature
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        assert verify_token(tampered, secret) is None

    def test_wrong_secret_returns_none(self):
        token = create_token("alice", "admin", "test-secret-key-that-is-at-least-thirty-two-bytes-long")
        assert verify_token(token, "wrong-secret-key-that-is-at-least-thirty-two-bytes-long") is None

    def test_garbage_token_returns_none(self):
        assert verify_token("not-a-jwt", "test-secret-key-that-is-at-least-thirty-two-bytes-long") is None

    def test_custom_expiry(self):
        secret = "test-secret-key-that-is-at-least-thirty-two-bytes-long"
        token = create_token("alice", "admin", secret, expires_hours=1)
        claims = verify_token(token, secret)
        assert claims is not None
        # exp should be roughly 1 hour from now
        exp = datetime.fromtimestamp(claims["exp"], tz=UTC)
        now = datetime.now(UTC)
        delta = exp - now
        assert timedelta(minutes=55) < delta < timedelta(minutes=65)

    def test_default_expiry_is_720_hours(self):
        secret = "test-secret-key-that-is-at-least-thirty-two-bytes-long"
        token = create_token("alice", "admin", secret)
        claims = verify_token(token, secret)
        assert claims is not None
        exp = datetime.fromtimestamp(claims["exp"], tz=UTC)
        iat = datetime.fromtimestamp(claims["iat"], tz=UTC)
        delta = exp - iat
        assert delta == timedelta(hours=720)


# ---------------------------------------------------------------------------
# 4.2 Password hashing
# ---------------------------------------------------------------------------


class TestPasswordHashing:
    """hash_password and verify_password."""

    def test_hash_and_verify_correct(self):
        hashed = hash_password("my-password")
        assert verify_password("my-password", hashed) is True

    def test_verify_wrong_password(self):
        hashed = hash_password("correct-password")
        assert verify_password("wrong-password", hashed) is False

    def test_different_hashes_for_same_password(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        # bcrypt salts differ, so hashes differ
        assert h1 != h2
        # But both verify
        assert verify_password("same", h1) is True
        assert verify_password("same", h2) is True

    def test_hash_returns_string(self):
        hashed = hash_password("test")
        assert isinstance(hashed, str)
        assert hashed.startswith("$2")


# ---------------------------------------------------------------------------
# 4.3 User storage interface
# ---------------------------------------------------------------------------


class TestJSONFileUserStore:
    """JSONFileUserStore CRUD operations."""

    def test_create_and_find_user(self, tmp_path):
        store = JSONFileUserStore(tmp_path / "users.json")
        user = store.create_user("alice", "pass123", "admin")
        assert user["username"] == "alice"
        assert user["role"] == "admin"
        assert "password_hash" in user
        assert "created_at" in user

        found = store.find_user("alice")
        assert found is not None
        assert found["username"] == "alice"

    def test_find_user_not_found(self, tmp_path):
        store = JSONFileUserStore(tmp_path / "users.json")
        assert store.find_user("nobody") is None

    def test_create_duplicate_raises_value_error(self, tmp_path):
        store = JSONFileUserStore(tmp_path / "users.json")
        store.create_user("alice", "pass123", "admin")
        with pytest.raises(ValueError, match="already exists"):
            store.create_user("alice", "pass456", "user")

    def test_delete_user(self, tmp_path):
        store = JSONFileUserStore(tmp_path / "users.json")
        store.create_user("alice", "pass123", "admin")
        store.delete_user("alice")
        assert store.find_user("alice") is None

    def test_delete_nonexistent_raises_lookup_error(self, tmp_path):
        store = JSONFileUserStore(tmp_path / "users.json")
        with pytest.raises(LookupError, match="not found"):
            store.delete_user("nobody")

    def test_load_users_empty_file(self, tmp_path):
        store = JSONFileUserStore(tmp_path / "users.json")
        assert store.load_users() == []

    def test_password_is_hashed_not_plain(self, tmp_path):
        store = JSONFileUserStore(tmp_path / "users.json")
        store.create_user("alice", "secret", "admin")
        user = store.find_user("alice")
        assert user["password_hash"] != "secret"
        assert verify_password("secret", user["password_hash"])

    def test_json_file_written(self, tmp_path):
        path = tmp_path / "users.json"
        store = JSONFileUserStore(path)
        store.create_user("alice", "pass", "admin")
        assert path.is_file()
        data = json.loads(path.read_text())
        assert len(data) == 1
        assert data[0]["username"] == "alice"

    def test_multiple_users(self, tmp_path):
        store = JSONFileUserStore(tmp_path / "users.json")
        store.create_user("alice", "pass1", "admin")
        store.create_user("bob", "pass2", "user")
        users = store.load_users()
        assert len(users) == 2
        names = {u["username"] for u in users}
        assert names == {"alice", "bob"}

    def test_created_at_is_iso_timestamp(self, tmp_path):
        store = JSONFileUserStore(tmp_path / "users.json")
        store.create_user("alice", "pass", "admin")
        user = store.find_user("alice")
        # Should parse as ISO datetime
        dt = datetime.fromisoformat(user["created_at"])
        assert dt.year >= 2024

    def test_nested_directory_creation(self, tmp_path):
        path = tmp_path / "deep" / "nested" / "users.json"
        store = JSONFileUserStore(path)
        store.create_user("alice", "pass", "admin")
        assert path.is_file()


# ---------------------------------------------------------------------------
# 4.4 Auth dependencies
# ---------------------------------------------------------------------------


def _make_auth_app(handler, *, deps=None):
    """Build a test app with jwt_secret in lifespan state."""

    @asynccontextmanager
    async def lifespan(app):
        yield {"config": {"jwt_secret": "test-secret-key-that-is-at-least-thirty-two-bytes-long"}}

    router = Router()
    router.add_route("GET", "/protected", handler, deps=deps or {})
    return create_app(router, lifespan=lifespan)


async def _start_lifespan(app):
    """Run lifespan startup and return a shutdown trigger."""
    startup_done = asyncio.Event()
    shutdown_trigger = asyncio.Event()

    async def ls_receive():
        if not startup_done.is_set():
            return {"type": "lifespan.startup"}
        await shutdown_trigger.wait()
        return {"type": "lifespan.shutdown"}

    async def ls_send(msg):
        if msg["type"] == "lifespan.startup.complete":
            startup_done.set()

    task = asyncio.create_task(app({"type": "lifespan"}, ls_receive, ls_send))
    await startup_done.wait()
    return task, shutdown_trigger


class TestGetCurrentUser:
    """get_current_user extracts JWT from 3 sources."""

    @pytest.mark.anyio
    async def test_bearer_header(self):
        async def handler(request, user=None):
            return JSONResponse({"sub": user["sub"], "role": user["role"]})

        app = _make_auth_app(handler, deps={"user": get_current_user})
        task, shutdown = await _start_lifespan(app)
        try:
            token = create_token("alice", "admin", "test-secret-key-that-is-at-least-thirty-two-bytes-long")
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test",
            ) as client:
                resp = await client.get(
                    "/protected",
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 200
            assert resp.json()["sub"] == "alice"
            assert resp.json()["role"] == "admin"
        finally:
            shutdown.set()
            await task

    @pytest.mark.anyio
    async def test_session_cookie(self):
        async def handler(request, user=None):
            return JSONResponse({"sub": user["sub"]})

        app = _make_auth_app(handler, deps={"user": get_current_user})
        task, shutdown = await _start_lifespan(app)
        try:
            token = create_token("bob", "user", "test-secret-key-that-is-at-least-thirty-two-bytes-long")
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test",
            ) as client:
                resp = await client.get(
                    "/protected",
                    cookies={"session": token},
                )
            assert resp.status_code == 200
            assert resp.json()["sub"] == "bob"
        finally:
            shutdown.set()
            await task

    @pytest.mark.anyio
    async def test_query_param(self):
        async def handler(request, user=None):
            return JSONResponse({"sub": user["sub"]})

        app = _make_auth_app(handler, deps={"user": get_current_user})
        task, shutdown = await _start_lifespan(app)
        try:
            token = create_token("carol", "viewer", "test-secret-key-that-is-at-least-thirty-two-bytes-long")
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test",
            ) as client:
                resp = await client.get(f"/protected?token={token}")
            assert resp.status_code == 200
            assert resp.json()["sub"] == "carol"
        finally:
            shutdown.set()
            await task

    @pytest.mark.anyio
    async def test_no_token_returns_401(self):
        async def handler(request, user=None):
            return JSONResponse({"ok": True})

        app = _make_auth_app(handler, deps={"user": get_current_user})
        task, shutdown = await _start_lifespan(app)
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test",
            ) as client:
                resp = await client.get("/protected")
            assert resp.status_code == 401
            assert resp.json()["detail"] == "Not authenticated"
        finally:
            shutdown.set()
            await task

    @pytest.mark.anyio
    async def test_invalid_token_returns_401(self):
        async def handler(request, user=None):
            return JSONResponse({"ok": True})

        app = _make_auth_app(handler, deps={"user": get_current_user})
        task, shutdown = await _start_lifespan(app)
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test",
            ) as client:
                resp = await client.get(
                    "/protected",
                    headers={"Authorization": "Bearer invalid-token"},
                )
            assert resp.status_code == 401
            assert resp.json()["detail"] == "Invalid or expired token"
        finally:
            shutdown.set()
            await task


class TestRequireRole:
    """require_role(role) factory checks claims["role"]."""

    @pytest.mark.anyio
    async def test_correct_role_passes(self):
        async def handler(request, user=None):
            return JSONResponse({"sub": user["sub"]})

        app = _make_auth_app(handler, deps={"user": require_role("admin")})
        task, shutdown = await _start_lifespan(app)
        try:
            token = create_token("alice", "admin", "test-secret-key-that-is-at-least-thirty-two-bytes-long")
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test",
            ) as client:
                resp = await client.get(
                    "/protected",
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 200
            assert resp.json()["sub"] == "alice"
        finally:
            shutdown.set()
            await task

    @pytest.mark.anyio
    async def test_wrong_role_returns_403(self):
        async def handler(request, user=None):
            return JSONResponse({"ok": True})

        app = _make_auth_app(handler, deps={"user": require_role("admin")})
        task, shutdown = await _start_lifespan(app)
        try:
            token = create_token("bob", "viewer", "test-secret-key-that-is-at-least-thirty-two-bytes-long")
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test",
            ) as client:
                resp = await client.get(
                    "/protected",
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 403
            assert "admin" in resp.json()["detail"]
        finally:
            shutdown.set()
            await task

    @pytest.mark.anyio
    async def test_no_token_returns_401(self):
        async def handler(request, user=None):
            return JSONResponse({"ok": True})

        app = _make_auth_app(handler, deps={"user": require_role("admin")})
        task, shutdown = await _start_lifespan(app)
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test",
            ) as client:
                resp = await client.get("/protected")
            assert resp.status_code == 401
        finally:
            shutdown.set()
            await task


# ---------------------------------------------------------------------------
# 4.5 CSRF double-submit middleware
# ---------------------------------------------------------------------------


class TestCSRFMiddleware:
    """CSRFMiddleware validates double-submit cookie pattern."""

    @pytest.mark.anyio
    async def test_get_always_passes(self, client_for):
        router = Router()

        @router.get("/data")
        async def data(request):
            return JSONResponse({"ok": True})

        app = create_app(router, middleware=[CSRFMiddleware])
        async with client_for(app) as client:
            resp = await client.get("/data")
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_post_without_csrf_returns_403(self, client_for):
        router = Router()

        @router.post("/submit")
        async def submit(request):
            return JSONResponse({"ok": True})

        app = create_app(router, middleware=[CSRFMiddleware])
        async with client_for(app) as client:
            resp = await client.post("/submit", json={"data": "test"})
        assert resp.status_code == 403
        assert "CSRF" in resp.json()["detail"]

    @pytest.mark.anyio
    async def test_post_with_matching_csrf_passes(self, client_for):
        csrf_val = "my-csrf-token-value"
        router = Router()

        @router.post("/submit")
        async def submit(request):
            return JSONResponse({"ok": True})

        app = create_app(router, middleware=[CSRFMiddleware])
        async with client_for(app) as client:
            resp = await client.post(
                "/submit",
                json={"data": "test"},
                headers={"X-CSRF-Token": csrf_val},
                cookies={"csrf_token": csrf_val},
            )
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_post_with_mismatched_csrf_returns_403(self, client_for):
        router = Router()

        @router.post("/submit")
        async def submit(request):
            return JSONResponse({"ok": True})

        app = create_app(router, middleware=[CSRFMiddleware])
        async with client_for(app) as client:
            resp = await client.post(
                "/submit",
                json={"data": "test"},
                headers={"X-CSRF-Token": "value-a"},
                cookies={"csrf_token": "value-b"},
            )
        assert resp.status_code == 403
        assert "mismatch" in resp.json()["detail"]

    @pytest.mark.anyio
    async def test_bearer_token_bypasses_csrf(self, client_for):
        router = Router()

        @router.post("/api/data")
        async def api_data(request):
            return JSONResponse({"ok": True})

        app = create_app(router, middleware=[CSRFMiddleware])
        # A real JWT has 3 dot-separated segments
        fake_jwt = "header.payload.signature"
        async with client_for(app) as client:
            resp = await client.post(
                "/api/data",
                json={"data": "test"},
                headers={"Authorization": f"Bearer {fake_jwt}"},
            )
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_exempt_paths(self, client_for):
        router = Router()

        @router.post("/auth/login")
        async def login(request):
            return JSONResponse({"ok": True})

        middleware = [lambda app: CSRFMiddleware(app, exempt_paths=["/auth/login"])]
        app = create_app(router, middleware=middleware)
        async with client_for(app) as client:
            resp = await client.post("/auth/login", json={"user": "test"})
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_disabled_flag(self, client_for):
        router = Router()

        @router.post("/submit")
        async def submit(request):
            return JSONResponse({"ok": True})

        middleware = [lambda app: CSRFMiddleware(app, disabled=True)]
        app = create_app(router, middleware=middleware)
        async with client_for(app) as client:
            resp = await client.post("/submit", json={"data": "test"})
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_head_and_options_exempt(self, client_for):
        router = Router()

        @router.get("/data")
        async def data(request):
            return JSONResponse({"ok": True})

        app = create_app(router, middleware=[CSRFMiddleware])
        async with client_for(app) as client:
            resp = await client.head("/data")
            # HEAD may get 404 since only GET is registered, but CSRF
            # should not be the blocker -- the status should not be 403
            assert resp.status_code != 403

            resp = await client.options("/data")
            assert resp.status_code != 403

    @pytest.mark.anyio
    async def test_websocket_passes_through(self):
        """CSRF middleware ignores websocket scope."""
        router = Router()

        @router.ws("/ws/test")
        async def ws_handler(ws):
            await ws.accept()
            await ws.send_text("hello")
            await ws.close()

        app = create_app(router, middleware=[CSRFMiddleware])

        sent = []
        step = 0

        async def fake_receive():
            nonlocal step
            step += 1
            if step == 1:
                return {"type": "websocket.connect"}
            await asyncio.sleep(100)

        async def fake_send(msg):
            sent.append(msg)

        scope = {
            "type": "websocket",
            "path": "/ws/test",
            "headers": [],
            "query_string": b"",
        }
        await app(scope, fake_receive, fake_send)
        assert sent[0]["type"] == "websocket.accept"


# ---------------------------------------------------------------------------
# 4.6 Session cookie helpers
# ---------------------------------------------------------------------------


class TestSessionCookieHelpers:
    """set_session_cookies and clear_session_cookies."""

    def test_set_session_cookies(self):
        cookies = set_session_cookies("jwt-token-value", "csrf-value")
        assert len(cookies) == 2
        # Session cookie: httponly, samesite=lax
        session_cookie = cookies[0]
        assert "session=jwt-token-value" in session_cookie
        assert "HttpOnly" in session_cookie
        assert "SameSite=lax" in session_cookie
        # CSRF cookie: js-readable (no httponly)
        csrf_cookie = cookies[1]
        assert "csrf_token=csrf-value" in csrf_cookie
        assert "HttpOnly" not in csrf_cookie
        assert "SameSite=lax" in csrf_cookie

    def test_clear_session_cookies(self):
        cookies = clear_session_cookies()
        assert len(cookies) == 2
        for cookie in cookies:
            assert "Max-Age=0" in cookie
        # Check both cookie names are cleared
        names = [c.split("=")[0] for c in cookies]
        assert "session" in names
        assert "csrf_token" in names

    @pytest.mark.anyio
    async def test_cookies_set_on_response(self, client_for):
        """Cookies from set_session_cookies work with JSONResponse."""
        router = Router()

        @router.post("/login")
        async def login(request):
            cookies = set_session_cookies("my-jwt", "my-csrf")
            return JSONResponse({"ok": True}, cookies=cookies)

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.post("/login", json={})
        assert resp.status_code == 200
        # Check Set-Cookie headers
        set_cookies = resp.headers.get_list("set-cookie")
        assert len(set_cookies) == 2
        session_found = any("session=my-jwt" in c for c in set_cookies)
        csrf_found = any("csrf_token=my-csrf" in c for c in set_cookies)
        assert session_found
        assert csrf_found


# ---------------------------------------------------------------------------
# 4.7 Rate limiting
# ---------------------------------------------------------------------------


class TestRateLimiting:
    """@rate_limit decorator with token bucket."""

    @pytest.mark.anyio
    async def test_within_limit_passes(self, client_for):
        router = Router()

        @router.get("/search")
        @rate_limit("5/minute")
        async def search(request):
            return JSONResponse({"ok": True})

        app = create_app(router)
        async with client_for(app) as client:
            for _ in range(5):
                resp = await client.get("/search")
                assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_exceeding_limit_returns_429(self, client_for):
        router = Router()

        @router.get("/search")
        @rate_limit("3/minute")
        async def search(request):
            return JSONResponse({"ok": True})

        app = create_app(router)
        async with client_for(app) as client:
            for _ in range(3):
                resp = await client.get("/search")
                assert resp.status_code == 200
            # 4th request should be rate limited
            resp = await client.get("/search")
            assert resp.status_code == 429
            assert "Rate limit" in resp.json()["detail"]

    @pytest.mark.anyio
    async def test_unlimited_endpoint_unaffected(self, client_for):
        router = Router()

        @router.get("/unlimited")
        async def unlimited(request):
            return JSONResponse({"ok": True})

        app = create_app(router)
        async with client_for(app) as client:
            for _ in range(20):
                resp = await client.get("/unlimited")
                assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_custom_key_func(self, client_for):
        router = Router()

        @router.get("/api")
        @rate_limit("2/minute", key_func=lambda req: "global")
        async def api(request):
            return JSONResponse({"ok": True})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/api")
            assert resp.status_code == 200
            resp = await client.get("/api")
            assert resp.status_code == 200
            # 3rd request with same global key hits limit
            resp = await client.get("/api")
            assert resp.status_code == 429

    def test_invalid_rate_format_raises(self):
        with pytest.raises(ValueError, match="Invalid rate format"):
            rate_limit("invalid")

    def test_valid_rate_formats(self):
        # These should not raise
        rate_limit("10/second")
        rate_limit("100/minute")
        rate_limit("1000/hour")

    @pytest.mark.anyio
    async def test_per_second_rate(self, client_for):
        router = Router()

        @router.get("/fast")
        @rate_limit("2/second")
        async def fast(request):
            return JSONResponse({"ok": True})

        app = create_app(router)
        async with client_for(app) as client:
            resp = await client.get("/fast")
            assert resp.status_code == 200
            resp = await client.get("/fast")
            assert resp.status_code == 200
            # 3rd immediate request should fail
            resp = await client.get("/fast")
            assert resp.status_code == 429


# ---------------------------------------------------------------------------
# Integration: auth deps with DI in create_app
# ---------------------------------------------------------------------------


class TestAuthDIIntegration:
    """Auth dependencies wired via DI into create_app routes."""

    @pytest.mark.anyio
    async def test_protected_route_with_di(self):
        """Full integration: lifespan state + DI + get_current_user."""

        @asynccontextmanager
        async def lifespan(app):
            yield {"config": {"jwt_secret": "test-secret-key-that-is-at-least-thirty-two-bytes-long"}}

        router = Router()

        @router.get("/me", deps={"user": get_current_user})
        async def me(request, user=None):
            return JSONResponse({"username": user["sub"], "role": user["role"]})

        app = create_app(router, lifespan=lifespan)
        task, shutdown = await _start_lifespan(app)
        try:
            token = create_token("alice", "admin", "test-secret-key-that-is-at-least-thirty-two-bytes-long")
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test",
            ) as client:
                resp = await client.get(
                    "/me",
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 200
            assert resp.json() == {"username": "alice", "role": "admin"}
        finally:
            shutdown.set()
            await task

    @pytest.mark.anyio
    async def test_require_role_with_di(self):
        """require_role factory works as a DI dep."""

        @asynccontextmanager
        async def lifespan(app):
            yield {"config": {"jwt_secret": "test-secret-key-that-is-at-least-thirty-two-bytes-long"}}

        router = Router()

        @router.get("/admin", deps={"user": require_role("admin")})
        async def admin_only(request, user=None):
            return JSONResponse({"admin": user["sub"]})

        app = create_app(router, lifespan=lifespan)
        task, shutdown = await _start_lifespan(app)
        try:
            admin_token = create_token("alice", "admin", "test-secret-key-that-is-at-least-thirty-two-bytes-long")
            user_token = create_token("bob", "viewer", "test-secret-key-that-is-at-least-thirty-two-bytes-long")

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test",
            ) as client:
                # Admin passes
                resp = await client.get(
                    "/admin",
                    headers={"Authorization": f"Bearer {admin_token}"},
                )
                assert resp.status_code == 200

                # Non-admin gets 403
                resp = await client.get(
                    "/admin",
                    headers={"Authorization": f"Bearer {user_token}"},
                )
                assert resp.status_code == 403
        finally:
            shutdown.set()
            await task
