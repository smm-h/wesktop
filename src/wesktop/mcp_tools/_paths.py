"""Shared worktree path-traversal guard for the MCP tool modules.

Kept in its own module so both filesystem.py and git.py can reuse the same
logic without one tool module importing another. Pure stdlib, zero internal
dependencies -- consistent with the rest of mcp_tools.
"""

from pathlib import Path


def guard_path(worktree: Path, relative: str) -> Path:
    """Resolve ``relative`` against ``worktree`` and ensure it stays inside.

    Uses ``Path.is_relative_to`` on the fully-resolved paths, which is correct
    on every platform (it compares path components, not string prefixes, so it
    is immune to both the ``'/a/repo2'`` sibling-prefix escape and to
    ``os.sep`` differences on Windows).

    Raises ValueError on any path that escapes the worktree.
    """
    resolved = (worktree / relative).resolve()
    worktree_resolved = worktree.resolve()
    if not resolved.is_relative_to(worktree_resolved):
        raise ValueError(f"Path traversal blocked: {relative}")
    return resolved
