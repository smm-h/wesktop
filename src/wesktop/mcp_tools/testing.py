"""Testing MCP tools that delegate test suite execution, result collection, and coverage reporting to the wesktop server API endpoint."""

import json
import urllib.error
import urllib.request


def run_tests(server_url: str, auth_token: str, suite: str = "", pattern: str = "") -> str:
    """Run tests via a server API.

    Sends a POST to {server_url}/api/tests/run with optional suite and pattern filters.
    """
    payload = {}
    if suite:
        payload["suite"] = suite
    if pattern:
        payload["pattern"] = pattern

    body = json.dumps(payload).encode("utf-8")
    url = f"{server_url.rstrip('/')}/api/tests/run"

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {auth_token}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return str(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        return f"Error: HTTP {e.code} -- {e.read().decode('utf-8', errors='replace')}"
    except urllib.error.URLError as e:
        return f"Error: could not reach server: {e.reason}"
    except TimeoutError:
        return "Error: test run timed out after 120s"
