# Platform Vision: wesktop as an App Manager

## Context

wesktop currently provides a framework for building web-based desktop apps (pywebview + granian + ASGI). The CLI has a single `diagnose` command. The natural evolution is to make wesktop an app manager -- a single CLI that discovers, installs, runs, and manages wesktop-based applications.

## Problem

Users who build apps with wesktop have no unified way to:
- Install a wesktop app from PyPI or a git URL
- List locally installed wesktop apps
- Launch an app by name (without knowing its ASGI target)
- Update or remove apps cleanly

Each app currently needs its own entry point and launch script.

## Proposed Commands

| Command | Description |
|---------|-------------|
| `wesktop install <package>` | Install a wesktop app from PyPI, git URL, or local path. Discovers the ASGI target via package metadata (e.g., `[project.entry-points."wesktop.apps"]`). |
| `wesktop list` | List all installed wesktop apps with name, version, and status. |
| `wesktop run <app>` | Launch a wesktop app by registered name. Resolves the ASGI target, starts granian, opens a pywebview window. |
| `wesktop update [app]` | Update one or all installed wesktop apps. |
| `wesktop remove <app>` | Uninstall a wesktop app and clean up its entry. |

## Discovery Mechanism

Apps register themselves via a standard entry point group in their `pyproject.toml`:

```toml
[project.entry-points."wesktop.apps"]
myapp = "myapp.asgi:app"
```

`wesktop list` scans `importlib.metadata.entry_points(group="wesktop.apps")` to find all registered apps. `wesktop run <name>` resolves the entry point, imports the ASGI app, and calls `wesktop.run()`.

## App Metadata

Each app can optionally declare wesktop-specific metadata in `pyproject.toml`:

```toml
[tool.wesktop]
title = "My App"
width = 1280
height = 800
icon = "myapp/static/icon.png"
```

`wesktop run` reads this metadata to configure the window.

## Installation Mechanics

`wesktop install <package>` delegates to `uv pip install <package>` (or `pip install` as fallback) in the wesktop environment. After installation, it verifies the `wesktop.apps` entry point was registered and prints the app name.

## Affected Files

- `src/wesktop/cli.py` -- add `install`, `list`, `run`, `update`, `remove` commands
- `src/wesktop/registry.py` -- new module for entry point discovery and app metadata resolution
- `src/wesktop/__init__.py` -- possibly extend `run()` to accept resolved entry point objects
- `tests/test_cli.py` -- tests for new commands

## Effort Estimate

Medium. The entry point discovery is straightforward (`importlib.metadata`). The install/update/remove commands are thin wrappers around `uv`/`pip`. The main design work is the metadata schema and error handling for missing/malformed entry points.
