# pywebview GUI backend not accessible in uv venvs

## Problem

pywebview requires a GUI backend (GTK via PyGObject or Qt via qtpy). On Linux, PyGObject (`gi` module) is typically installed as a system package (`python3-gobject`) and is not available on PyPI. uv creates venvs with `include-system-site-packages = false` by default, so the system `gi` module is invisible inside the venv.

Result: `import webview` succeeds (pywebview itself is a pure-Python PyPI package), but `webview.start()` fails at runtime with `WebViewException: You must have either QT or GTK with Python extensions installed`. The `import webview` probe passes, so the fallback-to-browser path doesn't trigger — it crashes instead.

Observed on Fedora 43 with `python3-gobject` and `gtk3` installed system-wide but inaccessible from a uv-managed venv (system Python 3.14, venv Python 3.13).

## Options

1. **Document that consumers must enable system site packages.** Add a note in wesktop docs: set `include-system-site-packages = true` in `.venv/pyvenv.cfg` or configure uv accordingly. Least invasive but shifts burden to every consumer.

2. **Probe the GUI backend, not just `import webview`.** The current pattern (`import webview` to check availability) is insufficient. wesktop should probe deeper — try `webview.guilib.import_gtk()` or `webview.guilib.import_qt()` — and fall back to browser mode if neither succeeds. This makes the fallback work correctly regardless of venv config.

3. **Ship a PyPI-installable GTK binding.** `PyGObject` is on PyPI but requires system headers (`libgirepository1.0-dev`, `libcairo2-dev`, etc.) to build. Could add it as an optional dependency (`wesktop[gtk]`) but it will fail to install on systems without the C headers.

4. **Prefer Qt over GTK.** `qtpy` + `PyQt6` are pure-PyPI installable (binary wheels). Adding `pywebview[qt]` as the optional dependency would avoid the system-package problem entirely. Trade-off: Qt is a much larger dependency.

## Recommendation

Option 2 is the immediate fix — the fallback-to-browser path should actually work. Option 1 or 4 as a longer-term install story.
