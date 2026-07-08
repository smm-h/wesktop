"""wesktop — A Python framework for building web-based desktop applications."""

from __future__ import annotations

import importlib
import importlib.metadata

from wesktop.entries import create_entry, remove_entry
from wesktop.asgi import (
    AppConfig,
    Router,
    Request,
    State,
    WebSocket,
    WebSocketDisconnect,
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
from wesktop.sse import Broadcaster, sse_route
from wesktop.features import FeatureFlags
from wesktop.audit import AuditLog
from wesktop.tasks import BackgroundTask, TaskRegistry

__version__ = importlib.metadata.version("wesktop")

# ---------------------------------------------------------------------------
# Lazy attributes (PEP 562)
#
# Heavy or optional machinery (granian via wesktop.server, pywebview via
# wesktop.desktop, pydantic via wesktop.sdui, the mcp package via
# wesktop.mcp) must not load on `import wesktop`. Each name below is
# resolved from its owning module on first attribute access and then
# cached in the module globals. This forwards the *actual* functions --
# there are no hand-written wrapper signatures to drift out of sync.
# ---------------------------------------------------------------------------

_SDUI_NAMES = (
    "SDUINode",
    "node",
    "register_sdui_provider",
    "get_sdui_provider",
    "list_sdui_providers",
    # Sub-models
    "TabItem",
    "BreadcrumbItem",
    "TimelineItem",
    "ColumnDef",
    "KVEntry",
    "OptionItem",
    "DataGridColumnDef",
    # Layout
    "Stack",
    "ZStack",
    "Spacer",
    "Divider",
    "Grid",
    "Card",
    "Tabs",
    "Breadcrumb",
    "Empty",
    # Display
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
    # Data
    "Table",
    "DataGrid",
    "List",
    "KeyValue",
    "JsonView",
    "Tree",
    # Input
    "Button",
    "Input",
    "TextArea",
    "Select",
    "Checkbox",
    "Switch",
    "Radio",
    "Slider",
    # Feedback
    "Alert",
    "Toast",
    "Logs",
    # Overlay
    "Modal",
    "Drawer",
    "Popover",
    "Confirm",
)

_LAZY_ATTRS: dict[str, str] = {
    # desktop (pywebview)
    "run": "wesktop.desktop",
    "ensure_gui_backend": "wesktop.desktop",
    # server lifecycle (granian)
    "serve": "wesktop.server",
    "serve_background": "wesktop.server",
    "stop": "wesktop.server",
    "status": "wesktop.server",
    "ServerStatus": "wesktop.server",
    # dev mode (vite + server)
    "dev": "wesktop.dev",
    # mcp (agent role registry + server factory)
    "ROLES": "wesktop.mcp",
    "DEFAULT_ROLE": "wesktop.mcp",
    "create_mcp_server": "wesktop.mcp",
    "register_tools_for_role": "wesktop.mcp",
    # sdui (pydantic)
    **{name: "wesktop.sdui" for name in _SDUI_NAMES},
}


def __getattr__(name: str) -> object:
    module_name = _LAZY_ATTRS.get(name)
    if module_name is None:
        raise AttributeError(f"module 'wesktop' has no attribute {name!r}")
    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value  # cache: later lookups bypass __getattr__
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_ATTRS))


__all__ = [
    # asgi
    "AppConfig",
    "Router",
    "Request",
    "State",
    "WebSocket",
    "WebSocketDisconnect",
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
    # server lifecycle (lazy)
    "serve",
    "serve_background",
    "stop",
    "status",
    "ServerStatus",
    "run",
    "dev",
    # desktop (lazy)
    "ensure_gui_backend",
    # features
    "FeatureFlags",
    # audit
    "AuditLog",
    # tasks
    "BackgroundTask",
    "TaskRegistry",
    # mcp (lazy)
    "ROLES",
    "DEFAULT_ROLE",
    "create_mcp_server",
    "register_tools_for_role",
    # sdui (lazy)
    *_SDUI_NAMES,
    # metadata
    "__version__",
]
