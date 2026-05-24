from __future__ import annotations

import socket
import sys
from unittest.mock import MagicMock, patch

import wesktop


def _free_port() -> int:
    """Find an ephemeral port that is currently free."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@patch("webview.start")
@patch("webview.create_window")
@patch("wesktop.server.serve")
def test_run_calls_webview(
    mock_serve: MagicMock,
    mock_create_window: MagicMock,
    mock_wv_start: MagicMock,
) -> None:
    """Server starts before window; correct title/url/size passed to create_window; start() called."""
    port = _free_port()
    mock_serve.return_value = f"http://127.0.0.1:{port}"

    from wesktop.desktop import run

    run("myapp:app", title="Test", width=800, height=600, host="127.0.0.1", port=port)

    # Server started via serve(foreground=False)
    mock_serve.assert_called_once_with(
        "myapp:app",
        foreground=False,
        host="127.0.0.1",
        port=port,
        pid_path=None,
        name="WESKTOP",
        pre_serve=None,
        reload=False,
    )

    # Window created with correct params
    mock_create_window.assert_called_once_with(
        title="Test",
        url=f"http://127.0.0.1:{port}",
        width=800,
        height=600,
    )

    # webview.start() called to enter the event loop with icon=None
    mock_wv_start.assert_called_once_with(icon=None)


@patch("webview.start")
@patch("webview.create_window")
@patch("wesktop.server.serve")
def test_run_with_icon(
    mock_serve: MagicMock,
    mock_create_window: MagicMock,
    mock_wv_start: MagicMock,
) -> None:
    """Icon path is forwarded to webview.start(icon=...)."""
    port = _free_port()
    mock_serve.return_value = f"http://127.0.0.1:{port}"

    from wesktop.desktop import run

    run("myapp:app", icon="/path/to/icon.png", host="127.0.0.1", port=port)

    mock_create_window.assert_called_once()
    mock_wv_start.assert_called_once_with(icon="/path/to/icon.png")


@patch("webview.start")
@patch("webview.create_window")
@patch("wesktop.server.serve")
def test_run_without_icon(
    mock_serve: MagicMock,
    mock_create_window: MagicMock,
    mock_wv_start: MagicMock,
) -> None:
    """When no icon is provided, webview.start(icon=None) is called."""
    port = _free_port()
    mock_serve.return_value = f"http://127.0.0.1:{port}"

    from wesktop.desktop import run

    run("myapp:app", host="127.0.0.1", port=port)

    mock_wv_start.assert_called_once_with(icon=None)


@patch("wesktop.server.Granian")
def test_serve_calls_granian(mock_granian_cls: MagicMock) -> None:
    """wesktop.serve() delegates to the server module with correct params."""
    mock_instance = MagicMock()
    mock_granian_cls.return_value = mock_instance

    port = _free_port()
    wesktop.serve("myapp:app", foreground=False, host="127.0.0.1", port=port, name="TEST_SVC")

    mock_granian_cls.assert_called_once_with(
        target="myapp:app",
        address="127.0.0.1",
        port=port,
        interface="asgi",
    )
    mock_instance.serve.assert_called_once()


def test_run_late_imports_webview() -> None:
    """webview is not imported at module level -- only when run() is called."""
    # Ensure the desktop module is loaded (importing wesktop triggers it lazily
    # through the top-level run(), but the module itself should not import webview).
    import importlib

    # Remove wesktop.desktop from cache so we can observe a fresh import
    sys.modules.pop("wesktop.desktop", None)

    # Record webview presence before importing the module
    had_webview_before = "webview" in sys.modules

    # Import the module (not call run())
    import wesktop.desktop  # noqa: F811

    # webview should not have been pulled in by the module-level import
    if not had_webview_before:
        assert "webview" not in sys.modules, (
            "webview was imported at module level in wesktop.desktop"
        )

    # Clean up: reload so subsequent tests get the patching-friendly version
    importlib.reload(wesktop.desktop)
