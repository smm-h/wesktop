---
title: API Reference
description: Complete API reference for wesktop covering the ASGI router, request and response types, SSE broadcaster, server lifecycle, and desktop entry helpers
date: 2026-05-19
---

# API Reference

All 15 public symbols listed here are importable directly from `wesktop`. The package re-exports everything from its 5 internal modules (`asgi`, `sse`, `server`, `desktop`, `entries`) so consumers never need to import submodules. Each function and class below includes its full signature, parameter table, and usage notes. The library is validated by 122 tests covering all modules.

## Top-Level Functions

### `wesktop.run(target, *, title, width, height, icon, host, port, pid_path)`

Start a granian server in a background thread and open a native desktop window via pywebview. The function blocks until the user closes the window, at which point the server is shut down and the process exits. This is the primary entry point for desktop applications. The `target` parameter is an ASGI import path like `"myapp:app"`. pywebview is late-imported so headless environments that only use `serve()` never load the GUI dependency.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `target` | `str` | required | ASGI module path (e.g. `"myapp:app"`) |
| `title` | `str` | `"wesktop"` | Window title |
| `width` | `int` | `1280` | Window width in pixels |
| `height` | `int` | `800` | Window height in pixels |
| `icon` | `str \| None` | `None` | Path to window icon |
| `host` | `str` | `"127.0.0.1"` | Bind address |
| `port` | `int` | `8000` | Bind port |
| `pid_path` | `Path \| None` | `None` | PID file for lifecycle management |

### `wesktop.serve(target, *, host, port, pid_path, name)`

Start granian in blocking/headless mode without opening a desktop window. Use this for development, server-only deployment, or any environment where a GUI is unavailable. The function blocks the calling thread indefinitely, binding to the specified host and port. An optional PID file enables external lifecycle management (stop, restart) by other processes or scripts.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `target` | `str` | required | ASGI module path |
| `host` | `str` | `"127.0.0.1"` | Bind address |
| `port` | `int` | `8000` | Bind port |
| `pid_path` | `Path \| None` | `None` | PID file for lifecycle management |
| `name` | `str` | `"wesktop"` | Server name (used in log messages) |

## Routing

### `Router`

Simple path-based HTTP router that matches incoming requests against registered routes using `{param}` placeholders for dynamic path segments. Routes are registered via method-specific decorators (`get`, `post`, `delete`) or the generic `add_route` method. The router performs no regex compilation -- matching is a direct string comparison with placeholder extraction, keeping overhead minimal.

- `router.get(path)` -- decorator to register a GET handler
- `router.post(path)` -- decorator to register a POST handler
- `router.delete(path)` -- decorator to register a DELETE handler
- `router.add_route(method, path, handler)` -- programmatic route registration
- `router.match(method, path)` -- returns `(handler, path_params)` or `None`

### `create_app(router, *, middleware, static_dir, static_path, spa_fallback, lifespan, name)`

Create an ASGI application callable from a router. This is the factory function that wires together routing, middleware, static file serving, SPA fallback, and async lifespan management into a single ASGI callable suitable for any ASGI server. Middleware classes are applied outermost-first, and the optional `spa_fallback` parameter enables single-page application routing by serving the specified `index.html` for any unmatched GET request.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `router` | `Router` | required | Route table |
| `middleware` | `list[type] \| None` | `None` | ASGI middleware classes (applied outermost-first) |
| `static_dir` | `Path \| None` | `None` | Directory to serve static files from |
| `static_path` | `str` | `"/assets"` | URL prefix for static files |
| `spa_fallback` | `Path \| None` | `None` | Path to `index.html` for SPA routing |
| `lifespan` | `Callable \| None` | `None` | Async context manager for startup/shutdown |
| `name` | `str \| None` | `None` | Logger name |

### `add_ws_route(path, handler)`

Register a raw ASGI WebSocket handler for an exact path. The handler receives the standard ASGI triple `(scope, receive, send)` and is responsible for the full WebSocket lifecycle including accept, message exchange, and close. This is a module-level function that registers handlers in a global registry, separate from the `Router` instance, because WebSocket connections bypass HTTP method routing entirely. Use this when you need bidirectional communication beyond what SSE provides.

## Request

### `Request`

Wraps the ASGI scope dict with parsed body and query parameter helpers. The `Request` object is created by the ASGI app and passed to every route handler. It provides lazy JSON body parsing (decoded on first access via msgspec and cached), raw byte access with a `body_size` property, typed query parameter extraction with optional type conversion, and case-insensitive header lookup. Path parameters captured by the router are available via `path_params`.

- `request.scope` -- raw ASGI scope dict
- `request.path_params` -- dict of `{param}` captures from route matching
- `request.json` -- parsed JSON body (or `None`)
- `request.body` -- raw `bytes` body (or `None`)
- `request.body_size` -- length in bytes of the raw body
- `request.query(name, default=None, type_=str)` -- get a query parameter with optional type conversion
- `request.header(name, default=None)` -- get a request header (case-insensitive)

## Response Types

### `JSONResponse(data, status=200)`

JSON-encoded response with a `Content-Type` of `application/json`. The `data` parameter can be any value that msgspec can serialize -- dicts, lists, dataclasses, msgspec `Struct` instances, and primitive types. Route handlers that return a plain `dict` or `list` are automatically wrapped in a `JSONResponse` with status 200, so this class is only needed when you want to set an explicit status code or when returning non-dict serializable types.

### `TextResponse(text, content_type="text/plain", status=200, headers=None)`

Plain text response with a configurable content type and optional extra headers. Use this for any text-based content that is not JSON or HTML -- for example CSS files (`text/css`), plain text (`text/plain`), CSV exports (`text/csv`), or XML payloads (`application/xml`). The `headers` parameter accepts a dict of additional HTTP headers to include in the response, which is useful for setting `Content-Disposition` or caching directives.

### `HTMLResponse(html, status=200)`

HTML response with a `Content-Type` of `text/html` and a configurable status code. Use this when a route handler renders an HTML page directly rather than serving it as a static file. This is the simplest response type -- it takes an HTML string and an optional status code, with no additional configuration. For full-page applications, consider using `spa_fallback` in `create_app` instead of returning `HTMLResponse` from individual routes.

### `BytesResponse(data, content_type="application/octet-stream", status=200)`

Raw bytes response with an explicit content type. Use this for binary payloads such as images (`image/png`), PDFs (`application/pdf`), or any file download where the content is already in memory as `bytes`. The default content type is `application/octet-stream`, which triggers a download in most browsers. Set an appropriate MIME type to enable inline rendering where supported.

### `StreamResponse(generator, content_type, headers=None)`

Streaming response backed by an async generator that yields `bytes` or `str` chunks. Used internally by the SSE broadcaster to deliver server-sent events, but available for any chunked response pattern such as large file downloads, real-time log tailing, or progress streams. The generator runs lazily -- chunks are sent to the client as they are produced, without buffering the entire response in memory. Supply a `content_type` and optional `headers` dict to control the HTTP response metadata.

## SSE

### `Broadcaster(buffer_size=256, *, strict=True)`

Manages SSE client connections and broadcasts typed events to all connected clients. Each client gets its own `asyncio.Queue` with a configurable `buffer_size` (default 256 messages). In strict mode (the default), calling `broadcast()` with an unregistered event type raises `ValueError`, preventing typos from silently creating phantom event streams. Disconnected clients are pruned automatically when their queue is full, so producers never block.

- `broadcaster.register_event(name)` -- declare an allowed event type
- `broadcaster.event_types` -- `frozenset` of registered event types
- `broadcaster.broadcast(event, data)` -- send an event to all connected clients; prunes full queues
- `broadcaster.stream(request)` -- return a `StreamResponse` for an SSE endpoint
- `broadcaster.client_count` -- number of currently connected clients

In strict mode (the default), `broadcast()` raises `ValueError` if the event type was not previously registered.

### `sse_route(broadcaster)`

Return an async route handler suitable for `router.add_route("GET", "/events", handler)`. This is a convenience wrapper that creates a handler which calls `broadcaster.stream(request)` and returns the resulting `StreamResponse`. Use it to wire an SSE endpoint to a route in a single line without writing a custom handler function. The returned handler accepts a `Request` and returns a `StreamResponse` with `Content-Type: text/event-stream`.

## Desktop Entries

### `create_entry(name, command, *, icon, comment, categories)`

Create a platform-native desktop entry so users can launch a wesktop application from their OS application launcher. On Linux this writes a `.desktop` file, on macOS it creates a `.app` bundle, and on Windows it creates a Start Menu shortcut via COM or PowerShell. Returns the `Path` of the created entry. The `command` parameter is the shell command to execute when the entry is activated.

### `remove_entry(name)`

Remove a previously created desktop entry by its registered name. Returns `True` if the entry was found and removed, `False` if no entry with that name existed. On Linux this deletes the `.desktop` file from `~/.local/share/applications/`, on macOS it removes the `.app` bundle from `/Applications/`, and on Windows it deletes the Start Menu shortcut. Use this during uninstallation or when an application is renamed.

## Metadata

### `__version__`

Package version string, read from `importlib.metadata` at import time. This reflects the installed version of the wesktop package as declared in `pyproject.toml`. It follows semantic versioning (e.g. `"0.1.1"`) and is available immediately after `import wesktop`. The version is also exposed via the CLI: `wesktop --version`.
