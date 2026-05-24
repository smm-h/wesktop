"""Authentication module: JWT tokens, password hashing, user storage, CSRF, rate limiting.

Pure functions and DI-compatible factories with no framework-specific dependencies
beyond wesktop's own asgi types. Keeps auth logic testable and reusable.
"""

from __future__ import annotations

import json
import re
import secrets
import time
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any, Callable

import bcrypt
import jwt

from wesktop.asgi import HTTPError, send_error, set_cookie, delete_cookie

# ---------------------------------------------------------------------------
# 4.1 JWT token operations
# ---------------------------------------------------------------------------


def create_token(
    username: str,
    role: str,
    secret: str,
    expires_hours: int = 720,
) -> str:
    """Create a signed JWT with sub, role, exp, and iat claims (HS256)."""
    now = datetime.now(UTC)
    payload = {
        "sub": username,
        "role": role,
        "iat": now,
        "exp": now + timedelta(hours=expires_hours),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def verify_token(token: str, secret: str) -> dict[str, Any] | None:
    """Decode and validate a JWT. Returns claims dict or None on any error."""
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except (jwt.InvalidTokenError, jwt.ExpiredSignatureError, Exception):
        return None


# ---------------------------------------------------------------------------
# 4.2 Password hashing
# ---------------------------------------------------------------------------


def hash_password(plain: str) -> str:
    """Hash a plaintext password with bcrypt."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Check a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ---------------------------------------------------------------------------
# 4.3 User storage interface
# ---------------------------------------------------------------------------


class UserStore:
    """Abstract user storage interface."""

    def load_users(self) -> list[dict[str, str]]:
        raise NotImplementedError

    def save_users(self, users: list[dict[str, str]]) -> None:
        raise NotImplementedError

    def find_user(self, username: str) -> dict[str, str] | None:
        for user in self.load_users():
            if user["username"] == username:
                return user
        return None

    def create_user(
        self, username: str, password: str, role: str,
    ) -> dict[str, str]:
        """Create a new user. Raises ValueError if username already exists."""
        users = self.load_users()
        for u in users:
            if u["username"] == username:
                raise ValueError(f"User '{username}' already exists")
        user = {
            "username": username,
            "password_hash": hash_password(password),
            "role": role,
            "created_at": datetime.now(UTC).isoformat(),
        }
        users.append(user)
        self.save_users(users)
        return user

    def delete_user(self, username: str) -> None:
        """Delete a user by username. Raises LookupError if not found."""
        users = self.load_users()
        for i, u in enumerate(users):
            if u["username"] == username:
                users.pop(i)
                self.save_users(users)
                return
        raise LookupError(f"User '{username}' not found")


class JSONFileUserStore(UserStore):
    """User storage backed by a JSON file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load_users(self) -> list[dict[str, str]]:
        if not self.path.is_file():
            return []
        return json.loads(self.path.read_text())

    def save_users(self, users: list[dict[str, str]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(users, indent=2) + "\n")


# ---------------------------------------------------------------------------
# 4.4 Auth dependencies (DI-compatible)
# ---------------------------------------------------------------------------


def get_current_user(request: Any) -> dict[str, Any]:
    """Extract and validate JWT from Authorization header, session cookie, or query param.

    Token resolution order:
    1. Authorization: Bearer <token> header
    2. session cookie
    3. ?token= query parameter

    Reads the JWT secret from request.state["config"]["jwt_secret"].
    Returns decoded claims dict. Raises HTTPError(401) on failure.
    """
    token: str | None = None

    # 1. Bearer header
    auth_header = request.header("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]

    # 2. Session cookie
    if not token:
        token = request.cookie("session") or None

    # 3. Query parameter
    if not token:
        token = request.query_params.get("token") or None

    if not token:
        raise HTTPError(401, "Not authenticated")

    config = request.state["config"]
    jwt_secret = config["jwt_secret"]
    claims = verify_token(token, jwt_secret)
    if not claims:
        raise HTTPError(401, "Invalid or expired token")

    return claims


def require_role(role: str) -> Callable:
    """Return a DI factory that checks the current user has the given role.

    Usage: @router.get("/admin", deps={"user": require_role("admin")})
    """
    def dep(request: Any) -> dict[str, Any]:
        user = get_current_user(request)
        if user.get("role") != role:
            raise HTTPError(403, f"Role '{role}' required")
        return user
    return dep


# ---------------------------------------------------------------------------
# 4.5 CSRF double-submit middleware (pure ASGI)
# ---------------------------------------------------------------------------

# Methods that do not change state -- exempt from CSRF checks.
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _get_asgi_header(
    headers: list[tuple[bytes, bytes]], name: bytes,
) -> bytes:
    """Return the first header value matching *name* (lowercase), or b""."""
    for hdr_name, hdr_value in headers:
        if hdr_name == name:
            return hdr_value
    return b""


def _get_asgi_cookie(
    headers: list[tuple[bytes, bytes]], cookie_name: str,
) -> str:
    """Parse the Cookie header and return a single cookie value, or ""."""
    raw = _get_asgi_header(headers, b"cookie")
    if not raw:
        return ""
    sc: SimpleCookie = SimpleCookie()
    sc.load(raw.decode("latin-1"))
    morsel = sc.get(cookie_name)
    return morsel.value if morsel else ""


class CSRFMiddleware:
    """Double-submit cookie CSRF protection (pure ASGI).

    For state-changing requests (POST, PUT, PATCH, DELETE) that aren't
    exempt, validates that:
      1. A ``csrf_token`` cookie is present.
      2. An ``X-CSRF-Token`` header is present.
      3. The two values match.

    Constructor args:
      app: inner ASGI application
      exempt_paths: list of path prefixes to skip CSRF checks
      disabled: bypass all checks (for testing)
    """

    def __init__(
        self,
        app: Any,
        *,
        exempt_paths: list[str] | None = None,
        disabled: bool = False,
    ) -> None:
        self.app = app
        self.exempt_paths = tuple(exempt_paths or [])
        self.disabled = disabled

    async def __call__(
        self, scope: dict[str, Any], receive: Any, send: Any,
    ) -> None:
        # Only inspect HTTP requests; let websocket/lifespan pass through.
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if self.disabled:
            await self.app(scope, receive, send)
            return

        headers: list[tuple[bytes, bytes]] = scope["headers"]
        method: str = scope["method"]
        path: str = scope["path"]

        # Safe methods are always exempt.
        if method in _SAFE_METHODS:
            await self.app(scope, receive, send)
            return

        # Bearer token callers are not vulnerable to CSRF (cookie-only attack).
        # Structural check: a real JWT has exactly 3 dot-separated segments.
        auth_header = _get_asgi_header(headers, b"authorization")
        if auth_header.startswith(b"Bearer "):
            token_bytes = auth_header[7:]
            parts = token_bytes.split(b".")
            if len(parts) == 3 and all(parts):
                await self.app(scope, receive, send)
                return

        # Configurable exempt paths.
        if any(path.startswith(prefix) for prefix in self.exempt_paths):
            await self.app(scope, receive, send)
            return

        # Validate double-submit: cookie value must match header value.
        cookie_token = _get_asgi_cookie(headers, "csrf_token")
        header_token = _get_asgi_header(
            headers, b"x-csrf-token",
        ).decode("latin-1")

        if not cookie_token or not header_token:
            await send_error(send, 403, "Missing CSRF token")
            return

        if not secrets.compare_digest(cookie_token, header_token):
            await send_error(send, 403, "CSRF token mismatch")
            return

        await self.app(scope, receive, send)


# ---------------------------------------------------------------------------
# 4.6 Session cookie helpers
# ---------------------------------------------------------------------------


def set_session_cookies(token: str, csrf_token: str) -> list[str]:
    """Build Set-Cookie header strings for session and CSRF cookies.

    Returns a list of two Set-Cookie strings:
    - session: httponly, samesite=lax (not readable by JS)
    - csrf_token: js-readable (no httponly), samesite=lax
    """
    return [
        set_cookie("session", token, httponly=True, samesite="lax"),
        set_cookie("csrf_token", csrf_token, httponly=False, samesite="lax"),
    ]


def clear_session_cookies() -> list[str]:
    """Build Set-Cookie header strings that clear session and CSRF cookies."""
    return [
        delete_cookie("session"),
        delete_cookie("csrf_token"),
    ]


# ---------------------------------------------------------------------------
# 4.7 Rate limiting
# ---------------------------------------------------------------------------

# Pattern: "N/unit" where unit is second, minute, or hour
_RATE_PATTERN = re.compile(r"^(\d+)/(second|minute|hour)$")

_UNIT_SECONDS = {
    "second": 1,
    "minute": 60,
    "hour": 3600,
}


def rate_limit(
    rate: str,
    key_func: Callable | None = None,
) -> Callable:
    """Decorator for per-client rate limiting using a token bucket.

    Usage:
        @router.get("/api/search")
        @rate_limit("5/minute")
        async def search(request):
            ...

    Args:
        rate: Rate string like "5/minute", "10/second", "100/hour".
        key_func: Optional callable(request) -> str for custom bucket keys.
                  Defaults to client IP from ASGI scope.
    """
    match = _RATE_PATTERN.match(rate)
    if not match:
        raise ValueError(
            f"Invalid rate format: {rate!r}. Expected 'N/second', 'N/minute', or 'N/hour'."
        )
    max_tokens = int(match.group(1))
    window_seconds = _UNIT_SECONDS[match.group(2)]
    refill_rate = max_tokens / window_seconds  # tokens per second

    # In-memory token bucket: key -> (tokens_remaining, last_refill_time)
    buckets: dict[str, tuple[float, float]] = {}

    def decorator(fn: Callable) -> Callable:
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Extract request from first positional arg
            request = args[0] if args else None
            if request is None:
                return await fn(*args, **kwargs)

            # Derive client key
            if key_func is not None:
                client_key = key_func(request)
            else:
                client = request.scope.get("client")
                client_key = client[0] if client else "unknown"

            now = time.monotonic()

            # Refill tokens
            if client_key in buckets:
                tokens, last_refill = buckets[client_key]
                elapsed = now - last_refill
                tokens = min(max_tokens, tokens + elapsed * refill_rate)
            else:
                tokens = float(max_tokens)
                last_refill = now

            # Check limit
            if tokens < 1.0:
                raise HTTPError(429, "Rate limit exceeded")

            # Consume one token
            buckets[client_key] = (tokens - 1.0, now)

            return await fn(*args, **kwargs)

        # Preserve function name for debugging
        wrapper.__name__ = getattr(fn, "__name__", "wrapped")
        wrapper.__qualname__ = getattr(fn, "__qualname__", "wrapped")
        return wrapper

    return decorator
