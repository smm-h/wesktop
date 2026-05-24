"""Git tools scoped to an agent's worktree.

All commands run with -C <worktree> and have timeouts.
"""

import subprocess
from pathlib import Path


def _run(worktree: str, *args: str, timeout: int = 30) -> tuple[str, str, int]:
    """Run a git command in the worktree with a timeout.

    Returns (stdout, stderr, returncode). Never raises on git failure.
    """
    try:
        result = subprocess.run(
            ["git", "-C", worktree, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout.rstrip("\n"), result.stderr.rstrip("\n"), result.returncode
    except subprocess.TimeoutExpired:
        return "", "git command timed out", 1
    except OSError as e:
        return "", str(e), 1


def git_status(worktree: str) -> str:
    """Show working tree status (porcelain format)."""
    stdout, stderr, rc = _run(worktree, "status", "--porcelain")
    if rc != 0:
        return f"Error: {stderr}"
    return stdout or "(clean working tree)"


def git_diff(worktree: str, path: str = "") -> str:
    """Show unstaged changes. Optionally limited to a specific file path."""
    args = ["diff"]
    if path:
        # Guard: resolve and verify path is under worktree.
        wt = Path(worktree).resolve()
        target = (wt / path).resolve()
        if not str(target).startswith(str(wt)):
            return "Error: path traversal blocked"
        args.append("--")
        args.append(path)
    stdout, stderr, rc = _run(worktree, *args)
    if rc != 0:
        return f"Error: {stderr}"
    return stdout or "(no unstaged changes)"


def git_commit(worktree: str, message: str) -> str:
    """Stage all changes and commit with the given message."""
    # Stage everything.
    _, stderr, rc = _run(worktree, "add", "-A")
    if rc != 0:
        return f"Error staging: {stderr}"

    # Commit.
    stdout, stderr, rc = _run(worktree, "commit", "-m", message)
    if rc != 0:
        # "nothing to commit" is rc=1 but not an error.
        if "nothing to commit" in stderr or "nothing to commit" in stdout:
            return "Nothing to commit (working tree clean)."
        return f"Error committing: {stderr}"

    return stdout


def git_log(worktree: str, count: int = 20) -> str:
    """Show recent commit log (oneline format)."""
    # Clamp count to a reasonable range.
    n = max(1, min(count, 100))
    stdout, stderr, rc = _run(worktree, "log", "--oneline", f"-{n}")
    if rc != 0:
        return f"Error: {stderr}"
    return stdout or "(no commits)"
