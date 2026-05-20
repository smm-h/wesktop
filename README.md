# wesktop

A Python framework for building web-based desktop applications. Combines an ASGI micro-router, SSE broadcaster, [granian](https://github.com/emmett-framework/granian) (Rust-based ASGI server), and [pywebview](https://pywebview.flowrl.com/) (native OS windows) into a single package.

## Installation

```bash
pip install wesktop
```

## Quick Start

```python
import wesktop

router = wesktop.Router()

@router.get("/api/health")
async def health(req: wesktop.Request):
    return {"status": "ok"}

app = wesktop.create_app(router)

# Desktop mode: server + native window
wesktop.run("myapp:app", title="My App", width=1024, height=768)

# Or headless mode: server only
# wesktop.serve("myapp:app", host="127.0.0.1", port=8000)
```

## Features

- **ASGI micro-router** with `{param}` placeholders, static file serving, SPA fallback, and WebSocket support
- **SSE broadcaster** with typed events, per-client async queues, and automatic client pruning
- **6 response types**: JSON, text, HTML, bytes, streaming, and auto-wrapped dict/list
- **Desktop window** via pywebview (late-imported, so headless mode has no GUI dependency)
- **Desktop entries**: cross-platform shortcut creation (Linux `.desktop`, macOS `.app`, Windows Start Menu)
- **Fast serialization** via [msgspec](https://jcristharber.com/msgspec/)

## CLI

wesktop includes a CLI for diagnostics and configuration:

```bash
wesktop --help              # List available commands
wesktop --version           # Print package version
wesktop diagnose            # Check runtime environment and dependencies
wesktop config show         # Display current configuration
wesktop config set KEY VAL  # Set a config value
wesktop config edit         # Open config in $EDITOR
wesktop config path         # Print config file path
```

The CLI is also available as an npm shim for environments where `npx` is more convenient:

```bash
npx wesktop diagnose
```

## Platform Vision

wesktop is evolving toward an app manager that can discover, install, run, and manage wesktop-based applications via entry points. See [todo/platform-vision.md](todo/platform-vision.md) for the full proposal.

## License

MIT
