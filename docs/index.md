---
title: wesktop
description: A Python framework for building web-based desktop apps -- built on fastware with pywebview native windows, desktop entry management, and SDUI primitives
date: 2026-07-01
---

# wesktop :-: var key="project.version"

wesktop is a Python framework for building web-based desktop applications. It combines [fastware](https://docs.smmh.dev/fastware) (an ASGI micro-framework with routing, SSE, middleware, auth, and server lifecycle) with [pywebview](https://pywebview.flowrl.com/) (native OS windows) to let you write Python backends that open as desktop apps -- or run headless as web servers.

## Built on fastware

wesktop re-exports the entire fastware API so consumers can `import wesktop` and get routing, responses, SSE, middleware, auth, dependency injection, config loading, background tasks, feature flags, audit logging, and test clients -- all without importing fastware directly. The fastware layer handles everything HTTP/ASGI; wesktop adds the desktop shell on top:

- **Desktop window** -- start a granian server in a background thread, open a native OS window via pywebview, block until the user closes it
- **Desktop entries** -- create and remove platform-native application shortcuts (Linux `.desktop` files, macOS `.app` bundles, Windows Start Menu shortcuts)
- **SDUI primitives** -- 39 server-driven UI node types (layout, display, data, input, feedback, overlay) for building dynamic dashboards without shipping frontend code
- **Dev mode** -- Vite integration for frontend hot-reload during development
- **GUI backend detection** -- automatic discovery of system PyGObject/Qt in isolated venvs

For ASGI routing, middleware, auth, SSE, and server lifecycle documentation, see the [fastware docs](https://docs.smmh.dev/fastware).

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

`wesktop.run()` starts granian in a background thread and opens a pywebview window. When the window closes, the server keeps running independently. The server binds to a random available port by default in desktop mode, so multiple instances do not collide.

## Headless Server

If you don't need a desktop window -- for example during development, in CI, or for server-only deployment -- use `serve()` instead of `run()`.

```python
import wesktop

router = wesktop.Router()

@router.get("/api/ping")
async def ping(req: wesktop.Request):
    return wesktop.TextResponse("pong")

app = wesktop.create_app(router)

# Blocks the process, serving on 127.0.0.1:8000
wesktop.serve("myapp:app", foreground=True, host="127.0.0.1", port=8000)
```

## Development Mode

For frontend development with Vite hot-reload:

```python
import wesktop

router = wesktop.Router()

@router.get("/api/data")
async def data(req: wesktop.Request):
    return {"items": [1, 2, 3]}

app = wesktop.create_app(router)

# Starts Vite dev server + granian backend
wesktop.dev("myapp:app", vite_port=5173)
```

## SSE (Server-Sent Events)

wesktop includes a `Broadcaster` class (from fastware) that manages SSE client connections with typed events. Event types must be registered before broadcast (strict mode), and disconnected clients are pruned automatically.

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

## Desktop Entries

Create platform-native application shortcuts so users can launch your app from their OS launcher:

```python
import wesktop

# Create a desktop shortcut
path = wesktop.create_entry(
    name="My App",
    command="/path/to/myapp-open",
    icon="/path/to/icon.png",
    comment="My wesktop application",
)

# Remove it later
wesktop.remove_entry("My App")
```

When using `wesktop.run()`, desktop entries are created automatically on first launch and self-heal if the launcher script goes missing (e.g., after reinstalling to a different venv).

## API Reference

See the [API docs](api.md) for wesktop-native symbols (desktop window, entries, SDUI). For ASGI routing, middleware, auth, SSE, and server lifecycle, see the [fastware API docs](https://docs.smmh.dev/fastware/api.html).
