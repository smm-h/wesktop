---
title: wesktop
description: wesktop provides an ASGI router, SSE broadcaster, granian server, and pywebview integration for building web-based desktop apps in Python
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

If you don't need a desktop window (e.g., for development or server-only deployment), use `serve()` instead:

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

wesktop includes a `Broadcaster` that manages SSE client connections with typed events:

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

Route handlers return one of:

| Type | Content-Type | Notes |
|------|-------------|-------|
| `dict` / `list` | `application/json` | Auto-wrapped in `JSONResponse` |
| `JSONResponse` | `application/json` | Explicit status code |
| `TextResponse` | configurable | Plain text, CSS, etc. |
| `HTMLResponse` | `text/html` | HTML pages |
| `BytesResponse` | configurable | Raw bytes (images, files) |
| `StreamResponse` | configurable | Async generator (SSE, chunked) |

## API Reference

See [API docs](api.md) for the full reference.
