"""Tests for Phase 6: Pydantic integration.

Covers:
- 6.1 response_model on route decorators (validation, serialization, error handling)
- 6.2 Request.json_as() for Pydantic body parsing
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from wesktop.asgi import (
    HTTPError,
    JSONResponse,
    Router,
    Request,
    create_app,
)


# ---------------------------------------------------------------------------
# Pydantic models for testing
# ---------------------------------------------------------------------------

class UserOut(BaseModel):
    name: str
    age: int


class UserIn(BaseModel):
    name: str
    age: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client(app, base_url: str = "http://test") -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url=base_url,
    )


# ---------------------------------------------------------------------------
# 6.1 response_model on routes
# ---------------------------------------------------------------------------

class TestResponseModel:
    """response_model validates and serializes handler dict returns."""

    @pytest.mark.anyio
    async def test_valid_dict_validated_and_serialized(self):
        """Handler returns valid dict -> response_model validates and serializes."""
        router = Router()

        @router.get("/user", response_model=UserOut)
        async def get_user(req):
            return {"name": "Alice", "age": 30}

        app = create_app(router, request_id=False, request_timing=False)
        async with _client(app) as client:
            resp = await client.get("/user")
            assert resp.status_code == 200
            data = resp.json()
            assert data == {"name": "Alice", "age": 30}

    @pytest.mark.anyio
    async def test_invalid_dict_returns_500(self):
        """Handler returns invalid dict -> 500 with detail."""
        router = Router()

        @router.get("/user", response_model=UserOut)
        async def get_user(req):
            # Missing 'age' field, and extra 'unknown' field
            return {"name": "Alice"}

        app = create_app(router, request_id=False, request_timing=False)
        async with _client(app) as client:
            resp = await client.get("/user")
            assert resp.status_code == 500
            data = resp.json()
            assert "detail" in data
            assert "age" in data["detail"]

    @pytest.mark.anyio
    async def test_wrong_type_returns_500(self):
        """Handler returns dict with wrong field type -> 500."""
        router = Router()

        @router.get("/user", response_model=UserOut)
        async def get_user(req):
            return {"name": "Alice", "age": "not_a_number"}

        app = create_app(router, request_id=False, request_timing=False)
        async with _client(app) as client:
            resp = await client.get("/user")
            # Pydantic may coerce "not_a_number" or reject it; either way,
            # if it rejects, we get 500
            assert resp.status_code == 500

    @pytest.mark.anyio
    async def test_json_response_skips_response_model(self):
        """Handler returns JSONResponse directly -> response_model skipped."""
        router = Router()

        @router.get("/user", response_model=UserOut)
        async def get_user(req):
            # Return JSONResponse directly -- should NOT be validated
            return JSONResponse({"custom": "data"})

        app = create_app(router, request_id=False, request_timing=False)
        async with _client(app) as client:
            resp = await client.get("/user")
            assert resp.status_code == 200
            data = resp.json()
            assert data == {"custom": "data"}

    @pytest.mark.anyio
    async def test_no_response_model_dict_returned_as_is(self):
        """No response_model -> dict returned as-is without validation."""
        router = Router()

        @router.get("/user")
        async def get_user(req):
            return {"name": "Alice", "extra": True}

        app = create_app(router, request_id=False, request_timing=False)
        async with _client(app) as client:
            resp = await client.get("/user")
            assert resp.status_code == 200
            data = resp.json()
            assert data == {"name": "Alice", "extra": True}

    @pytest.mark.anyio
    async def test_response_model_strips_extra_fields(self):
        """response_model serialization only includes model fields."""
        router = Router()

        @router.get("/user", response_model=UserOut)
        async def get_user(req):
            return {"name": "Bob", "age": 25, "secret": "should_be_stripped"}

        app = create_app(router, request_id=False, request_timing=False)
        async with _client(app) as client:
            resp = await client.get("/user")
            assert resp.status_code == 200
            data = resp.json()
            assert data == {"name": "Bob", "age": 25}
            assert "secret" not in data

    @pytest.mark.anyio
    async def test_response_model_on_post(self):
        """response_model works on POST routes too."""
        router = Router()

        @router.post("/user", response_model=UserOut)
        async def create_user(req):
            return {"name": "Charlie", "age": 40}

        app = create_app(router, request_id=False, request_timing=False)
        async with _client(app) as client:
            resp = await client.post("/user")
            assert resp.status_code == 200
            data = resp.json()
            assert data == {"name": "Charlie", "age": 40}


# ---------------------------------------------------------------------------
# 6.2 Request.json_as()
# ---------------------------------------------------------------------------

class TestJsonAs:
    """Request.json_as(model) parses and validates JSON body."""

    @pytest.mark.anyio
    async def test_valid_json_body(self):
        """Valid JSON body -> model instance returned."""
        router = Router()

        @router.post("/user")
        async def create_user(req):
            user = req.json_as(UserIn)
            return {"name": user.name, "age": user.age}

        app = create_app(router, request_id=False, request_timing=False)
        async with _client(app) as client:
            resp = await client.post(
                "/user",
                json={"name": "Alice", "age": 30},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data == {"name": "Alice", "age": 30}

    @pytest.mark.anyio
    async def test_missing_required_field_422(self):
        """Missing required field -> 422 with field name in detail."""
        router = Router()

        @router.post("/user")
        async def create_user(req):
            user = req.json_as(UserIn)
            return {"name": user.name, "age": user.age}

        app = create_app(router, request_id=False, request_timing=False)
        async with _client(app) as client:
            resp = await client.post(
                "/user",
                json={"name": "Alice"},  # missing 'age'
            )
            assert resp.status_code == 422
            data = resp.json()
            assert "detail" in data
            assert "age" in data["detail"]

    @pytest.mark.anyio
    async def test_wrong_type_422(self):
        """Wrong type for a field -> 422."""
        router = Router()

        @router.post("/user")
        async def create_user(req):
            user = req.json_as(UserIn)
            return {"name": user.name, "age": user.age}

        app = create_app(router, request_id=False, request_timing=False)
        async with _client(app) as client:
            resp = await client.post(
                "/user",
                json={"name": "Alice", "age": "not_a_number"},
            )
            assert resp.status_code == 422
            data = resp.json()
            assert "detail" in data

    @pytest.mark.anyio
    async def test_empty_body_422(self):
        """Empty body (no JSON) -> 422."""
        router = Router()

        @router.post("/user")
        async def create_user(req):
            user = req.json_as(UserIn)
            return {"name": user.name, "age": user.age}

        app = create_app(router, request_id=False, request_timing=False)
        async with _client(app) as client:
            resp = await client.post("/user")
            assert resp.status_code == 422
            data = resp.json()
            assert "detail" in data

    @pytest.mark.anyio
    async def test_invalid_json_body_422(self):
        """Non-JSON body -> 422."""
        router = Router()

        @router.post("/user")
        async def create_user(req):
            user = req.json_as(UserIn)
            return {"name": user.name, "age": user.age}

        app = create_app(router, request_id=False, request_timing=False)
        async with _client(app) as client:
            resp = await client.post(
                "/user",
                content=b"not json",
                headers={"content-type": "text/plain"},
            )
            assert resp.status_code == 422
            data = resp.json()
            assert "detail" in data
