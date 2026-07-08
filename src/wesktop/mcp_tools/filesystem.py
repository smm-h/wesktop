"""Filesystem MCP tools scoped to an agent's worktree: read, write, edit, list, and search files with path traversal guard enforcement.

All paths are relative to the worktree root. Traversal outside
the worktree is blocked by _guard_path.
"""

import os
import subprocess
from pathlib import Path

from wesktop.mcp_tools._paths import guard_path as _guard_path

# Max file size for reading (1 MB).
_MAX_FILE_SIZE = 1_048_576


def read_file(worktree: str, path: str) -> str:
    """Read a file from the worktree. Path is relative to worktree root."""
    wt = Path(worktree)
    target = _guard_path(wt, path)

    if not target.is_file():
        return f"Error: file not found: {path}"

    size = target.stat().st_size
    if size > _MAX_FILE_SIZE:
        return f"Error: file too large ({size} bytes, max {_MAX_FILE_SIZE})"

    try:
        content = target.read_text(encoding="utf-8", errors="strict")
    except (UnicodeDecodeError, ValueError):
        return f"Error: binary file cannot be read as text: {path}"

    return content


def write_file(worktree: str, path: str, content: str) -> str:
    """Write content to a file in the worktree. Creates parent dirs as needed."""
    wt = Path(worktree)
    target = _guard_path(wt, path)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} bytes to {path}"


def edit_file(worktree: str, path: str, old_text: str, new_text: str) -> str:
    """Find and replace text in a file. Fails if old_text is not found."""
    wt = Path(worktree)
    target = _guard_path(wt, path)

    if not target.is_file():
        return f"Error: file not found: {path}"

    content = target.read_text(encoding="utf-8")
    if old_text not in content:
        return "Error: old_text not found in file"

    count = content.count(old_text)
    new_content = content.replace(old_text, new_text, 1)
    target.write_text(new_content, encoding="utf-8")

    if count > 1:
        return f"Replaced first occurrence (found {count} total) in {path}"
    return f"Replaced text in {path}"


def list_files(worktree: str, path: str = "") -> str:
    """List directory contents under the worktree.

    Returns one entry per line: 'd <name>' for directories, 'f <name> (<size>)' for files.
    """
    wt = Path(worktree)
    target = _guard_path(wt, path or ".")

    if not target.is_dir():
        return f"Error: not a directory: {path}"

    lines = []
    try:
        entries = sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
    except PermissionError:
        return "Error: permission denied"

    for entry in entries:
        name = entry.name
        # Skip hidden dirs but allow .env files.
        if name.startswith(".") and entry.is_dir():
            continue

        rel = str(entry.relative_to(wt.resolve()))
        if entry.is_dir():
            lines.append(f"d {rel}/")
        elif entry.is_file():
            try:
                size = entry.stat().st_size
            except OSError:
                size = 0
            lines.append(f"f {rel} ({size}b)")

    return "\n".join(lines) if lines else "(empty directory)"


def search_files(worktree: str, pattern: str, path: str = "") -> str:
    """Search file contents using ripgrep. Returns matching lines with context."""
    wt = Path(worktree)
    search_dir = _guard_path(wt, path or ".")

    if not search_dir.is_dir():
        return f"Error: not a directory: {path}"

    try:
        result = subprocess.run(
            [
                "rg",
                "--no-heading",
                "--line-number",
                "--color=never",
                "--max-count=50",
                "--max-filesize=1M",
                pattern,
                str(search_dir),
            ],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(wt),
        )
    except FileNotFoundError:
        return "Error: ripgrep (rg) not found on PATH"
    except subprocess.TimeoutExpired:
        return "Error: search timed out after 15s"

    if result.returncode == 1:
        return "No matches found."
    if result.returncode != 0:
        return f"Error: rg exited with code {result.returncode}: {result.stderr}"

    # Make paths relative to worktree for readability. Use os.sep so the
    # prefix strip is correct on Windows (backslash) as well as POSIX.
    wt_prefix = str(wt.resolve()) + os.sep
    output = result.stdout.replace(wt_prefix, "")

    # Truncate if very long.
    lines = output.splitlines()
    if len(lines) > 200:
        return "\n".join(lines[:200]) + f"\n... ({len(lines) - 200} more lines)"
    return output.rstrip()
