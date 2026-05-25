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


# All success-path tests also mock _has_gui_backend to return True,
# so they work even when no real GTK/Qt is available.

@patch("wesktop.desktop._has_gui_backend", return_value=True)
@patch("webview.start")
@patch("webview.create_window")
@patch("wesktop.server.serve")
def test_run_calls_webview(
    mock_serve: MagicMock,
    mock_create_window: MagicMock,
    mock_wv_start: MagicMock,
    _mock_gui: MagicMock,
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
        js_api=None,
    )

    # webview.start() called to enter the event loop with icon=None
    mock_wv_start.assert_called_once_with(icon=None)


@patch("wesktop.desktop._has_gui_backend", return_value=True)
@patch("webview.start")
@patch("webview.create_window")
@patch("wesktop.server.serve")
def test_run_with_icon(
    mock_serve: MagicMock,
    mock_create_window: MagicMock,
    mock_wv_start: MagicMock,
    _mock_gui: MagicMock,
) -> None:
    """Icon path is forwarded to webview.start(icon=...)."""
    port = _free_port()
    mock_serve.return_value = f"http://127.0.0.1:{port}"

    from wesktop.desktop import run

    run("myapp:app", icon="/path/to/icon.png", host="127.0.0.1", port=port)

    mock_create_window.assert_called_once()
    mock_wv_start.assert_called_once_with(icon="/path/to/icon.png")


@patch("wesktop.desktop._has_gui_backend", return_value=True)
@patch("webview.start")
@patch("webview.create_window")
@patch("wesktop.server.serve")
def test_run_without_icon(
    mock_serve: MagicMock,
    mock_create_window: MagicMock,
    mock_wv_start: MagicMock,
    _mock_gui: MagicMock,
) -> None:
    """When no icon is provided, webview.start(icon=None) is called."""
    port = _free_port()
    mock_serve.return_value = f"http://127.0.0.1:{port}"

    from wesktop.desktop import run

    run("myapp:app", host="127.0.0.1", port=port)

    mock_wv_start.assert_called_once_with(icon=None)


@patch("wesktop.desktop._has_gui_backend", return_value=True)
@patch("webview.start")
@patch("webview.create_window")
@patch("wesktop.server.serve")
def test_run_with_js_api(
    mock_serve: MagicMock,
    mock_create_window: MagicMock,
    mock_wv_start: MagicMock,
    _mock_gui: MagicMock,
) -> None:
    """js_api object is forwarded to webview.create_window(js_api=...)."""
    port = _free_port()
    mock_serve.return_value = f"http://127.0.0.1:{port}"

    class MyAPI:
        def greet(self, name: str) -> str:
            return f"Hello, {name}"

    api = MyAPI()

    from wesktop.desktop import run

    run("myapp:app", host="127.0.0.1", port=port, js_api=api)

    mock_create_window.assert_called_once_with(
        title="wesktop",
        url=f"http://127.0.0.1:{port}",
        width=1280,
        height=800,
        js_api=api,
    )


@patch("wesktop.desktop._has_gui_backend", return_value=True)
@patch("webview.start")
@patch("webview.create_window")
@patch("wesktop.server.serve")
def test_run_without_js_api(
    mock_serve: MagicMock,
    mock_create_window: MagicMock,
    mock_wv_start: MagicMock,
    _mock_gui: MagicMock,
) -> None:
    """When no js_api is provided, webview.create_window(js_api=None) is called."""
    port = _free_port()
    mock_serve.return_value = f"http://127.0.0.1:{port}"

    from wesktop.desktop import run

    run("myapp:app", host="127.0.0.1", port=port)

    mock_create_window.assert_called_once_with(
        title="wesktop",
        url=f"http://127.0.0.1:{port}",
        width=1280,
        height=800,
        js_api=None,
    )


@patch("wesktop.desktop._has_gui_backend", return_value=True)
@patch("webview.start")
@patch("webview.create_window")
@patch("wesktop.server.serve")
def test_run_js_api_via_wrapper(
    mock_serve: MagicMock,
    mock_create_window: MagicMock,
    mock_wv_start: MagicMock,
    _mock_gui: MagicMock,
) -> None:
    """js_api passes through the wesktop.run() wrapper to desktop.run()."""
    port = _free_port()
    mock_serve.return_value = f"http://127.0.0.1:{port}"

    class BridgeAPI:
        def ping(self) -> str:
            return "pong"

    api = BridgeAPI()

    wesktop.run("myapp:app", host="127.0.0.1", port=port, js_api=api)

    mock_create_window.assert_called_once()
    call_kwargs = mock_create_window.call_args[1]
    assert call_kwargs["js_api"] is api


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


# --- Fallback tests ---

@patch("wesktop.desktop._browser_fallback")
@patch("wesktop.desktop._has_gui_backend", return_value=False)
@patch("wesktop.server.serve")
def test_run_fallback_no_gui_backend(
    mock_serve: MagicMock,
    _mock_gui: MagicMock,
    mock_fallback: MagicMock,
) -> None:
    """When _has_gui_backend() returns False, fall back to browser without touching webview."""
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    mock_serve.return_value = url

    from wesktop.desktop import run

    run("myapp:app", host="127.0.0.1", port=port)

    mock_fallback.assert_called_once_with(url)


@patch("wesktop.desktop._browser_fallback")
@patch("wesktop.desktop._has_gui_backend", return_value=True)
@patch("webview.start", side_effect=__import__("webview").WebViewException("No GUI"))
@patch("webview.create_window")
@patch("wesktop.server.serve")
def test_run_fallback_webview_exception(
    mock_serve: MagicMock,
    mock_create_window: MagicMock,
    mock_wv_start: MagicMock,
    _mock_gui: MagicMock,
    mock_fallback: MagicMock,
) -> None:
    """When webview.start() raises WebViewException, fall back to browser."""
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    mock_serve.return_value = url

    from wesktop.desktop import run

    run("myapp:app", host="127.0.0.1", port=port)

    mock_fallback.assert_called_once_with(url)


@patch("wesktop.desktop.signal")
@patch("wesktop.desktop.webbrowser")
def test_browser_fallback_opens_browser(
    mock_webbrowser: MagicMock,
    mock_signal: MagicMock,
    capsys: object,
) -> None:
    """_browser_fallback opens the URL in a browser and prints a message."""
    mock_signal.pause.side_effect = KeyboardInterrupt

    from wesktop.desktop import _browser_fallback

    _browser_fallback("http://127.0.0.1:9999")

    mock_webbrowser.open.assert_called_once_with("http://127.0.0.1:9999")
    import _pytest.capture
    captured = capsys.readouterr()  # type: ignore[union-attr]
    assert "pywebview GUI backend not available" in captured.out
    assert "http://127.0.0.1:9999" in captured.out


@patch("wesktop.desktop._browser_fallback")
@patch("wesktop.server.serve")
def test_run_fallback_webview_not_installed(
    mock_serve: MagicMock,
    mock_fallback: MagicMock,
) -> None:
    """When webview is not importable at all, fall back to browser."""
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    mock_serve.return_value = url

    import builtins
    import importlib
    import wesktop.desktop

    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "webview":
            raise ImportError("No module named 'webview'")
        return original_import(name, *args, **kwargs)

    # Reload the module so the late `import webview` inside run() is fresh
    importlib.reload(wesktop.desktop)

    with patch("builtins.__import__", side_effect=fake_import):
        # Re-patch _browser_fallback on the reloaded module
        with patch.object(wesktop.desktop, "_browser_fallback") as reloaded_fallback:
            # Also re-patch serve on the reloaded module's import path
            with patch("wesktop.server.serve", return_value=url):
                wesktop.desktop.run("myapp:app", host="127.0.0.1", port=port)
                reloaded_fallback.assert_called_once_with(url)

    # Clean up
    importlib.reload(wesktop.desktop)


# --- _has_gui_backend unit tests ---

def test_has_gui_backend_non_linux() -> None:
    """On non-Linux platforms, _has_gui_backend always returns True."""
    from wesktop.desktop import _has_gui_backend

    with patch("sys.platform", "darwin"):
        assert _has_gui_backend() is True

    with patch("sys.platform", "win32"):
        assert _has_gui_backend() is True


def test_has_gui_backend_linux_gtk_available() -> None:
    """On Linux with gi importable, returns True."""
    from wesktop.desktop import _has_gui_backend

    mock_gi = MagicMock()
    with (
        patch("sys.platform", "linux"),
        patch.dict("os.environ", {}, clear=False),
        patch.dict(sys.modules, {"gi": mock_gi}),
    ):
        import os
        os.environ.pop("PYWEBVIEW_GUI", None)
        assert _has_gui_backend() is True


def test_has_gui_backend_linux_qt_available() -> None:
    """On Linux with gi missing but qtpy importable, returns True."""
    from wesktop.desktop import _has_gui_backend

    import builtins
    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "gi":
            raise ImportError("no gi")
        if name == "qtpy":
            return MagicMock()
        return original_import(name, *args, **kwargs)

    with (
        patch("sys.platform", "linux"),
        patch.dict("os.environ", {}, clear=False),
        patch("builtins.__import__", side_effect=fake_import),
    ):
        import os
        os.environ.pop("PYWEBVIEW_GUI", None)
        assert _has_gui_backend() is True


def test_has_gui_backend_linux_neither() -> None:
    """On Linux with neither gi nor qtpy, returns False."""
    from wesktop.desktop import _has_gui_backend

    import builtins
    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name in ("gi", "qtpy"):
            raise ImportError(f"no {name}")
        return original_import(name, *args, **kwargs)

    with (
        patch("sys.platform", "linux"),
        patch.dict("os.environ", {}, clear=False),
        patch("builtins.__import__", side_effect=fake_import),
    ):
        import os
        os.environ.pop("PYWEBVIEW_GUI", None)
        assert _has_gui_backend() is False


def test_has_gui_backend_pywebview_gui_env_gtk() -> None:
    """PYWEBVIEW_GUI=gtk forces GTK probe only."""
    from wesktop.desktop import _has_gui_backend

    mock_gi = MagicMock()
    with (
        patch("sys.platform", "linux"),
        patch.dict("os.environ", {"PYWEBVIEW_GUI": "gtk"}),
        patch.dict(sys.modules, {"gi": mock_gi}),
    ):
        assert _has_gui_backend() is True


def test_has_gui_backend_pywebview_gui_env_gtk_missing() -> None:
    """PYWEBVIEW_GUI=gtk with gi missing returns False (does not try Qt)."""
    from wesktop.desktop import _has_gui_backend

    import builtins
    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "gi":
            raise ImportError("no gi")
        return original_import(name, *args, **kwargs)

    with (
        patch("sys.platform", "linux"),
        patch.dict("os.environ", {"PYWEBVIEW_GUI": "gtk"}),
        patch("builtins.__import__", side_effect=fake_import),
    ):
        assert _has_gui_backend() is False
