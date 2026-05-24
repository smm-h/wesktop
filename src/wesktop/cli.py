"""wesktop CLI -- diagnostics and future app management."""

from __future__ import annotations

import platform
import sys

from strictcli import App

from wesktop import __version__

app = App(
    name="wesktop",
    help="A Python framework for building web-based desktop applications",
    version=__version__,
    config=True,
)


@app.command("diagnose", help="Check runtime environment and dependencies")
def diagnose(**_kw: object) -> None:
    """Print a diagnostic table of the runtime environment."""
    rows: list[tuple[str, str]] = []

    rows.append(("Python", f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"))
    rows.append(("wesktop", __version__))

    # granian
    try:
        import granian  # type: ignore[import-untyped]

        ver = getattr(granian, "__version__", "unknown")
        rows.append(("granian", f"{ver} (ok)"))
    except ImportError:
        rows.append(("granian", "NOT FOUND"))

    # pywebview
    try:
        import webview  # type: ignore[import-untyped]

        ver = getattr(webview, "__version__", "unknown")
        guilib = getattr(webview, "guilib", None)
        if guilib is None:
            # Try to detect via platform
            if sys.platform == "linux":
                backend = "GTK (likely)"
            elif sys.platform == "darwin":
                backend = "Cocoa (likely)"
            elif sys.platform == "win32":
                backend = "EdgeChromium (likely)"
            else:
                backend = "unknown"
        else:
            backend = str(guilib)
        rows.append(("pywebview", f"{ver} (ok), backend: {backend}"))
    except ImportError:
        rows.append(("pywebview", "NOT FOUND"))

    # msgspec
    try:
        import msgspec

        ver = getattr(msgspec, "__version__", "unknown")
        rows.append(("msgspec", f"{ver} (ok)"))
    except ImportError:
        rows.append(("msgspec", "NOT FOUND"))

    # strictcli
    try:
        import strictcli

        ver = getattr(strictcli, "__version__", "unknown")
        rows.append(("strictcli", f"{ver} (ok)"))
    except ImportError:
        rows.append(("strictcli", "NOT FOUND"))

    # Platform
    rows.append(("platform", f"{platform.system()} {platform.machine()}"))

    # Config path
    rows.append(("config", app.config_file_path))

    # Print table
    label_width = max(len(label) for label, _ in rows)
    for label, value in rows:
        print(f"  {label:<{label_width}}  {value}")


def main() -> None:
    """Entry point for the CLI."""
    app.run()
