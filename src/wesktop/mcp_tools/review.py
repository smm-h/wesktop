"""Review MCP tools for posting inline comments on code changes, delegating to the wesktop server API for persistent review storage."""

from wesktop.mcp_tools import _http


def post_review_comment(
    server_url: str,
    auth_token: str,
    file: str,
    line: int,
    body: str,
) -> str:
    """Post a review comment on a specific file and line."""
    payload = {"file": file, "line": line, "body": body}
    return _http.request(
        server_url,
        auth_token,
        "POST",
        "/api/review/comment",
        payload,
        timeout=15,
        parse_json=False,
    )
