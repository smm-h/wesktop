---
title: API Reference
description: Public API surface of webpane
date: 2026-05-19
---

# API Reference

All symbols listed here are importable directly from `webpane`.

## Top-Level Functions

### `webpane.run(target, *, title, width, height, icon, host, port, pid_path)`

Start a granian server in a background thread and open a native desktop window via pywebview. Blocks until the window is closed.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `target` | `str` | required | ASGI module path (e.g. `"myapp:app"`) |
| `title` | `str` | `"webpane"` | Window title |
| `width` | `int` | `1280` | Window width in pixels |
| `height` | `int` | `800` | Window height in pixels |
| `icon` | `str \| None` | `None` | Path to window icon |
| `host` | `str` | `"127.0.0.1"` | Bind address |
| `port` | `int` | `8000` | Bind port |
| `pid_path` | `Path \| None` | `None` | PID file for lifecycle management |

### `webpane.serve(target, *, host, port, pid_path, name)`

Start granian in blocking/headless mode (no desktop window).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `target` | `str` | required | ASGI module path |
| `host` | `str` | `"127.0.0.1"` | Bind address |
| `port` | `int` | `8000` | Bind port |
| `pid_path` | `Path \| None` | `None` | PID file for lifecycle management |
| `name` | `str` | `"webpane"` | Server name (used in log messages) |

## Routing

### `Router`

Simple path-based HTTP router using `{param}` placeholders.

- `router.get(path)` -- decorator to register a GET handler
- `router.post(path)` -- decorator to register a POST handler
- `router.delete(path)` -- decorator to register a DELETE handler
- `router.add_route(method, path, handler)` -- programmatic route registration
- `router.match(method, path)` -- returns `(handler, path_params)` or `None`

### `create_app(router, *, middleware, static_dir, static_path, spa_fallback, lifespan, name)`

Create an ASGI application callable from a router.

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

Register a raw ASGI WebSocket handler for an exact path. The handler signature is `(scope, receive, send) -> None`.

## Request

### `Request`

Wraps the ASGI scope with parsed body and query helpers.

- `request.scope` -- raw ASGI scope dict
- `request.path_params` -- dict of `{param}` captures from route matching
- `request.json` -- parsed JSON body (or `None`)
- `request.body` -- raw `bytes` body (or `None`)
- `request.body_size` -- length in bytes of the raw body
- `request.query(name, default=None, type_=str)` -- get a query parameter with optional type conversion
- `request.header(name, default=None)` -- get a request header (case-insensitive)

## Response Types

### `JSONResponse(data, status=200)`

JSON-encoded response. `data` can be any msgspec-serializable value.

### `TextResponse(text, content_type="text/plain", status=200, headers=None)`

Plain text response with configurable content type and extra headers.

### `HTMLResponse(html, status=200)`

HTML response.

### `BytesResponse(data, content_type="application/octet-stream", status=200)`

Raw bytes response with explicit content type.

### `StreamResponse(generator, content_type, headers=None)`

Streaming response backed by an async generator. Used internally by SSE, but available for any chunked response pattern.

## SSE

### `Broadcaster(buffer_size=256, *, strict=True)`

Manages SSE client connections and broadcasts typed events.

- `broadcaster.register_event(name)` -- declare an allowed event type
- `broadcaster.event_types` -- `frozenset` of registered event types
- `broadcaster.broadcast(event, data)` -- send an event to all connected clients; prunes full queues
- `broadcaster.stream(request)` -- return a `StreamResponse` for an SSE endpoint
- `broadcaster.client_count` -- number of currently connected clients

In strict mode (the default), `broadcast()` raises `ValueError` if the event type was not previously registered.

### `sse_route(broadcaster)`

Return an async handler suitable for `router.add_route("GET", "/events", handler)`.

## Desktop Entries

### `create_entry(name, command, *, icon, comment, categories)`

Create a platform-native desktop entry (Linux `.desktop`, macOS `.app` bundle, Windows Start Menu shortcut). Returns the path of the created entry.

### `remove_entry(name)`

Remove a desktop entry by name. Returns `True` if something was removed.

## Metadata

### `__version__`

Package version string, read from `importlib.metadata` at import time.
