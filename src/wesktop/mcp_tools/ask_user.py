"""Ask-user tool: posts a question to a dashboard and polls for the answer.

Reaches the server via HTTP using server_url and auth_token parameters.
"""

import json
import time
import urllib.error
import urllib.request
from typing import Any

POLL_INTERVAL_SECONDS = 2
POLL_TIMEOUT_SECONDS = 600  # 10 minutes


def _api(
    server_url: str, auth_token: str, method: str, path: str, payload: dict[str, Any] | None = None, timeout: int = 15
) -> dict[str, Any]:
    """Make an authenticated JSON request and return the parsed response."""
    url = f"{server_url.rstrip('/')}{path}"
    body = json.dumps(payload).encode("utf-8") if payload else None
    headers = {"Authorization": f"Bearer {auth_token}"}
    if body:
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
        return result


def ask_user(
    server_url: str,
    auth_token: str,
    session_id: str,
    branch: str,
    role: str,
    question: str,
    options: list[str] | None = None,
) -> str:
    """Post a question to the dashboard inbox and block until it is answered.

    Creates a persisted question via POST /api/questions, then polls
    GET /api/questions/{id} until status becomes "answered". Returns
    the answer text, or an error/timeout message.
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
        result = _api(server_url, auth_token, "POST", "/api/questions", payload)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
        return f"Error creating question: {e}"

    question_id = result.get("id")
    if not question_id:
        return f"Error: server returned no question id: {result}"

    # Poll until answered or timeout.
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(POLL_INTERVAL_SECONDS)
        try:
            q = _api(server_url, auth_token, "GET", f"/api/questions/{question_id}")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            continue  # transient failure, keep polling

        if q.get("status") == "answered":
            return str(q.get("answer", "(no answer text)"))

    return "Error: timed out waiting for user answer (10 minutes)"
