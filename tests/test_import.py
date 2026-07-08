"""Import-layer guards: wesktop must import cleanly, lazily, and completely.

- `import wesktop` must not pull heavy optional machinery (granian, mcp,
  webview) into sys.modules -- those load on first attribute access via
  the module-level __getattr__ (PEP 562).
- Every name advertised in wesktop.__all__ must resolve.
"""

import subprocess
import sys


def test_import():
    import wesktop  # noqa: F401


def test_import_does_not_load_heavy_modules():
    """granian, mcp, and webview must not be imported by `import wesktop`."""
    code = (
        "import wesktop, sys; "
        "heavy = [m for m in ('granian', 'mcp', 'webview') if m in sys.modules]; "
        "assert not heavy, f'heavy modules imported eagerly: {heavy}'"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_all_public_names_resolve():
    """Every name in wesktop.__all__ is accessible (exercises the lazy
    __getattr__ paths for server, desktop, dev, mcp, and sdui symbols)."""
    import wesktop

    for name in wesktop.__all__:
        assert getattr(wesktop, name) is not None, f"{name} did not resolve"


def test_unknown_attribute_raises():
    import wesktop

    try:
        wesktop.definitely_not_a_symbol
    except AttributeError as exc:
        assert "definitely_not_a_symbol" in str(exc)
    else:
        raise AssertionError("expected AttributeError")


def test_websocket_disconnect_exported():
    """WebSocketDisconnect is part of wesktop's public API."""
    import wesktop
    from fastware.websocket import WebSocketDisconnect

    assert "WebSocketDisconnect" in wesktop.__all__
    assert wesktop.WebSocketDisconnect is WebSocketDisconnect


def test_asgi_stub_does_not_leak_typing_helpers():
    """The star-import chain in wesktop.asgi must not leak typing helpers
    (fastware.types regression: missing __all__ leaked Any/Awaitable/
    Callable/annotations)."""
    from wesktop import asgi

    for leaked in ("Any", "Awaitable", "annotations"):
        assert not hasattr(asgi, leaked), f"wesktop.asgi leaks {leaked!r}"
