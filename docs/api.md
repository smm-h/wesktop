---
title: API Reference
description: "API reference for wesktop's native symbols: run() desktop window, GUI backend detection, desktop entries, dev mode, SDUI primitives, and version metadata."
date: 2026-07-01
---

# API Reference

wesktop exposes 117 public symbols via `import wesktop`. Most of these are re-exports from [fastware](https://docs.smmh.dev/fastware) -- the ASGI micro-framework that provides routing, responses, SSE, middleware, auth, dependency injection, config, testing, server lifecycle, background tasks, feature flags, audit logging, error logging, and MCP support. For documentation on those symbols, see the [fastware API reference](https://docs.smmh.dev/fastware/api.html).

This page documents the symbols that are native to wesktop -- the desktop shell, entry management, SDUI primitives, GUI backend detection, and dev mode. The library is validated by 271 tests across 13 test modules.

## Desktop Window

The desktop module provides the `run()` function for launching native OS windows backed by a Granian ASGI server in a daemon thread. The pywebview dependency is late-imported, so headless deployments that only use `serve()` never load the GUI library.

:-: ref path="src.wesktop.desktop"

### `wesktop.run(target, *, title, width, height, icon, host, port, pid_path, name, pre_serve, reload, js_api, single_instance, second_open)`

Start a detached granian server subprocess and open a native desktop window via pywebview. Blocks until the user closes the window. This is the primary entry point for desktop applications.

The `target` parameter is an ASGI import path (e.g., `"myapp:app"`) or a callable. pywebview is late-imported so headless environments that only use `serve()` never load the GUI dependency. In desktop mode the server binds to a random available port by default (port 0), so multiple instances do not collide.

When `single_instance=True` (the default), `run()` checks for an already-running server. If found, the behavior depends on `second_open`:

- `second_open="new-window"` (default): opens an additional native window joined to the running server. Windows are refcounted across processes via marker files; the server stops only when the last window (in any process) closes.
- `second_open="focus-existing"`: does NOT open a new window. Drops a platform-neutral, file-based focus-request marker and exits. The process that owns the window raises it via a ~1s poll. Raising above other applications is window-manager dependent and best-effort. No DBus, no AppleEvents.

Note: `pre_serve` and `reload` are hard errors on `run()` because the desktop server runs as a detached subprocess that re-imports the target. Use `wesktop.serve()` for both.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `target` | `str \| Callable` | required | ASGI module path or callable |
| `title` | `str` | `"wesktop"` | Window title |
| `width` | `int` | `1280` | Window width in pixels |
| `height` | `int` | `800` | Window height in pixels |
| `icon` | `str \| None` | `None` | Path to window icon |
| `host` | `str \| None` | `None` | Bind address (default: `127.0.0.1`) |
| `port` | `int \| None` | `None` | Bind port (default: random) |
| `pid_path` | `Path \| None` | `None` | PID file for lifecycle management. Defaults to a stable per-app path under the platform state directory when not provided. |
| `name` | `str` | `"WESKTOP"` | Server name for logging |
| `pre_serve` | `Callable \| None` | `None` | Not supported in `run()` (hard error). Use `serve()` instead. |
| `reload` | `bool` | `False` | Not supported in `run()` (hard error). Use `serve()` instead. |
| `js_api` | `object \| None` | `None` | Python object exposed to JavaScript via `window.pywebview.api` |
| `single_instance` | `bool` | `True` | Join existing instance if one is running |
| `second_open` | `str` | `"new-window"` | Second-launch behavior: `"new-window"` opens another window; `"focus-existing"` signals the existing window and exits |

### `wesktop.ensure_gui_backend()`

Make pywebview's GUI backend importable in isolated virtual environments. If `gi` (PyGObject) is not importable, searches common system site-packages locations (Linux, macOS Homebrew, macOS Framework) and adds the first match to `sys.path`. Returns `True` if a backend is available, `False` otherwise. Called automatically by `run()`.

### Cross-process window refcounting

`run()` coordinates window lifecycle across multiple OS processes through filesystem markers in the fastware instance-registry directory. Each open window writes a marker file (`{pid, window_id}`) before `webview.start()` and removes it after the window closes. The server is stopped only when zero live window markers remain (dead PIDs pruned by liveness checks via `kill -0`). This means one process closing its last window never kills the server while another process still has a window open.

### `wesktop.desktop.list_app_instances(pid_path)`

Enumerate the app's live server instance(s) and open window markers. Returns an `AppInstances` dataclass with two fields:

| Field | Type | Description |
|-------|------|-------------|
| `servers` | `list` | Registered server descriptors (from the fastware instance registry) |
| `windows` | `list` | Live per-window marker payloads (dicts with `pid` and `window_id`) |

Stale entries are pruned automatically by the underlying registry reads.

### Runtime bridge (`wesktop.runtime_bridge`)

The runtime bridge is the host-side complement to the page-side update path. Native windows load the same page as the browser, so the framework's `/__fastware/client.js` reloads the page via SSE when the build id changes -- that is the primary update path, requiring no host involvement and no polling.

The runtime bridge provides host-side functions for reset and reload flows:

| Function | Description |
|----------|-------------|
| `reload(window)` | Reload the page by injecting `location.reload()` |
| `clear_web_cache(window)` | Best-effort cache clear: native `clear_cache` if available, otherwise clears Cache Storage API via injected JS |
| `fetch_build_id(version_url)` | GET `/__fastware/version` and return the `build_id` string, or `None` on any failure |
| `check_and_reload(window, version_url, last_build_id)` | Probe the version endpoint; reload the window if the build id differs from `last_build_id` |
| `install_focus_poll(window, version_url)` | Wire a version poll to the window's focus event (if pywebview exposes one). Returns `True` if wired, `False` otherwise. On builds without a focus event this is a no-op; the page-side `client.js` remains the update path. |

Build ids have no ordering: reload happens on a DIFFERENT id, not a "newer" one.

## Desktop Entries

Cross-platform desktop shortcut creation and removal for all 3 major operating systems. On Linux, creates freedesktop-compliant `.desktop` files in `~/.local/share/applications/` with optional icon installation to `~/.local/share/icons/`. On macOS, generates `.app` bundles in `~/Applications/` with `Info.plist` and launcher scripts. On Windows, creates Start Menu shortcuts via COM automation with a PowerShell fallback.

:-: ref path="src.wesktop.entries"

### `wesktop.create_entry(name, command, *, icon, comment, categories)`

Create a platform-native desktop entry so users can launch a wesktop application from their OS application launcher. On Linux, this writes a freedesktop-compliant `.desktop` file with optional icon installation; on macOS, it creates an `.app` bundle with an `Info.plist` and launcher shell script; on Windows, it creates a Start Menu shortcut using COM automation with a PowerShell fallback:

| Platform | What it creates |
|----------|----------------|
| Linux | `.desktop` file in `~/.local/share/applications/` with optional icon copy to `~/.local/share/icons/` |
| macOS | `.app` bundle in `~/Applications/` with `Info.plist` and launcher script |
| Windows | Start Menu shortcut via COM (`win32com`) or PowerShell fallback |

Returns the `Path` of the created entry.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | `str` | required | Application name |
| `command` | `str` | required | Shell command to execute |
| `icon` | `str \| Path \| None` | `None` | Path to icon file or theme icon name |
| `comment` | `str` | `""` | Application description |
| `categories` | `str` | `"Utility;"` | Desktop entry categories (Linux only) |

### `wesktop.remove_entry(name)`

Remove a previously created desktop entry by its registered name. Searches the platform-specific location (Linux `~/.local/share/applications/`, macOS `~/Applications/`, Windows Start Menu folder) and deletes both the entry and any installed icon. Returns `True` if the entry was found and removed, `False` if no entry with that name existed.

## Development Mode

### `wesktop.dev(target, *, vite_command, vite_port, host, port, pid_path, name, pre_serve)`

Development mode with Vite frontend hot-reload. Starts a Vite dev server as a subprocess alongside the granian ASGI backend, proxying unmatched frontend requests through `ViteDevProxy` middleware. Polls the Vite port for readiness (up to 15 seconds) and terminates the Vite process automatically when the server shuts down.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `target` | `str \| Callable` | required | ASGI module path or callable |
| `vite_command` | `str` | `"npm run dev"` | Command to start Vite |
| `vite_port` | `int` | `5173` | Port Vite listens on |
| `host` | `str \| None` | `None` | Backend bind address |
| `port` | `int \| None` | `None` | Backend bind port |
| `pid_path` | `Path \| None` | `None` | PID file path |
| `name` | `str` | `"WESKTOP"` | Server name for logging |
| `pre_serve` | `Callable \| None` | `None` | Callback invoked before starting the server |

## SDUI Primitives

The SDUI system provides 40 Pydantic-validated node types organized into 6 categories (layout, display, data, input, feedback, overlay) for building dynamic dashboards entirely from the server without shipping custom frontend code.

:-: ref path="src.wesktop.sdui" target="SDUINode"

wesktop includes 40 server-driven UI node types for building dynamic dashboards without shipping frontend code. Each model serializes to the `{"type", "props", "children"}` dict shape expected by the SDUI renderer.

For the full list of SDUI primitives (layout, display, data, input, feedback, overlay), see the [auto-generated SDUI reference](src-wesktop-sdui.html).

### Grouping

:-: table-sdui

### Quick example

```python
from wesktop.sdui import Stack, Button, Heading, node

# Using model classes
layout = Stack(children=[
    Heading(text="Dashboard", level=1).to_node(),
    Button(label="Deploy", variant="primary", command="deploy").to_node(),
])

# Using the node() helper
tree = node("stack", [node("heading", text="Hello", level=2)])
```

### SDUI provider registry

The SDUI module includes a provider registry for named async callables that produce UI trees and initial state.

#### `wesktop.register_sdui_provider(name, provider)`

Register an SDUI provider by name. A provider is an async callable that returns `(ui_tree, initial_state)` -- a tuple of two dicts. The UI tree is the serialized SDUI node structure; the initial state is arbitrary data passed alongside it.

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | `str` | Unique provider name |
| `provider` | `Callable[[], Awaitable[tuple[dict, dict]]]` | Async callable returning `(ui_tree, initial_state)` |

#### `wesktop.get_sdui_provider(name)`

Return the SDUI provider registered under `name`, or `None` if not registered.

#### `wesktop.list_sdui_providers()`

Return a list of all registered SDUI provider names.

## Fastware Re-exports

The following 15 modules are re-exported from fastware, providing the full ASGI framework stack (routing, responses, middleware, auth, DI, testing, server lifecycle, and more) without requiring a separate `import fastware` statement. See the [fastware API docs](https://docs.smmh.dev/fastware/api.html) for full documentation.

| wesktop module | fastware source | Provides |
|---------------|----------------|----------|
| `wesktop.asgi` | `fastware.routing`, `fastware.request`, `fastware.responses`, `fastware.app`, `fastware.types`, `fastware.websocket` | Router, Request, response types, create_app, WebSocket |
| `wesktop.sse` | `fastware.sse` | Broadcaster, sse_route |
| `wesktop.server` | `fastware.server` | serve, serve_background, stop, status, ServerStatus |
| `wesktop.middleware` | `fastware.middleware` | CORSMiddleware, RequestIDMiddleware, RequestTimingMiddleware, TrustedHostMiddleware, ViteDevProxy |
| `wesktop.auth` | `fastware.auth` | create_token, verify_token, hash_password, verify_password, JSONFileUserStore, CSRFMiddleware, rate_limit |
| `wesktop.di` | `fastware.di` | DependencyResolver |
| `wesktop.config` | `fastware.config` | load_config |
| `wesktop.testing` | `fastware.testing` | AsyncTestClient, TestClient |
| `wesktop.features` | `fastware.features` | FeatureFlags |
| `wesktop.audit` | `fastware.audit` | AuditLog |
| `wesktop.tasks` | `fastware.tasks` | BackgroundTask, TaskRegistry |
| `wesktop.error_log` | `fastware.error_log` | ErrorLog |
| `wesktop.logging` | `fastware.logging` | configure_logging, get_logger, init_sentry |
| `wesktop.mcp` | `fastware.mcp` | create_mcp_server, register_tools_for_role |
| `wesktop.dev` | `fastware.dev` | dev mode internals |

## Metadata

### `__version__`

Package version string, read from `importlib.metadata` at import time. Follows semantic versioning (currently 0.x.x, pre-stable). Available via `import wesktop; wesktop.__version__` in Python code and `wesktop --version` from the command line. The version is set in `pyproject.toml` and bumped automatically by rlsbl during releases.
