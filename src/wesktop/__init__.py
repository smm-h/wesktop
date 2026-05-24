"""wesktop — A Python framework for building web-based desktop applications."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path
from typing import Callable

from wesktop.entries import create_entry, remove_entry
from wesktop.asgi import (
    AppConfig,
    Router,
    Request,
    State,
    WebSocket,
    JSONResponse,
    TextResponse,
    HTMLResponse,
    BytesResponse,
    StreamResponse,
    FileResponse,
    HTTPError,
    Scope,
    Receive,
    Send,
    create_app,
    send_error,
    set_cookie,
    delete_cookie,
)
from wesktop.auth import (
    create_token,
    verify_token,
    hash_password,
    verify_password,
    JSONFileUserStore,
    get_current_user,
    require_role,
    CSRFMiddleware,
    set_session_cookies,
    clear_session_cookies,
    rate_limit,
)
from wesktop.di import DependencyResolver
from wesktop.error_log import ErrorLog
from wesktop.logging import configure_logging, get_logger, init_sentry
from wesktop.middleware import (
    CORSMiddleware,
    RequestIDMiddleware,
    RequestTimingMiddleware,
    TrustedHostMiddleware,
    ViteDevProxy,
)
from wesktop.config import load_config
from wesktop.testing import AsyncTestClient, TestClient
from wesktop.server import ServerStatus
from wesktop.sse import Broadcaster, sse_route
from wesktop.features import FeatureFlags
from wesktop.audit import AuditLog
from wesktop.tasks import BackgroundTask, TaskRegistry
from wesktop.mcp import (
    ROLES,
    DEFAULT_ROLE,
    create_mcp_server,
    register_tools_for_role,
)
from wesktop.sdui import (
    SDUINode,
    node,
    register_sdui_provider,
    get_sdui_provider,
    list_sdui_providers,
    # Sub-models
    TabItem,
    BreadcrumbItem,
    TimelineItem,
    ColumnDef,
    KVEntry,
    OptionItem,
    DataGridColumnDef,
    # Layout
    Stack,
    ZStack,
    Spacer,
    Divider,
    Grid,
    Card,
    Tabs,
    Breadcrumb,
    Empty,
    # Display
    Heading,
    Text,
    Code,
    Status,
    Badge,
    ProgressBar,
    Spinner,
    Timeline,
    Diff,
    Markdown,
    # Data
    Table,
    DataGrid,
    List,
    KeyValue,
    JsonView,
    Tree,
    # Input
    Button,
    Input,
    TextArea,
    Select,
    Checkbox,
    Switch,
    Radio,
    Slider,
    # Feedback
    Alert,
    Toast,
    Logs,
    # Overlay
    Modal,
    Drawer,
    Popover,
    Confirm,
)

__version__ = importlib.metadata.version("wesktop")

__all__ = [
    # asgi
    "AppConfig",
    "Router",
    "Request",
    "State",
    "WebSocket",
    "JSONResponse",
    "TextResponse",
    "HTMLResponse",
    "BytesResponse",
    "StreamResponse",
    "FileResponse",
    "HTTPError",
    "Scope",
    "Receive",
    "Send",
    "create_app",
    "send_error",
    "set_cookie",
    "delete_cookie",
    # auth
    "create_token",
    "verify_token",
    "hash_password",
    "verify_password",
    "JSONFileUserStore",
    "get_current_user",
    "require_role",
    "CSRFMiddleware",
    "set_session_cookies",
    "clear_session_cookies",
    "rate_limit",
    # di
    "DependencyResolver",
    # error_log
    "ErrorLog",
    # logging
    "configure_logging",
    "get_logger",
    "init_sentry",
    # middleware
    "CORSMiddleware",
    "RequestIDMiddleware",
    "RequestTimingMiddleware",
    "TrustedHostMiddleware",
    "ViteDevProxy",
    # config
    "load_config",
    # testing
    "AsyncTestClient",
    "TestClient",
    # sse
    "Broadcaster",
    "sse_route",
    # entries
    "create_entry",
    "remove_entry",
    # server lifecycle
    "serve",
    "stop",
    "status",
    "ServerStatus",
    "run",
    # features
    "FeatureFlags",
    # audit
    "AuditLog",
    # tasks
    "BackgroundTask",
    "TaskRegistry",
    # sdui
    "SDUINode",
    "node",
    "register_sdui_provider",
    "get_sdui_provider",
    "list_sdui_providers",
    "TabItem",
    "BreadcrumbItem",
    "TimelineItem",
    "ColumnDef",
    "KVEntry",
    "OptionItem",
    "DataGridColumnDef",
    "Stack",
    "ZStack",
    "Spacer",
    "Divider",
    "Grid",
    "Card",
    "Tabs",
    "Breadcrumb",
    "Empty",
    "Heading",
    "Text",
    "Code",
    "Status",
    "Badge",
    "ProgressBar",
    "Spinner",
    "Timeline",
    "Diff",
    "Markdown",
    "Table",
    "DataGrid",
    "List",
    "KeyValue",
    "JsonView",
    "Tree",
    "Button",
    "Input",
    "TextArea",
    "Select",
    "Checkbox",
    "Switch",
    "Radio",
    "Slider",
    "Alert",
    "Toast",
    "Logs",
    "Modal",
    "Drawer",
    "Popover",
    "Confirm",
    # mcp
    "ROLES",
    "DEFAULT_ROLE",
    "create_mcp_server",
    "register_tools_for_role",
    # metadata
    "__version__",
]


def run(
    target: str | Callable,
    *,
    title: str = "wesktop",
    width: int = 1280,
    height: int = 800,
    icon: str | None = None,
    host: str | None = None,
    port: int | None = None,
    pid_path: Path | None = None,
    name: str = "WESKTOP",
    pre_serve: Callable[[], None] | None = None,
    reload: bool = False,
    js_api: object | None = None,
) -> None:
    """Start server + native desktop window."""
    from wesktop.desktop import run as _run

    _run(
        target,
        title=title,
        width=width,
        height=height,
        icon=icon,
        host=host,
        port=port,
        pid_path=pid_path,
        name=name,
        pre_serve=pre_serve,
        reload=reload,
        js_api=js_api,
    )


def serve(
    target: str | Callable,
    *,
    foreground: bool,
    host: str | None = None,
    port: int | None = None,
    pid_path: Path | None = None,
    name: str = "WESKTOP",
    pre_serve: Callable[[], None] | None = None,
    reload: bool = False,
) -> str | None:
    """Start server. Blocks if foreground=True, returns URL if foreground=False."""
    from wesktop.server import serve as _serve

    return _serve(
        target,
        foreground=foreground,
        host=host,
        port=port,
        pid_path=pid_path,
        name=name,
        pre_serve=pre_serve,
        reload=reload,
    )


def stop(pid_path: Path) -> None:
    """Stop a running server by PID file."""
    from wesktop.server import stop as _stop

    _stop(pid_path)


def status(pid_path: Path, health_url: str | None = None) -> ServerStatus:
    """Check server status by PID file and optional health URL."""
    from wesktop.server import status as _status

    return _status(pid_path, health_url=health_url)
