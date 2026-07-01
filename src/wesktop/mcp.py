"""MCP (Model Context Protocol) server factory re-exported from fastware: per-role agent tool provisioning, tool filtering, and server lifecycle."""

from fastware.mcp import *  # noqa: F401,F403

# Private attribute used by tests (monkeypatched to simulate missing mcp package)
from fastware.mcp import _MCP_AVAILABLE  # noqa: F401
