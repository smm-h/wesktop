"""Ask-user MCP tool: posts a question to the wesktop dashboard via HTTP API and polls for the user's answer with configurable timeout.

Reaches the server via HTTP using server_url and auth_token parameters.
"""

import time
import urllib.error
from typing import Any

from wesktop.mcp_tools import _http

POLL_INTERVAL_SECONDS = 2
POLL_TIMEOUT_SECONDS = 600  # 10 minutes


def ask_user(
    server_url: str,
    auth_token: str,
    session_id: str,
    branch: str,
    role: str,
    question: str,
    options: list[str] | None = None,
    poll_timeout_seconds: float = POLL_TIMEOUT_SECONDS,
    poll_interval_seconds: float = POLL_INTERVAL_SECONDS,
) -> str:
    """Post a question to the dashboard inbox and block until it is answered.

    Creates a persisted question via POST /api/questions, then polls
    GET /api/questions/{id} every ``poll_interval_seconds`` until status
    becomes "answered" or ``poll_timeout_seconds`` elapses. Returns the answer
    text, or an error/timeout message.
    """
    # Create the question on the server.
    payload: dict[str, Any] = {
        "source": "agent",
        "branch": branch,
        "role": role,
        "question": question,
        "session_id": session_id,
    }
    if options:
        payload["options"] = options

    try:
        result = _http.request(server_url, auth_token, "POST", "/api/questions", payload, timeout=15, parse_json=True)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
        return f"Error creating question: {e}"

    question_id = result.get("id")
    if not question_id:
        return f"Error: server returned no question id: {result}"

    # Poll until answered or timeout.
    deadline = time.monotonic() + poll_timeout_seconds
    while time.monotonic() < deadline:
        time.sleep(poll_interval_seconds)
        try:
            q = _http.request(
                server_url, auth_token, "GET", f"/api/questions/{question_id}", timeout=15, parse_json=True
            )
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            continue  # transient failure, keep polling

        if q.get("status") == "answered":
            return str(q.get("answer", "(no answer text)"))

    return f"Error: timed out waiting for user answer after {poll_timeout_seconds}s"