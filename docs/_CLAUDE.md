---
title: CLAUDE.md
description: Developer guide for AI agents working on the wesktop codebase
date: 2026-07-01
---
# wesktop

A Python framework for building web-based desktop applications. Provides native OS windows backed by a fast ASGI server.

## Architecture (post-extraction)

wesktop is built on [fastware](https://github.com/smm-h/fastware). The ASGI framework (routing, SSE, middleware, server, dependency injection, auth, testing, logging, tasks, features, error_log, audit, config, MCP, dev) lives in the fastware package. wesktop adds desktop-specific layers:

- **desktop.py** -- pywebview native windows, GUI backend detection (`ensure_gui_backend`), single-instance checking, auto-registration of desktop entries
- **entries.py** -- Cross-platform desktop shortcut creation/removal (Linux `.desktop` files, macOS `.app` bundles, Windows Start Menu shortcuts via COM or PowerShell)
- **sdui.py** -- 40 Server-Driven UI primitives (Pydantic models): Layout (9), Display (10), Data (6), Input (8), Feedback (3), Overlay (4)
- **cli.py** -- strictcli CLI with `diagnose` and `config` commands
- **mcp_tools/** -- 6 concrete MCP tool implementations (filesystem, git, deployment, ask_user, review, testing). Pure stdlib, zero internal imports.

## Re-export stubs

15 modules in `src/wesktop/` are thin re-export stubs that forward to fastware. They exist for backward compatibility -- `from wesktop.asgi import Router` works but the implementation lives in `fastware.routing.Router`.

| Stub module | Forwards to |
|---|---|
| `asgi.py` | `fastware.types`, `fastware.responses`, `fastware.request`, `fastware.routing`, `fastware.websocket`, `fastware.app` |
| `audit.py` | `fastware.audit` |
| `auth.py` | `fastware.auth` |
| `config.py` | `fastware.config` |
| `dev.py` | `fastware.dev` |
| `di.py` | `fastware.di` |
| `error_log.py` | `fastware.error_log` |
| `features.py` | `fastware.features` |
| `logging.py` | `fastware.logging` |
| `mcp.py` | `fastware.mcp` |
| `middleware.py` | `fastware.middleware` |
| `server.py` | `fastware.server` |
| `sse.py` | `fastware.sse` |
| `tasks.py` | `fastware.tasks` |
| `testing.py` | `fastware.testing` |

Some stubs (`asgi.py`, `server.py`, `mcp.py`) also re-export private helpers used by wesktop's own tests (monkeypatched in tests).

## Module layout

:-: list-modules path="src/wesktop/"

## Dependencies

:-: table-dep path="pyproject.toml"

Dev dependencies: `pytest`, `httpx` (async test client). 131 tests across 8 test modules.

## Public API

wesktop re-exports all of fastware's symbols plus its own. All public symbols are importable from `wesktop` directly.

**From fastware (via stubs):**

- `AppConfig`, `Router`, `Request`, `State`, `WebSocket` -- routing and request handling
- `JSONResponse`, `TextResponse`, `HTMLResponse`, `BytesResponse`, `StreamResponse`, `FileResponse` -- response types
- `HTTPError`, `Scope`, `Receive`, `Send` -- ASGI primitives
- `create_app`, `send_error`, `set_cookie`, `delete_cookie` -- app factory and helpers
- `create_token`, `verify_token`, `hash_password`, `verify_password`, `JSONFileUserStore`, `get_current_user`, `require_role`, `CSRFMiddleware`, `set_session_cookies`, `clear_session_cookies`, `rate_limit` -- auth
- `DependencyResolver` -- dependency injection
- `ErrorLog` -- error log
- `configure_logging`, `get_logger`, `init_sentry` -- logging
- `CORSMiddleware`, `RequestIDMiddleware`, `RequestTimingMiddleware`, `TrustedHostMiddleware`, `ViteDevProxy` -- middleware
- `load_config` -- config loading
- `AsyncTestClient`, `TestClient` -- testing
- `ServerStatus`, `serve_background` -- server lifecycle
- `Broadcaster`, `sse_route` -- SSE
- `FeatureFlags` -- feature flags
- `AuditLog` -- audit logging
- `BackgroundTask`, `TaskRegistry` -- background tasks
- `ROLES`, `DEFAULT_ROLE`, `create_mcp_server`, `register_tools_for_role` -- MCP server

**wesktop-native:**

- `run` -- start server + native desktop window (late-imports pywebview)
- `serve` -- start server only (foreground or background)
- `stop` -- stop a running server by PID file
- `status` -- check server status
- `dev` -- development mode with Vite proxy
- `ensure_gui_backend` -- make system PyGObject importable in isolated venvs
- `create_entry`, `remove_entry` -- desktop shortcut management
- 40 SDUI primitives from `sdui.py` (`SDUINode`, `node`, `register_sdui_provider`, `get_sdui_provider`, `list_sdui_providers`, layout/display/data/input/feedback/overlay models)

## Consumer patterns

### Desktop mode

```python
import wesktop

wesktop.run("myapp:app")  # server + native window
```

Starts a granian server in a background thread, opens a native OS window via pywebview, and blocks until the window is closed. Supports single-instance checking (second launch joins the existing server).

### Headless mode

```python
import wesktop

wesktop.serve("myapp:app", foreground=True)  # server only, blocks
```

Runs the ASGI server without a GUI. Useful for deployment and CI.

### CLI

```bash
wesktop diagnose              # runtime environment check
wesktop config show            # display configuration
wesktop config set key value   # set a config value
wesktop config edit            # open config in $EDITOR
wesktop --version              # package version
```

The CLI is also available as an npm shim: `npx wesktop diagnose`.

## Development

```bash
uv sync                    # Install dependencies
uv run pytest              # Run 131 tests
selfdoc build              # Build documentation site
selfdoc check              # Lint docs for SEO and staleness
```

## Conventions

- **Late imports for pywebview**: `desktop.py` imports `webview` inside `run()`, not at module level. This ensures headless consumers (`serve()`) never load the GUI dependency.
- **Re-export stubs use `from fastware.X import *` pattern**: all public API flows through fastware. Stubs exist solely for backward-compatible import paths.
- **mcp_tools/ have zero internal imports**: each tool module is pure stdlib. They communicate with servers via HTTP using parameters passed in at runtime.
- **sdui.py depends on pydantic at module level**: unlike pywebview, pydantic is a required dependency and is always imported.
- **strictcli for CLI**: the CLI uses `strictcli.App` with `config=True`, which provides config subcommands automatically.
- **PID files are optional**: `run()` and `serve()` accept `pid_path=None` (the default). PID files are only created when the caller explicitly provides a path.

## Relationship to fastware

All ASGI, server, middleware, SSE, auth, DI, testing, logging, tasks, features, error_log, audit, config, MCP framework, and dev-mode work should happen in [fastware](https://github.com/smm-h/fastware), not wesktop. wesktop only changes for:

- Desktop-specific features (pywebview integration, desktop entries, single-instance)
- SDUI primitives
- MCP tool implementations (the concrete tools, not the MCP framework)
- CLI commands
- Re-export stub updates (when fastware adds new public symbols)

## Project structure

```
src/wesktop/         Source code (4 real modules + mcp_tools/ + 15 re-export stubs)
tests/               Test suite (8 test modules, 131 tests)
docs/                Documentation (selfdoc templates)
todo/                Planned work items
```
