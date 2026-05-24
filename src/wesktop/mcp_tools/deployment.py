"""Deployment tools that delegate to a server API."""

import json
import urllib.error
import urllib.request
from typing import Any


def _api_call(
    server_url: str,
    auth_token: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    timeout: int = 30,
) -> str:
    """Make an authenticated request to a server.

    Returns the response body as a string, or an error message.
    """
    url = f"{server_url.rstrip('/')}{path}"
    body = json.dumps(payload).encode("utf-8") if payload else None
    headers = {"Authorization": f"Bearer {auth_token}"}
    if body:
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return str(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        return f"Error: HTTP {e.code} -- {e.read().decode('utf-8', errors='replace')}"
    except urllib.error.URLError as e:
        return f"Error: could not reach server: {e.reason}"
    except TimeoutError:
        return f"Error: request timed out after {timeout}s"


def stage_branch(
    server_url: str,
    auth_token: str,
    qualified_branch: str,
    message: str,
) -> str:
    """Trigger staging merge for a branch via a server API."""
    path = f"/api/branches/{qualified_branch}/pipeline/stage"
    return _api_call(server_url, auth_token, "POST", path, {"message": message})


def create_prod_pr(
    server_url: str,
    auth_token: str,
    qualified_branch: str,
    message: str,
) -> str:
    """Create a production PR for a branch via a server API."""
    path = f"/api/branches/{qualified_branch}/pipeline/prod"
    return _api_call(server_url, auth_token, "POST", path, {"message": message})


def check_pipeline(
    server_url: str,
    auth_token: str,
    qualified_branch: str,
) -> str:
    """Check pipeline status for a branch via a server API."""
    path = f"/api/branches/{qualified_branch}/pipeline"
    return _api_call(server_url, auth_token, "GET", path)
