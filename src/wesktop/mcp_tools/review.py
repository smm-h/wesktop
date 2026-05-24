"""Review tools for posting comments on code changes."""

import json
import urllib.error
import urllib.request


def post_review_comment(
    server_url: str,
    auth_token: str,
    file: str,
    line: int,
    body: str,
) -> str:
    """Post a review comment on a specific file and line."""
    url = f"{server_url.rstrip('/')}/api/review/comment"
    payload = json.dumps({"file": file, "line": line, "body": body}).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {auth_token}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return str(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        return f"Error: HTTP {e.code} -- {e.read().decode('utf-8', errors='replace')}"
    except urllib.error.URLError as e:
        return f"Error: could not reach server: {e.reason}"
    except TimeoutError:
        return "Error: request timed out"
