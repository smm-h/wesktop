---
title: Getting Started
description: Build a complete web-based desktop application with wesktop, from a basic API to a real-time SDUI dashboard in a native window.
---

# Getting Started

This tutorial walks through building a complete wesktop application: a system monitor that displays CPU and memory usage in real time, with a server-driven UI dashboard and a native desktop window.

By the end you will have:

- A working ASGI app with routes
- Server-sent events pushing live data to the browser
- A server-driven UI (SDUI) dashboard rendered from Python
- A native desktop window wrapping the whole thing

## Prerequisites

- Python 3.11 or later
- A system with a GUI backend (GTK on Linux, Cocoa on macOS, EdgeWebView2 on Windows)

## Installation

Create a new project directory and install wesktop:

```bash
mkdir mymonitor && cd mymonitor
uv init
uv add wesktop
```

## Step 1: A basic app with routing

Create `app.py` with a router and two routes:

```python
import wesktop

router = wesktop.Router()


@router.get("/api/health")
async def health(request: wesktop.Request):
    return {"status": "ok"}


@router.get("/api/greeting/{name}")
async def greet(request: wesktop.Request, name: str):
    return {"message": f"Hello, {name}!"}


app = wesktop.create_app(router)
```

`Router` provides decorator methods for each HTTP verb: `get`, `post`, `put`, `patch`, `delete`. Path parameters use curly-brace syntax (`{name}`) and support type coercion (`{id:int}`, `{path:path}`). The matched parameter values are passed as keyword arguments to the handler.

Handlers receive a `Request` object and return one of:

- A plain `dict` or `list` (auto-wrapped as JSON)
- An explicit response: `JSONResponse`, `TextResponse`, `HTMLResponse`, `BytesResponse`, `StreamResponse`, or `FileResponse`

Run the app in the foreground for development:

```python
if __name__ == "__main__":
    wesktop.serve("app:app", foreground=True, host="127.0.0.1", port=8000)
```

Start it:

```bash
uv run python app.py
```

Test it:

```bash
curl http://127.0.0.1:8000/api/health
# {"status":"ok"}

curl http://127.0.0.1:8000/api/greeting/world
# {"message":"Hello, world!"}
```

### Reading request data

The `Request` object provides access to the body, query parameters, headers, and cookies:

```python
@router.post("/api/items")
async def create_item(request: wesktop.Request):
    data = request.json  # parsed JSON body (dict or list)
    return {"created": data}


@router.get("/api/search")
async def search(request: wesktop.Request):
    q = request.query("q", default="")           # single query param
    page = request.query("page", default=1, type_=int)  # with type coercion
    return {"query": q, "page": page}
```

### Composing routers

Split routes across files using `include_router`:

```python
# routes/users.py
import wesktop

users_router = wesktop.Router()

@users_router.get("/")
async def list_users(request: wesktop.Request):
    return [{"name": "Alice"}, {"name": "Bob"}]

@users_router.get("/{user_id:int}")
async def get_user(request: wesktop.Request, user_id: int):
    return {"id": user_id, "name": "Alice"}
```

```python
# app.py
from routes.users import users_router

router = wesktop.Router()
router.include_router(users_router, prefix="/api/users")
```

## Step 2: Adding SSE for real-time updates

wesktop provides `Broadcaster` for server-sent events. A broadcaster manages typed event channels, per-client queues, and automatic cleanup of disconnected clients.

Extend `app.py` to push system stats every second:

```python
import asyncio
import psutil
import wesktop
from contextlib import asynccontextmanager

router = wesktop.Router()
events = wesktop.Broadcaster()
events.register_event("stats")


async def stats_loop():
    """Push CPU and memory stats every second."""
    while True:
        events.broadcast("stats", {
            "cpu_percent": psutil.cpu_percent(),
            "memory_percent": psutil.virtual_memory().percent,
        })
        await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(stats_loop())
    yield
    task.cancel()


@router.get("/api/health")
async def health(request: wesktop.Request):
    return {"status": "ok"}


# Wire the SSE endpoint
router.add_route("GET", "/events", wesktop.sse_route(events))

app = wesktop.create_app(router, lifespan=lifespan)
```

Key points:

- **Register events before broadcasting.** `Broadcaster` runs in strict mode by default. Calling `broadcast()` with an unregistered event name raises `ValueError`.
- **`sse_route` is a convenience.** It returns an async handler you pass to `add_route` or any route decorator.
- **The lifespan context manager** runs setup before the server accepts requests and teardown after it stops. The yielded value (if a dict) is merged into `request.state` on every request.

Install psutil and test:

```bash
uv add psutil
uv run python app.py
```

In another terminal:

```bash
curl -N http://127.0.0.1:8000/events
# event: stats
# data: {"cpu_percent":12.3,"memory_percent":45.6}
#
# event: stats
# data: {"cpu_percent":11.8,"memory_percent":45.7}
```

### Heartbeats

For long-lived SSE connections behind proxies, enable heartbeats so intermediate infrastructure does not close idle connections:

```python
events = wesktop.Broadcaster(heartbeat_interval=15.0)
```

This sends an SSE comment (`: heartbeat`) every 15 seconds when no real events are pending.

## Step 3: Building an SDUI dashboard

Server-driven UI lets you define the entire frontend layout in Python. The server returns a JSON tree of UI nodes; a generic renderer on the client turns them into components.

wesktop ships 40 SDUI primitives organized into six groups:

| Group | Primitives |
|---|---|
| Layout | `Stack`, `Grid`, `Card`, `Tabs`, `Divider`, `Spacer`, `ZStack`, `Breadcrumb`, `Empty` |
| Display | `Heading`, `Text`, `Code`, `Status`, `Badge`, `ProgressBar`, `Spinner`, `Timeline`, `Diff`, `Markdown` |
| Data | `Table`, `DataGrid`, `List`, `KeyValue`, `JsonView`, `Tree` |
| Input | `Button`, `Input`, `TextArea`, `Select`, `Checkbox`, `Switch`, `Radio`, `Slider` |
| Feedback | `Alert`, `Toast`, `Logs` |
| Overlay | `Modal`, `Drawer`, `Popover`, `Confirm` |

### Typed primitives (Pydantic models)

Each primitive is a Pydantic model with validated fields. Call `.to_node()` to get the dict the renderer expects:

```python
from wesktop import Heading, Card, ProgressBar, Status, Stack, Text, Alert

heading = Heading(content="System Monitor", level=1)
print(heading.to_node())
# {"type": "heading", "props": {"content": "System Monitor", "level": 1}}
```

### Quick dict builder

For rapid prototyping, `node()` builds unvalidated dicts directly:

```python
from wesktop import node

tree = node("column", [
    node("heading", content="Dashboard", level=1),
    node("text", content="Welcome back."),
])
```

### SDUI providers

A provider is an async function that returns a `(ui_tree, initial_state)` tuple. Register providers by name and serve them from a route:

```python
import wesktop
from wesktop import (
    register_sdui_provider,
    get_sdui_provider,
    node,
    Card,
    Heading,
    ProgressBar,
    Status,
    Text,
    KeyValue,
    KVEntry,
    Alert,
)


async def dashboard_provider():
    """Build the dashboard UI tree and initial state."""
    import psutil

    cpu = psutil.cpu_percent()
    mem = psutil.virtual_memory()

    ui = node("column", [
        Heading(content="System Monitor", level=1).to_node(),
        Alert(
            severity="info",
            message="Receiving live updates via SSE.",
        ).to_node(),
        node("row", [
            Card(title="CPU Usage").to_node() | {
                "children": [
                    ProgressBar(value=cpu, label=f"{cpu:.1f}%").to_node(),
                    Status(
                        label="Healthy" if cpu < 80 else "High",
                        variant="success" if cpu < 80 else "warning",
                    ).to_node(),
                ],
            },
            Card(title="Memory Usage").to_node() | {
                "children": [
                    ProgressBar(value=mem.percent, label=f"{mem.percent:.1f}%").to_node(),
                    KeyValue(entries=[
                        KVEntry(label="Total", value=f"{mem.total / (1024**3):.1f} GB"),
                        KVEntry(label="Available", value=f"{mem.available / (1024**3):.1f} GB"),
                    ]).to_node(),
                ],
            },
        ], gap=16),
    ], gap=24)

    state = {"cpu": cpu, "memory_percent": mem.percent}
    return ui, state


register_sdui_provider("dashboard", dashboard_provider)


@router.get("/api/dashboard")
async def dashboard(request: wesktop.Request):
    provider = get_sdui_provider("dashboard")
    if provider is None:
        raise wesktop.HTTPError(404, "Provider not found")
    ui, state = await provider()
    return {"ui": ui, "state": state}
```

The `/api/dashboard` endpoint returns a JSON payload with the full UI tree and initial state. A generic client-side renderer (React, Svelte, vanilla JS) walks the tree and instantiates components.

### Conditional rendering

SDUI nodes support an `if` key for conditional visibility:

```python
Alert(
    severity="error",
    message="CPU is critically high!",
    if_condition="state.cpu > 90",
).to_node()
# {"type": "alert", "props": {...}, "if": "state.cpu > 90"}
```

The renderer evaluates the `if` expression against the current state and shows or hides the node.

## Step 4: Packaging as a desktop app

`wesktop.run()` starts a detached ASGI server subprocess and opens a native OS window via pywebview. The window connects to the server over localhost.

Create `main.py`:

```python
import wesktop

wesktop.run(
    "app:app",
    title="System Monitor",
    width=1024,
    height=768,
    name="SYSMON",
)
```

Run it:

```bash
uv run python main.py
```

A native window opens showing your app. When the window closes, the server stops automatically.

### How `run()` works

1. Checks for an existing instance via the PID file (controlled by the `name` parameter).
2. Spawns a detached Granian server subprocess on a random free port.
3. Opens a pywebview window pointing at `http://127.0.0.1:<port>`.
4. Runs a startup handshake (fetches `/__fastware/version` to verify the server is alive).
5. Injects runtime configuration (`window.__wesktop = {buildId, port, appName}`) into the window via `evaluate_js`.
6. Blocks until the window is closed.
7. On close, removes the window marker. If no other windows are open (across all processes), stops the server.

### Single-instance behavior

By default, `run()` detects an already-running instance and joins it by opening a new window against the existing server. Two modes control second-launch behavior:

```python
# Default: open another window alongside the existing one
wesktop.run("app:app", title="Monitor", second_open="new-window")

# Alternative: raise the existing window, don't open a new one
wesktop.run("app:app", title="Monitor", second_open="focus-existing")
```

Window lifecycle is tracked via marker files on disk, not in-process state, so multiple processes sharing the same app coordinate correctly.

### Desktop entries

On first launch, `run()` auto-registers a desktop shortcut (a `.desktop` file on Linux, an `.app` bundle on macOS, a Start Menu shortcut on Windows). This is best-effort and never blocks or fails the app launch.

You can also manage entries manually:

```python
wesktop.create_entry(name="System Monitor", command="sysmon", icon="/path/to/icon.png")
wesktop.remove_entry("System Monitor")
```

### Custom window icon

Pass a path to an icon file:

```python
wesktop.run("app:app", title="Monitor", icon="assets/icon.png")
```

## Step 5: Complete example

Here is the full application combining all the pieces. Two files: `app.py` (the ASGI application) and `main.py` (the desktop launcher).

### `app.py`

```python
"""System monitor ASGI application with SSE and SDUI."""

import asyncio
from contextlib import asynccontextmanager

import psutil
import wesktop
from wesktop import (
    Broadcaster,
    Card,
    Heading,
    KVEntry,
    KeyValue,
    ProgressBar,
    Status,
    Alert,
    node,
    register_sdui_provider,
    get_sdui_provider,
    sse_route,
)

# --- SSE broadcaster ---

events = Broadcaster()
events.register_event("stats")


async def stats_loop():
    while True:
        events.broadcast("stats", {
            "cpu_percent": psutil.cpu_percent(),
            "memory_percent": psutil.virtual_memory().percent,
        })
        await asyncio.sleep(1)


# --- SDUI provider ---

async def dashboard_provider():
    cpu = psutil.cpu_percent()
    mem = psutil.virtual_memory()

    ui = node("column", [
        Heading(content="System Monitor", level=1).to_node(),
        Alert(severity="info", message="Live updates via SSE.").to_node(),
        node("row", [
            Card(title="CPU").to_node() | {"children": [
                ProgressBar(value=cpu, label=f"{cpu:.1f}%").to_node(),
                Status(
                    label="OK" if cpu < 80 else "High",
                    variant="success" if cpu < 80 else "warning",
                ).to_node(),
            ]},
            Card(title="Memory").to_node() | {"children": [
                ProgressBar(value=mem.percent, label=f"{mem.percent:.1f}%").to_node(),
                KeyValue(entries=[
                    KVEntry(label="Total", value=f"{mem.total / (1024**3):.1f} GB"),
                    KVEntry(label="Free", value=f"{mem.available / (1024**3):.1f} GB"),
                ]).to_node(),
            ]},
        ], gap=16),
    ], gap=24)

    return ui, {"cpu": cpu, "memory_percent": mem.percent}


register_sdui_provider("dashboard", dashboard_provider)


# --- Lifespan ---

@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(stats_loop())
    yield
    task.cancel()


# --- Routes ---

router = wesktop.Router()


@router.get("/api/health")
async def health(request: wesktop.Request):
    return {"status": "ok"}


@router.get("/api/dashboard")
async def dashboard(request: wesktop.Request):
    provider = get_sdui_provider("dashboard")
    ui, state = await provider()
    return {"ui": ui, "state": state}


router.add_route("GET", "/events", sse_route(events))


# --- App ---

app = wesktop.create_app(router, lifespan=lifespan)
```

### `main.py`

```python
"""Launch the system monitor as a desktop application."""

import wesktop

wesktop.run(
    "app:app",
    title="System Monitor",
    width=1024,
    height=768,
    name="SYSMON",
)
```

## Running and debugging

### Development (server only, with auto-reload)

```bash
uv run python -c "
import wesktop
wesktop.serve('app:app', foreground=True, host='127.0.0.1', port=8000, reload=True)
"
```

The `reload=True` flag watches `.py` files and restarts the server on changes. This requires `foreground=True`.

### Desktop mode

```bash
uv run python main.py
```

### Headless deployment

For running on a server without a GUI:

```python
wesktop.serve("app:app", foreground=True, host="0.0.0.0", port=8000)
```

### GUI backend troubleshooting

If `run()` fails with a GUI backend error, check availability:

```python
import wesktop

available = wesktop.ensure_gui_backend()
print(f"GUI backend available: {available}")
```

On Linux, wesktop automatically makes system PyGObject importable in isolated venvs. If that fails, install the system packages:

- **Fedora**: `sudo dnf install gobject-introspection-devel python3-gobject`
- **Debian/Ubuntu**: `sudo apt install libgirepository1.0-dev python3-gi`

Alternatively, set `PYWEBVIEW_GUI=qt` and install a Qt backend:

```bash
uv add pyqt6
PYWEBVIEW_GUI=qt uv run python main.py
```

### CLI diagnostics

wesktop ships a CLI for runtime checks:

```bash
uv run wesktop diagnose   # Python version, dependency versions, platform info
uv run wesktop config show # Display current configuration
```

### Testing

Use `TestClient` to exercise routes without starting a real server or GUI:

```python
from wesktop import TestClient
from app import app


def test_health():
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_dashboard():
    client = TestClient(app)
    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert "ui" in data
    assert "state" in data
```

For async tests:

```python
import pytest
from wesktop import AsyncTestClient
from app import app


@pytest.mark.asyncio
async def test_health_async():
    async with AsyncTestClient(app) as client:
        resp = await client.get("/api/health")
        assert resp.status_code == 200
```
