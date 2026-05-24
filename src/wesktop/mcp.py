"""MCP server for per-role agent tool provisioning.

Provides role-based tool filtering and server creation for MCP agent
processes. The ``mcp`` package is an optional dependency -- this module
is importable without it, but ``create_mcp_server`` raises a clear
error if the package is not installed.

Environment variables consumed by the default server:
    SA_ROLE          -- agent role (implementor, auditor, reviewer, deployer)
    SA_TASK_ID       -- unique task identifier
    SA_SESSION_ID    -- parent session identifier
    SA_WORKTREE      -- absolute path to the git worktree
    SA_PROJECT_ROOT  -- absolute path to the project root
    SA_SERVER_URL    -- server base URL (e.g. http://127.0.0.1:9100)
    SA_AUTH_TOKEN    -- bearer token for server API calls
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from types import ModuleType
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP

    _MCP_AVAILABLE = True
except ModuleNotFoundError:
    _MCP_AVAILABLE = False

# ---------------------------------------------------------------------------
# Role definitions
# ---------------------------------------------------------------------------

ROLES: dict[str, dict[str, Any]] = {
    "implementor": {
        "level": "read-write",
        "tools": [
            "read_file",
            "write_file",
            "edit_file",
            "list_files",
            "search_files",
            "git_status",
            "git_diff",
            "git_commit",
            "git_log",
            "run_tests",
            "ask_user",
        ],
    },
    "auditor": {
        "level": "read-only",
        "tools": [
            "read_file",
            "list_files",
            "search_files",
            "git_status",
            "git_diff",
            "git_log",
            "run_tests",
            "ask_user",
        ],
    },
    "reviewer": {
        "level": "read-only",
        "tools": [
            "read_file",
            "list_files",
            "search_files",
            "git_diff",
            "git_log",
            "post_review_comment",
            "ask_user",
        ],
    },
    "deployer": {
        "level": "everything",
        "tools": [
            "read_file",
            "list_files",
            "search_files",
            "git_status",
            "git_diff",
            "git_log",
            "stage_branch",
            "create_prod_pr",
            "check_pipeline",
            "ask_user",
        ],
    },
}

DEFAULT_ROLE = "auditor"

# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_tools_for_role(
    server: Any,
    role: str,
    tool_modules: list[ModuleType],
) -> dict[str, Callable[..., Any]]:
    """Register only the tools allowed by *role* on *server*.

    Each module in *tool_modules* must define a ``TOOLS`` dict mapping
    tool name to the callable. Only tools listed in the role's config
    are registered.

    Returns the dict of registered tool name -> function.
    """
    role_config = ROLES.get(role, ROLES[DEFAULT_ROLE])
    allowed = set(role_config["tools"])

    registry: dict[str, Callable[..., Any]] = {}
    for mod in tool_modules:
        mod_tools: dict[str, Callable[..., Any]] = getattr(mod, "TOOLS", {})
        for name, fn in mod_tools.items():
            if name in allowed:
                server.add_tool(fn, name=name)
                registry[name] = fn

    return registry


# ---------------------------------------------------------------------------
# Server factory
# ---------------------------------------------------------------------------


def create_mcp_server(
    name: str = "wesktop-agent",
    *,
    role: str | None = None,
    tool_modules: list[ModuleType] | None = None,
) -> Any:
    """Create a FastMCP server with role-filtered tools.

    Parameters
    ----------
    name:
        Server name passed to FastMCP.
    role:
        Agent role. If *None*, reads ``SA_ROLE`` from environment
        (falling back to DEFAULT_ROLE).
    tool_modules:
        List of modules that define a ``TOOLS`` dict. If *None*, no
        tools are registered (caller must register manually).

    Returns
    -------
    FastMCP
        The configured server instance.

    Raises
    ------
    RuntimeError
        If the ``mcp`` package is not installed.
    """
    if not _MCP_AVAILABLE:
        raise RuntimeError(
            "The 'mcp' package is required for MCP server support. "
            "Install it with: pip install mcp"
        )

    if role is None:
        role = os.environ.get("SA_ROLE", DEFAULT_ROLE)

    server = FastMCP(name)

    if tool_modules is not None:
        register_tools_for_role(server, role, tool_modules)

    return server
