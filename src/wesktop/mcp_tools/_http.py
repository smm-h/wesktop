"""Shared authenticated-HTTP helper for the HTTP-backed MCP tool modules.

Every server-delegating tool (ask_user, deployment, review, testing) needs the
same request scaffolding: join the path onto the server URL, attach a Bearer
token, JSON-encode the payload, and translate urllib errors. This module is the
single implementation. Pure stdlib, zero internal dependencies.

Two return modes, chosen by the ``parse_json`` flag:

- ``parse_json=True``  -- returns the parsed JSON body (a dict) and lets
  urllib errors propagate, so the caller can distinguish failure from a valid
  response (used by ask_user's polling loop).
- ``parse_json=False`` -- returns the raw response body as text, or a formatted
  ``"Error: ..."`` string on any transport/HTTP failure (used by the tools that
  surface the server reply verbatim to the agent).
"""

import json
import urllib.error
import urllib.request
from typing import Any


def request(
    server_url: str,
    auth_token: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    timeout: int = 30,
    *,
    parse_json: bool,
) -> Any:
    """Make an authenticated request. See module docstring for return modes."""
    url = f"{server_url.rstrip('/')}{path}"
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Authorization": f"Bearer {auth_token}"}
    if body is not None:
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    if parse_json:
        # Errors propagate to the caller.
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
            return result

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return f"Error: HTTP {e.code} -- {e.read().decode('utf-8', errors='replace')}"
    except urllib.error.URLError as e:
        return f"Error: could not reach server: {e.reason}"
    except TimeoutError:
        return f"Error: request timed out after {timeout}s"
