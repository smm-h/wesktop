"""Verify re-export stubs forward correctly to fastware."""


def test_asgi_stub():
    from wesktop.asgi import Router, Request, JSONResponse, create_app, WebSocket, HTTPError
    assert Router is not None
    assert Request is not None


def test_sse_stub():
    from wesktop.sse import Broadcaster, sse_route
    assert Broadcaster is not None


def test_server_stub():
    from wesktop.server import serve, stop, status, ServerStatus
    assert serve is not None


def test_middleware_stub():
    from wesktop.middleware import CORSMiddleware, ViteDevProxy
    assert CORSMiddleware is not None


def test_auth_stub():
    from wesktop.auth import create_token, CSRFMiddleware
    assert create_token is not None


def test_di_stub():
    from wesktop.di import DependencyResolver
    assert DependencyResolver is not None


def test_testing_stub():
    from wesktop.testing import AsyncTestClient, TestClient
    assert AsyncTestClient is not None


def test_logging_stub():
    from wesktop.logging import configure_logging, get_logger
    assert configure_logging is not None


def test_features_stub():
    from wesktop.features import FeatureFlags
    assert FeatureFlags is not None


def test_tasks_stub():
    from wesktop.tasks import TaskRegistry
    assert TaskRegistry is not None


def test_config_stub():
    from wesktop.config import load_config
    assert load_config is not None


def test_mcp_stub():
    from wesktop.mcp import create_mcp_server, ROLES
    assert create_mcp_server is not None


def test_dev_stub():
    from wesktop.dev import dev
    assert dev is not None


def test_error_log_stub():
    from wesktop.error_log import ErrorLog
    assert ErrorLog is not None


def test_audit_stub():
    from wesktop.audit import AuditLog
    assert AuditLog is not None


def test_top_level_exports():
    from wesktop import Router, Request, JSONResponse, create_app, Broadcaster
    assert Router is not None
