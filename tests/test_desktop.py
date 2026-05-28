from __future__ import annotations

import socket
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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
@patch("wesktop.server.serve_background")
def test_run_calls_webview(
    mock_serve_bg: MagicMock,
    mock_create_window: MagicMock,
    mock_wv_start: MagicMock,
    _mock_gui: MagicMock,
) -> None:
    """Server starts before window; correct title/url/size passed to create_window; start() called."""
    port = _free_port()
    mock_serve_bg.return_value = f"http://127.0.0.1:{port}"

    from wesktop.desktop import run

    run("myapp:app", title="Test", width=800, height=600, host="127.0.0.1", port=port)

    # Server started via serve_background() as an independent process
    mock_serve_bg.assert_called_once_with(
        "myapp:app",
        host="127.0.0.1",
        port=port,
        pid_path=Path(".wesktop.pid"),
        name="WESKTOP",
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
@patch("wesktop.server.serve_background")
def test_run_with_icon(
    mock_serve_bg: MagicMock,
    mock_create_window: MagicMock,
    mock_wv_start: MagicMock,
    _mock_gui: MagicMock,
) -> None:
    """Icon path is forwarded to webview.start(icon=...)."""
    port = _free_port()
    mock_serve_bg.return_value = f"http://127.0.0.1:{port}"

    from wesktop.desktop import run

    run("myapp:app", icon="/path/to/icon.png", host="127.0.0.1", port=port)

    mock_create_window.assert_called_once()
    mock_wv_start.assert_called_once_with(icon="/path/to/icon.png")


@patch("wesktop.desktop._has_gui_backend", return_value=True)
@patch("webview.start")
@patch("webview.create_window")
@patch("wesktop.server.serve_background")
def test_run_without_icon(
    mock_serve_bg: MagicMock,
    mock_create_window: MagicMock,
    mock_wv_start: MagicMock,
    _mock_gui: MagicMock,
) -> None:
    """When no icon is provided, webview.start(icon=None) is called."""
    port = _free_port()
    mock_serve_bg.return_value = f"http://127.0.0.1:{port}"

    from wesktop.desktop import run

    run("myapp:app", host="127.0.0.1", port=port)

    mock_wv_start.assert_called_once_with(icon=None)


@patch("wesktop.desktop._has_gui_backend", return_value=True)
@patch("webview.start")
@patch("webview.create_window")
@patch("wesktop.server.serve_background")
def test_run_with_js_api(
    mock_serve_bg: MagicMock,
    mock_create_window: MagicMock,
    mock_wv_start: MagicMock,
    _mock_gui: MagicMock,
) -> None:
    """js_api object is forwarded to webview.create_window(js_api=...)."""
    port = _free_port()
    mock_serve_bg.return_value = f"http://127.0.0.1:{port}"

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
@patch("wesktop.server.serve_background")
def test_run_without_js_api(
    mock_serve_bg: MagicMock,
    mock_create_window: MagicMock,
    mock_wv_start: MagicMock,
    _mock_gui: MagicMock,
) -> None:
    """When no js_api is provided, webview.create_window(js_api=None) is called."""
    port = _free_port()
    mock_serve_bg.return_value = f"http://127.0.0.1:{port}"

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
@patch("wesktop.server.serve_background")
def test_run_js_api_via_wrapper(
    mock_serve_bg: MagicMock,
    mock_create_window: MagicMock,
    mock_wv_start: MagicMock,
    _mock_gui: MagicMock,
) -> None:
    """js_api passes through the wesktop.run() wrapper to desktop.run()."""
    port = _free_port()
    mock_serve_bg.return_value = f"http://127.0.0.1:{port}"

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


# --- Error tests (no browser fallback) ---

@patch("wesktop.desktop._has_gui_backend", return_value=False)
@patch("wesktop.server.serve_background")
def test_run_raises_on_no_gui_backend(
    mock_serve_bg: MagicMock,
    _mock_gui: MagicMock,
) -> None:
    """When _has_gui_backend() returns False, raise RuntimeError."""
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    mock_serve_bg.return_value = url

    from wesktop.desktop import run

    with pytest.raises(RuntimeError, match="pywebview GUI backend not available"):
        run("myapp:app", host="127.0.0.1", port=port)


@patch("wesktop.desktop._has_gui_backend", return_value=True)
@patch("webview.start", side_effect=__import__("webview").WebViewException("No GUI"))
@patch("webview.create_window")
@patch("wesktop.server.serve_background")
def test_run_propagates_webview_exception(
    mock_serve_bg: MagicMock,
    mock_create_window: MagicMock,
    mock_wv_start: MagicMock,
    _mock_gui: MagicMock,
) -> None:
    """When webview.start() raises WebViewException, it propagates."""
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    mock_serve_bg.return_value = url

    import webview as wv

    from wesktop.desktop import run

    with pytest.raises(wv.WebViewException):
        run("myapp:app", host="127.0.0.1", port=port)


@patch("wesktop.server.serve_background")
def test_run_raises_on_webview_not_installed(
    mock_serve_bg: MagicMock,
) -> None:
    """When webview is not importable at all, raise RuntimeError."""
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    mock_serve_bg.return_value = url

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
        with patch("wesktop.server.serve_background", return_value=url):
            with pytest.raises(RuntimeError, match="pywebview is not installed"):
                wesktop.desktop.run("myapp:app", host="127.0.0.1", port=port)

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


# --- _auto_register_entry tests ---


@patch("wesktop.desktop._has_gui_backend", return_value=True)
@patch("webview.start")
@patch("webview.create_window")
@patch("wesktop.server.serve_background")
@patch("wesktop.desktop._auto_register_entry")
def test_run_calls_auto_register_entry(
    mock_auto_register: MagicMock,
    mock_serve_bg: MagicMock,
    mock_create_window: MagicMock,
    mock_wv_start: MagicMock,
    _mock_gui: MagicMock,
) -> None:
    """run() calls _auto_register_entry with the title and icon."""
    port = _free_port()
    mock_serve_bg.return_value = f"http://127.0.0.1:{port}"

    from wesktop.desktop import run

    run("myapp:app", title="MyApp", icon="/path/icon.png", host="127.0.0.1", port=port)

    mock_auto_register.assert_called_once_with("MyApp", "/path/icon.png")


@patch("wesktop.entries.create_entry")
@patch("wesktop.desktop._entry_exists", return_value=False)
def test_auto_register_creates_entry_when_missing(
    mock_exists: MagicMock,
    mock_create: MagicMock,
    tmp_path: Path,
) -> None:
    """_auto_register_entry creates a desktop entry when none exists."""
    from wesktop.desktop import _auto_register_entry

    with (
        patch("wesktop.desktop.Path.home", return_value=tmp_path),
        patch("wesktop.desktop.Path.cwd", return_value=tmp_path),
        patch("sys.argv", ["/usr/bin/myapp", "open"]),
    ):
        _auto_register_entry("MyApp", None)

    mock_create.assert_called_once()
    call_kwargs = mock_create.call_args
    assert call_kwargs[1]["name"] == "MyApp"
    assert call_kwargs[1]["icon"] is None
    assert call_kwargs[1]["comment"] == ""


@patch("wesktop.entries.create_entry")
@patch("wesktop.desktop._entry_exists", return_value=True)
def test_auto_register_skips_when_exists(
    mock_exists: MagicMock,
    mock_create: MagicMock,
    tmp_path: Path,
) -> None:
    """_auto_register_entry does nothing when the entry exists and launcher is valid."""
    from wesktop.desktop import _auto_register_entry

    # Create a fake launcher so the self-healing check passes
    launcher = tmp_path / ".local" / "bin" / "myapp-open"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.touch()

    with patch("wesktop.desktop.Path.home", return_value=tmp_path):
        _auto_register_entry("MyApp", None)

    mock_create.assert_not_called()


@patch("wesktop.entries.create_entry")
@patch("wesktop.entries.remove_entry")
@patch("wesktop.desktop._entry_exists", return_value=True)
def test_auto_register_self_heals_broken_launcher(
    mock_exists: MagicMock,
    mock_remove: MagicMock,
    mock_create: MagicMock,
    tmp_path: Path,
) -> None:
    """_auto_register_entry removes and recreates entry when launcher is missing."""
    from wesktop.desktop import _auto_register_entry

    # No launcher exists at ~/.local/bin/myapp-open -- simulates uninstall
    with (
        patch("wesktop.desktop.Path.home", return_value=tmp_path),
        patch("wesktop.desktop.Path.cwd", return_value=tmp_path),
        patch("sys.argv", ["/usr/bin/myapp", "open"]),
    ):
        _auto_register_entry("MyApp", None)

    # The broken entry should have been removed
    mock_remove.assert_called_once_with("MyApp")
    # And a new entry should have been created
    mock_create.assert_called_once()


@patch("wesktop.desktop._entry_exists", side_effect=OSError("disk on fire"))
def test_auto_register_swallows_exceptions(
    mock_exists: MagicMock,
) -> None:
    """_auto_register_entry never raises, even on unexpected errors."""
    from wesktop.desktop import _auto_register_entry

    # Must not raise
    _auto_register_entry("MyApp", None)


# --- single_instance tests ---


@patch("wesktop.desktop._has_gui_backend", return_value=True)
@patch("webview.start")
@patch("webview.create_window")
@patch("wesktop.server.serve_background")
@patch("wesktop.server.stop")
@patch("wesktop.server.check_already_running", return_value=42)
def test_run_single_instance_joins_existing(
    mock_check: MagicMock,
    mock_stop: MagicMock,
    mock_serve_bg: MagicMock,
    mock_create_window: MagicMock,
    mock_wv_start: MagicMock,
    _mock_gui: MagicMock,
    tmp_path: Path,
) -> None:
    """run() with single_instance=True and existing PID opens a window to the existing server."""
    port = _free_port()
    pid_path = tmp_path / "test.pid"
    pid_path.write_text("42")
    # Write a port file so the join path can discover the port
    port_path = pid_path.with_suffix(".port")
    port_path.write_text(str(port))

    from wesktop.desktop import run

    run(
        "myapp:app",
        host="127.0.0.1",
        pid_path=pid_path,
        single_instance=True,
    )

    mock_stop.assert_not_called()
    mock_serve_bg.assert_not_called()
    mock_create_window.assert_called_once()
    call_kwargs = mock_create_window.call_args
    assert f":{port}" in call_kwargs.kwargs.get("url", call_kwargs.args[1] if len(call_kwargs.args) > 1 else "")


@patch("wesktop.desktop._has_gui_backend", return_value=True)
@patch("webview.start")
@patch("webview.create_window")
@patch("wesktop.server.serve_background")
@patch("wesktop.server.check_already_running", return_value=42)
def test_run_single_instance_false_proceeds_with_conflict(
    mock_check: MagicMock,
    mock_serve_bg: MagicMock,
    mock_create_window: MagicMock,
    mock_wv_start: MagicMock,
    _mock_gui: MagicMock,
    tmp_path: Path,
) -> None:
    """run() with single_instance=False proceeds even with an existing PID."""
    port = _free_port()
    pid_path = tmp_path / "test.pid"
    pid_path.write_text("42")
    mock_serve_bg.return_value = f"http://127.0.0.1:{port}"

    from wesktop.desktop import run

    run(
        "myapp:app",
        host="127.0.0.1",
        port=port,
        pid_path=pid_path,
        single_instance=False,
    )

    # serve_background() should be called (not short-circuited)
    mock_serve_bg.assert_called_once()
    mock_create_window.assert_called_once()


@patch("wesktop.desktop._has_gui_backend", return_value=True)
@patch("webview.start")
@patch("webview.create_window")
@patch("wesktop.server.serve_background")
@patch("wesktop.server.check_already_running", return_value=None)
def test_run_single_instance_no_conflict_proceeds(
    mock_check: MagicMock,
    mock_serve_bg: MagicMock,
    mock_create_window: MagicMock,
    mock_wv_start: MagicMock,
    _mock_gui: MagicMock,
    tmp_path: Path,
) -> None:
    """run() with single_instance=True and no existing instance proceeds normally."""
    port = _free_port()
    pid_path = tmp_path / "test.pid"
    mock_serve_bg.return_value = f"http://127.0.0.1:{port}"

    from wesktop.desktop import run

    run(
        "myapp:app",
        host="127.0.0.1",
        port=port,
        pid_path=pid_path,
        single_instance=True,
    )

    mock_serve_bg.assert_called_once()
    mock_create_window.assert_called_once()
