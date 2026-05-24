# wesktop

A Python framework for building web-based desktop applications. Provides an ASGI micro-router, SSE broadcaster, granian server integration, pywebview native windows, and cross-platform desktop entry creation -- all from a single `import wesktop`.

## Architecture

wesktop has 5 layers, each in its own module:

1. **ASGI micro-router** (`asgi.py`) -- minimal HTTP routing with `{param}` placeholders, response type dispatch (JSON, text, HTML, bytes, streaming), static file serving, SPA fallback, WebSocket route registry, middleware chain, and async lifespan support. Zero external dependencies beyond msgspec for JSON encoding.

2. **SSE broadcaster** (`sse.py`) -- typed server-sent events with per-client async queues. Event types must be registered before broadcast (strict mode). Disconnected clients are pruned automatically when their queue fills up.

3. **Server lifecycle** (`server.py`) -- granian integration with PID file management, port availability checks, process group leadership (so worker subprocesses die with the parent), and signal handling. Supports both blocking (`start_server`) and background-thread (`start_server_in_background`) modes.

4. **Desktop window** (`desktop.py`) -- pywebview integration. Starts the server in a background thread, opens a native OS window, and blocks until the window is closed. Late-imports pywebview so headless mode has no GUI dependency.

5. **Desktop entries** (`entries.py`) -- cross-platform desktop shortcut creation and removal (Linux `.desktop` files, macOS `.app` bundles, Windows Start Menu shortcuts via COM or PowerShell).

## Module Layout

```
src/wesktop/
  __init__.py     Public API: re-exports from all modules, __version__, __all__ (15 symbols)
  asgi.py         ASGI router, request/response types, app factory, WebSocket registry
  sse.py          SSE Broadcaster and sse_route helper
  server.py       Granian lifecycle: PID files, port checks, start/stop
  desktop.py      pywebview window: start server + open native window
  entries.py      Cross-platform desktop entry creation/removal
  cli.py          CLI entry point (strictcli App): diagnose, config
  __main__.py     Enables `python -m wesktop`
```

## Dependencies

| Package | Why |
|---------|-----|
| `granian` | Rust-based ASGI server. Faster cold start than uvicorn, handles process management internally. |
| `pywebview` | Opens native OS windows (WebKit on Linux/macOS, Edge WebView2 on Windows). Avoids Electron overhead. |
| `msgspec` | Fast JSON serialization/deserialization. Used in the ASGI layer for request parsing and response encoding. |
| `strictcli` | CLI framework with built-in config management. Powers the `wesktop` CLI. |

**Optional:**

| Package | Why |
|---------|-----|
| `mcp` | MCP server support for role-based agent tool provisioning. Only needed if using `create_mcp_server`. Install with `pip install mcp`. |

Dev dependencies: `pytest`, `httpx` (async test client). 122 tests across 7 test modules.

## Consumer Patterns

### Library-only use

Consumers bring their own entry point and call either:

- `wesktop.run("myapp:app")` -- desktop mode (server + native window)
- `wesktop.serve("myapp:app")` -- headless mode (server only)

The `target` argument is an ASGI import path (e.g., `"myapp.web:app"`). Consumers create a `Router`, register routes, call `create_app()`, and pass the module path to `run()` or `serve()`.

### CLI use

The `wesktop` CLI (via `strictcli`) provides diagnostics and configuration:

- `wesktop diagnose` -- print runtime environment: Python version, dependency versions and backends, platform, config path
- `wesktop config show` -- display current configuration
- `wesktop config set <key> <value>` -- set a config value
- `wesktop config edit` -- open config file in `$EDITOR`
- `wesktop config path` -- print the config file path
- `wesktop --version` -- print package version
- `wesktop --help` -- list available commands

The CLI is also available as an npm shim: `npx wesktop diagnose`.

## Public API

All public symbols are importable from `wesktop` directly:

- **Router, Request** -- routing and request handling
- **JSONResponse, TextResponse, HTMLResponse, BytesResponse, StreamResponse** -- response types
- **create_app** -- ASGI app factory
- **add_ws_route** -- WebSocket route registration
- **Broadcaster, sse_route** -- SSE support
- **create_entry, remove_entry** -- desktop shortcut management
- **run, serve** -- entry points
- **__version__** -- package version from metadata

## Development

```bash
uv sync                    # Install dependencies
uv run pytest              # Run 122 tests
selfdoc build              # Build documentation site
selfdoc serve              # Serve docs locally
selfdoc check              # Lint docs for SEO and staleness
```

## Conventions

- **Late imports for pywebview**: `desktop.py` imports `webview` inside `run()`, not at module level. This ensures headless consumers (`serve()`) never load the GUI dependency.
- **msgspec for all serialization**: JSON encoding/decoding in the ASGI layer uses msgspec, not `json` stdlib. This applies to `JSONResponse`, `Request.json`, and any internal serialization.
- **PID files are optional**: both `run()` and `serve()` accept `pid_path=None` (the default). PID files are only created when the caller explicitly provides a path.
- **SSE typed events**: `Broadcaster` enforces event type registration in strict mode (default). Calling `broadcast()` with an unregistered event name raises `ValueError`.
- **strictcli for CLI**: the CLI uses `strictcli.App` with `config=True`, which provides config subcommands automatically.

## Project Structure

```
src/wesktop/         Source code (5 core modules + CLI)
tests/               Test suite (7 test modules, 122 tests)
docs/                Documentation (selfdoc templates)
todo/                Planned work items
```
