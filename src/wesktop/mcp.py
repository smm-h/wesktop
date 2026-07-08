"""wesktop's agent role registry plus the MCP server factory re-exported from fastware: per-role tool provisioning for implementor, auditor, reviewer, and deployer agents.

fastware's MCP layer is role-agnostic -- ``create_mcp_server`` and
``register_tools_for_role`` take a ``roles`` mapping explicitly. The
implementor/auditor/reviewer/deployer domain model lives here: pass
``roles=wesktop.mcp.ROLES`` (and ``default_role=wesktop.mcp.DEFAULT_ROLE``)
when creating a server or registering tools.
"""

from __future__ import annotations

from typing import Any

from fastware.mcp import create_mcp_server, register_tools_for_role  # noqa: F401

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
