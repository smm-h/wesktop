"""wesktop's agent role registry plus the MCP server factory that wraps fastware: per-role tool provisioning for implementor, auditor, reviewer, and deployer agents.

fastware's MCP layer is role-agnostic -- its ``create_mcp_server`` and
``register_tools_for_role`` take a ``roles`` mapping explicitly. The
implementor/auditor/reviewer/deployer domain model lives here: pass
``roles=wesktop.mcp.ROLES`` (and ``default_role=wesktop.mcp.DEFAULT_ROLE``)
when creating a server or registering tools.

### ROLES

Registry mapping each agent role name (``implementor``, ``auditor``,
``reviewer``, ``deployer``) to its config dict -- a permission ``level`` and
the allowlist of MCP ``tools`` that role may call. This is wesktop's
application role model; fastware ships none.

### DEFAULT_ROLE

Name of the fallback role (``auditor``, the least-privileged read-only role)
used when a requested role is unknown. Auditor is the safe default because it
grants no write, review-posting, or deploy capabilities.
"""

from __future__ import annotations

from collections.abc import Callable
from types import ModuleType
from typing import Any

from fastware.mcp import create_mcp_server as _create_mcp_server
from fastware.mcp import register_tools_for_role as _register_tools_for_role

__all__ = [
    "ROLES",
    "DEFAULT_ROLE",
    "create_mcp_server",
    "register_tools_for_role",
]

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
# Server factory / tool registration (wesktop-role-aware wrappers over fastware)
# ---------------------------------------------------------------------------


def create_mcp_server(
    name: str = "fastware-agent",
    *,
    role: str | None = None,
    tool_modules: list[ModuleType] | None = None,
    roles: dict[str, dict[str, Any]] | None = None,
    default_role: str | None = None,
) -> Any:
    """Create a FastMCP server with role-filtered tools, using wesktop's roles.

    Thin wrapper over fastware's role-agnostic factory. wesktop owns the role
    model, so pass ``roles=ROLES`` (and optionally ``default_role=DEFAULT_ROLE``)
    to provision an implementor/auditor/reviewer/deployer server; without a
    ``roles`` mapping fastware has no roles to filter tools by. Raises
    ``RuntimeError`` if the optional ``mcp`` package is not installed.
    """
    return _create_mcp_server(
        name,
        role=role,
        tool_modules=tool_modules,
        roles=roles,
        default_role=default_role,
    )


def register_tools_for_role(
    server: Any,
    role: str,
    tool_modules: list[ModuleType],
    *,
    roles: dict[str, dict[str, Any]],
    default_role: str | None = None,
) -> dict[str, Callable[..., Any]]:
    """Register only the tools allowed by *role* onto an existing server.

    Thin wrapper over fastware's role-agnostic registrar. Each module in
    *tool_modules* must expose a ``TOOLS`` dict; only the tools listed for
    *role* in wesktop's ``ROLES`` registry are attached. Callers pass
    ``roles=ROLES`` (and optionally ``default_role=DEFAULT_ROLE``). Returns the
    dict of registered tool name -> callable.
    """
    return _register_tools_for_role(
        server,
        role,
        tool_modules,
        roles=roles,
        default_role=default_role,
    )
