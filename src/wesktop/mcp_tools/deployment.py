"""Deployment MCP tools that delegate staging, production PR creation, and pipeline status checks to the wesktop server API."""

from urllib.parse import quote

from wesktop.mcp_tools import _http


def stage_branch(
    server_url: str,
    auth_token: str,
    qualified_branch: str,
    message: str,
) -> str:
    """Trigger staging merge for a branch via a server API."""
    path = f"/api/branches/{quote(qualified_branch)}/pipeline/stage"
    return _http.request(server_url, auth_token, "POST", path, {"message": message}, parse_json=False)


def create_prod_pr(
    server_url: str,
    auth_token: str,
    qualified_branch: str,
    message: str,
) -> str:
    """Create a production PR for a branch via a server API."""
    path = f"/api/branches/{quote(qualified_branch)}/pipeline/prod"
    return _http.request(server_url, auth_token, "POST", path, {"message": message}, parse_json=False)


def check_pipeline(
    server_url: str,
    auth_token: str,
    qualified_branch: str,
) -> str:
    """Check pipeline status for a branch via a server API."""
    path = f"/api/branches/{quote(qualified_branch)}/pipeline"
    return _http.request(server_url, auth_token, "GET", path, parse_json=False)
