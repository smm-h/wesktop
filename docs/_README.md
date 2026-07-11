---
title: wesktop
description: Build web-based desktop applications in Python with native OS windows, backed by a fast ASGI server
date: 2026-07-01
---
# wesktop

Build web-based desktop apps in Python. Native OS windows backed by a fast ASGI server.

![Version](https://img.shields.io/pypi/v/wesktop)
![Python](https://img.shields.io/pypi/pyversions/wesktop)
![License](https://img.shields.io/pypi/l/wesktop)
![PyPI](https://img.shields.io/pypi/dm/wesktop)
![npm](https://img.shields.io/npm/v/wesktop)

## What is wesktop?

wesktop combines [fastware](https://github.com/smm-h/fastware) (an ASGI framework) with [pywebview](https://pywebview.flowrl.com/) (native OS windows) to create desktop applications using Python and web technologies. Define routes in Python, serve them over HTTP, and open a native window -- no Electron, no Chromium bundling, no JavaScript build step required.

## Minimal desktop app

```python
import wesktop

router = wesktop.Router()

@router.get("/")
async def index(req: wesktop.Request):
    return wesktop.HTMLResponse("<h1>Hello from wesktop</h1>")

@router.get("/api/health")
async def health(req: wesktop.Request):
    return {"status": "ok"}

app = wesktop.create_app(router)

# Desktop mode: starts server + opens a native OS window
wesktop.run("myapp:app", title="My App", width=1024, height=768)
```

## Headless server

For development, CI, or server-only deployment -- no GUI dependency is loaded:

```python
wesktop.serve("myapp:app", foreground=True, host="127.0.0.1", port=8000)
```

## Why not Electron?

| | wesktop | Electron |
|---|---|---|
| Language | Python | JavaScript |
| Runtime | System Python + OS WebView | Bundled Chromium |
| Bundle size | ~50 KB (pip install) | ~150 MB+ |
| Memory | Shared OS WebView process | Dedicated Chromium per app |
| Native feel | Uses platform WebView (WebKit/Edge) | Chrome-based, uniform look |
| Installation | `pip install wesktop` | Custom installer per app |

## Architecture

wesktop is built on two layers:

- [**fastware**](https://github.com/smm-h/fastware) -- ASGI framework providing routing, SSE, middleware, dependency injection, authentication, and server lifecycle management via granian. fastware is a standalone package usable without wesktop for headless web services.
- **wesktop** -- Desktop integration layer: pywebview native windows, desktop entry creation, server-driven UI primitives, and CLI diagnostics. Imports fastware and adds everything needed to ship a desktop application.

## Key features

- Native OS windows via pywebview (WebKit on Linux/macOS, Edge WebView2 on Windows)
- ASGI micro-router with `{param}` placeholders and static file serving
- SSE broadcaster with typed events and per-client queues
- Granian (Rust-based) server lifecycle with PID management
- Desktop entry creation (Linux `.desktop`, macOS `.app`, Windows Start Menu)
- Server-driven UI primitives (40 SDUI components across 6 categories)
- Dependency injection, authentication, middleware, and feature flags
- MCP server support for role-based agent tool provisioning
- CLI diagnostics (`wesktop diagnose`)

## Installation

```bash
pip install wesktop
```

The CLI is also available as an npm shim:

```bash
npx wesktop diagnose
```

## CLI

:-: table-commands

## Module layout

:-: list-modules path="src/wesktop/"

## Dependencies

:-: table-dep path="pyproject.toml"

## Documentation

Full documentation is available at [wesktop.smmh.dev](https://wesktop.smmh.dev).

## License

MIT
