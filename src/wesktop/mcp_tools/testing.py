"""Testing MCP tools that delegate test suite execution, result collection, and coverage reporting to the wesktop server API endpoint."""

from wesktop.mcp_tools import _http


def run_tests(server_url: str, auth_token: str, suite: str = "", pattern: str = "") -> str:
    """Run tests via a server API.

    Sends a POST to {server_url}/api/tests/run with optional suite and pattern filters.
    """
    payload: dict[str, str] = {}
    if suite:
        payload["suite"] = suite
    if pattern:
        payload["pattern"] = pattern

    return _http.request(
        server_url,
        auth_token,
        "POST",
        "/api/tests/run",
        payload,
        timeout=120,
        parse_json=False,
    )
