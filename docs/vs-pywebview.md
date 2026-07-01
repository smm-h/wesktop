---
title: wesktop vs pywebview
description: What wesktop adds on top of bare pywebview
date: 2026-07-01
---

# wesktop vs pywebview

wesktop is built on pywebview. It uses pywebview to open native OS windows -- there is no fork, no wrapper, no replacement. This page explains what wesktop adds on top of bare pywebview and when you might want one over the other.

## What pywebview provides

pywebview is a lightweight cross-platform library that opens a native webview window and points it at a URL or local HTML. It supports:

- Native windows on Linux (WebKit via GTK), macOS (WebKit), and Windows (Edge WebView2)
- Loading URLs or HTML strings
- Python-to-JavaScript bridge (`js_api`)
- Window management (title, size, fullscreen, minimize, etc.)
- File dialogs
- Multiple window support

pywebview does NOT provide a web server, routing, middleware, or any backend framework. You bring your own.

## What wesktop adds

### ASGI routing (via fastware)

Instead of serving raw HTML or running a separate Flask/FastAPI server, wesktop provides a built-in ASGI micro-router:

```python
import wesktop

router = wesktop.Router()

@router.get("/api/users/{id}")
async def get_user(req: wesktop.Request):
    user_id = req.path_params["id"]
    return {"id": user_id, "name": "Alice"}

app = wesktop.create_app(router)
wesktop.run("myapp:app", title="User Manager")
```

With bare pywebview, you would need to set up a separate HTTP server, manage its lifecycle, and coordinate startup/shutdown yourself.

### SSE broadcasting

Built-in server-sent events with typed event registration, per-client async queues, and automatic dead client pruning:

```python
sse = wesktop.Broadcaster()
sse.register_event("update")
router.add_route("GET", "/events", wesktop.sse_route(sse))
```

### Server lifecycle management

wesktop handles the full granian server lifecycle:

- PID file management for single-instance enforcement
- Port availability checks (random port allocation in desktop mode)
- Background server startup with URL return for the webview
- Graceful shutdown coordination
- `serve()` for headless mode, `serve_background()` for desktop mode

### Middleware suite

Via fastware, wesktop includes production-ready middleware:

- **CORSMiddleware** -- cross-origin resource sharing
- **CSRFMiddleware** -- cross-site request forgery protection
- **RequestIDMiddleware** -- unique ID per request for tracing
- **RequestTimingMiddleware** -- response time headers
- **TrustedHostMiddleware** -- host header validation
- **ViteDevProxy** -- proxy frontend requests to Vite dev server

### Auth system

JWT token creation/verification, password hashing, role-based access control, session cookies, and rate limiting -- all built-in via fastware.

### Desktop entry creation

Automatic creation and removal of platform-native application shortcuts:

```python
# Happens automatically on first wesktop.run() call
# Or manually:
wesktop.create_entry("My App", "/path/to/launcher", icon="/path/to/icon.png")
```

On Linux this writes a `.desktop` file. On macOS it creates an `.app` bundle. On Windows it creates a Start Menu shortcut. `wesktop.run()` creates entries automatically and self-heals broken launchers.

### CLI diagnostics

The `wesktop` CLI provides runtime diagnostics and configuration management:

```bash
wesktop diagnose    # Python version, dependency versions, platform info
wesktop config show # Current configuration
```

### SDUI primitives

39 server-driven UI node types (layout, display, data, input, feedback, overlay) for building dynamic dashboards without shipping frontend code.

### GUI backend detection

`wesktop.ensure_gui_backend()` automatically finds system-installed PyGObject or Qt when running in an isolated virtual environment. This solves a common pain point with pywebview on Linux, where the GTK bindings are installed system-wide but invisible to venv-isolated packages.

### Development mode

`wesktop.dev()` starts a Vite dev server alongside the granian backend for frontend hot-reload during development.

## Side-by-side

| Capability | pywebview | wesktop |
|-----------|-----------|---------|
| Native webview window | Yes | Yes (uses pywebview) |
| HTTP routing | No (bring your own) | Built-in ASGI router |
| Server lifecycle | Manual | Managed (PID files, port allocation, background startup) |
| SSE | No | Built-in Broadcaster |
| Middleware | No | CORS, CSRF, request ID, timing, trusted hosts, Vite proxy |
| Auth | No | JWT, password hashing, RBAC, rate limiting |
| Desktop entries | No | Built-in (Linux, macOS, Windows) |
| CLI | No | `wesktop diagnose`, `wesktop config` |
| SDUI | No | 39 node types |
| Dev mode | No | Vite + granian hot-reload |
| Dependencies | pywebview only | pywebview + granian + fastware + msgspec |

## When to use bare pywebview

Use pywebview directly if you already have a web server (Flask, FastAPI, Django) and just need to wrap it in a native window. pywebview is a thin layer with minimal opinions -- if you want full control over your server stack, it stays out of the way.

## When to use wesktop

Use wesktop if you want a batteries-included desktop app framework: routing, SSE, middleware, auth, desktop entries, SDUI, and server lifecycle management -- all wired together and ready to go with a single `pip install wesktop`.
