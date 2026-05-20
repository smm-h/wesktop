---
title: wesktop
description: wesktop is a Python framework for building web-based desktop apps with an ASGI micro-router, SSE broadcaster, granian server, and pywebview native windows
date: 2026-05-19
---

# wesktop

wesktop is a Python framework for building web-based desktop applications. It provides an ASGI micro-router, an SSE broadcaster, and integration with granian (a Rust-based ASGI server) and pywebview (native OS windows). You define routes in Python, serve them over HTTP, and optionally open a native desktop window -- all from a single entry point.

## Installation

```bash
pip install wesktop
```

## Minimal Desktop App

```python
import wesktop

router = wesktop.Router()

@router.get("/api/health")
async def health(req: wesktop.Request):
    return {"status": "ok"}

app = wesktop.create_app(router)

# Opens a native desktop window pointing at the server
wesktop.run("myapp:app", title="My App", width=1024, height=768)
```

`wesktop.run()` starts granian in a background thread and opens a pywebview window. When the window closes, the process exits.

## Headless Server

If you don't need a desktop window -- for example during development, in CI, or for server-only deployment -- use `serve()` instead of `run()`. This starts granian in blocking mode on the specified host and port without opening a pywebview window, making it suitable for any environment where a GUI is unavailable or unnecessary.

```python
import wesktop

router = wesktop.Router()

@router.get("/api/ping")
async def ping(req: wesktop.Request):
    return wesktop.TextResponse("pong")

app = wesktop.create_app(router)

# Blocks the process, serving on 127.0.0.1:8000
wesktop.serve("myapp:app", host="127.0.0.1", port=8000)
```

## SSE (Server-Sent Events)

wesktop includes a `Broadcaster` class that manages SSE client connections with typed events. Event types must be registered before broadcast (strict mode), and disconnected clients are pruned automatically when their async queue fills. Each client gets its own queue with a configurable buffer size (default 256 messages), so slow consumers do not block fast producers.

```python
import wesktop

router = wesktop.Router()
sse = wesktop.Broadcaster()

# Register allowed event types
sse.register_event("status")
sse.register_event("progress")

# Wire the SSE stream to a route
router.add_route("GET", "/events", wesktop.sse_route(sse))

@router.get("/api/notify")
async def notify(req: wesktop.Request):
    sse.broadcast("status", {"message": "build complete"})
    return {"sent": True}

app = wesktop.create_app(router)
```

Clients connect to `/events` and receive typed SSE messages. The broadcaster prunes disconnected clients automatically.

## Response Types

wesktop provides 6 response types covering the most common HTTP content patterns. Route handlers can return a plain `dict` or `list` for automatic JSON serialization, or use an explicit response class for full control over status codes, headers, and content types. All JSON encoding uses msgspec for speed.

| Type | Content-Type | Notes |
|------|-------------|-------|
| `dict` / `list` | `application/json` | Auto-wrapped in `JSONResponse` |
| `JSONResponse` | `application/json` | Explicit status code |
| `TextResponse` | configurable | Plain text, CSS, etc. |
| `HTMLResponse` | `text/html` | HTML pages |
| `BytesResponse` | configurable | Raw bytes (images, files) |
| `StreamResponse` | configurable | Async generator (SSE, chunked) |

## API Reference

The full API reference documents every public symbol in the `wesktop` package, including the router, request and response types, SSE broadcaster, server lifecycle functions, and desktop entry helpers. The library exposes 15 public symbols, all importable directly from `wesktop`. See [API docs](api.md) for the complete reference.
