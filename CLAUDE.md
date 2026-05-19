# webpane

A Python framework for building web-based desktop applications. Uses granian (Rust-based ASGI server), pywebview (native OS windows), and msgspec (fast serialization).

## Architecture

webpane was extracted from ProductEngine as a reusable library. It provides four layers:

1. **ASGI micro-router** (`asgi.py`) -- minimal HTTP routing with `{param}` placeholders, response type dispatch (JSON, text, HTML, bytes, streaming), static file serving, SPA fallback, WebSocket route registry, middleware chain, and async lifespan support. Zero external dependencies beyond msgspec for JSON encoding.

2. **SSE broadcaster** (`sse.py`) -- typed server-sent events with per-client async queues. Event types must be registered before broadcast (strict mode). Disconnected clients are pruned automatically when their queue fills up.

3. **Server lifecycle** (`server.py`) -- granian integration with PID file management, port availability checks, process group leadership (so worker subprocesses die with the parent), and signal handling. Supports both blocking (`start_server`) and background-thread (`start_server_in_background`) modes.

4. **Desktop window** (`desktop.py`) -- pywebview integration. Starts the server in a background thread, opens a native OS window, and blocks until the window is closed. Late-imports pywebview so headless mode has no GUI dependency.

5. **Desktop entries** (`entries.py`) -- cross-platform desktop shortcut creation and removal (Linux `.desktop` files, macOS `.app` bundles, Windows Start Menu shortcuts via COM or PowerShell).

## Module Layout

```
src/webpane/
  __init__.py     Public API: re-exports from all modules, __version__, __all__
  asgi.py         ASGI router, request/response types, app factory, WebSocket registry
  sse.py          SSE Broadcaster and sse_route helper
  server.py       Granian lifecycle: PID files, port checks, start/stop
  desktop.py      pywebview window: start server + open native window
  entries.py      Cross-platform desktop entry creation/removal
```

## Dependencies

| Package | Why |
|---------|-----|
| `granian` | Rust-based ASGI server. Faster than uvicorn for production, handles process management internally. |
| `pywebview` | Opens native OS windows (WebKit on Linux/macOS, Edge WebView2 on Windows). Avoids Electron overhead. |
| `msgspec` | Fast JSON serialization/deserialization. Used in the ASGI layer for request parsing and response encoding. |

Dev dependencies: `pytest`, `httpx` (for async test client).

## Consumer Patterns

webpane is a library, not a CLI tool. Consumers bring their own entry point and call either:

- `webpane.run("myapp:app")` -- desktop mode (server + native window)
- `webpane.serve("myapp:app")` -- headless mode (server only)

The `target` argument is an ASGI import path (e.g., `"myapp.web:app"`). Consumers create a `Router`, register routes, call `create_app()`, and then pass the module path to `run()` or `serve()`.

## Public API

All public symbols are importable from `webpane` directly:

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
uv run pytest              # Run test suite
selfdoc build              # Build documentation
selfdoc serve              # Serve documentation locally
```

## Project Structure

```
src/webpane/         Source code
tests/               Test suite
docs/                Documentation (selfdoc templates)
```
