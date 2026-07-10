from __future__ import annotations

import socket
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import wesktop


def _free_port() -> int:
    """Find an ephemeral port that is currently free."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(autouse=True)
def runtime_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate the default PID path location from the real user runtime dir."""
    rt = tmp_path / "runtime"
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(rt))
    return rt


@pytest.fixture(autouse=True)
def _reset_window_counts() -> None:
    """Clear window reference counts between tests."""
    from wesktop.desktop import _window_counts
    _window_counts.clear()


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
    runtime_dir: Path,
) -> None:
    """Server starts before window; correct title/url/size passed to create_window; start() called."""
    port = _free_port()
    mock_serve_bg.return_value = f"http://127.0.0.1:{port}"

    from wesktop.desktop import run

    run("myapp:app", title="Test", width=800, height=600, host="127.0.0.1", port=port)

    # Server started via serve_background() as an independent process,
    # with the stable per-app default PID path
    mock_serve_bg.assert_called_once_with(
        "myapp:app",
        host="127.0.0.1",
        port=port,
        pid_path=runtime_dir / "wesktop" / "wesktop.pid",
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


@patch("fastware.server._make_embed_server")
def test_serve_calls_embed_server(mock_make_embed: MagicMock) -> None:
    """wesktop.serve() delegates to the embed server for background mode."""
    mock_embed = MagicMock()

    async def _noop_serve():
        pass

    mock_embed.serve = _noop_serve
    mock_make_embed.return_value = mock_embed

    async def fake_app(scope, receive, send):
        pass

    port = _free_port()
    wesktop.serve(fake_app, foreground=False, host="127.0.0.1", port=port, name="TEST_SVC")
    # Give the daemon thread a moment to call asyncio.run(embed.serve())
    time.sleep(0.1)

    mock_make_embed.assert_called_once_with(fake_app, "127.0.0.1", port)


def _purge_wesktop_lazy_cache() -> None:
    """Drop wesktop's cached PEP 562 lazy attributes for wesktop.desktop.

    After popping/reloading wesktop.desktop, the wesktop package may still
    cache function objects from the old module (its __getattr__ caches on
    first access). Purging makes them re-resolve against the fresh module,
    so later patches of wesktop.desktop attributes stay effective.
    """
    pkg = sys.modules.get("wesktop")
    if pkg is not None:
        for attr in ("run", "ensure_gui_backend"):
            pkg.__dict__.pop(attr, None)


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
    _purge_wesktop_lazy_cache()


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
    _purge_wesktop_lazy_cache()

    with patch("builtins.__import__", side_effect=fake_import):
        with patch("wesktop.server.serve_background", return_value=url):
            with pytest.raises(RuntimeError, match="pywebview is not installed"):
                wesktop.desktop.run("myapp:app", host="127.0.0.1", port=port)

    # Clean up
    importlib.reload(wesktop.desktop)
    _purge_wesktop_lazy_cache()


# --- _has_gui_backend unit tests ---

def test_has_gui_backend_non_linux_delegates_truthfully() -> None:
    """On non-Linux platforms, _has_gui_backend reports the real availability."""
    from wesktop.desktop import _has_gui_backend

    with (
        patch("sys.platform", "darwin"),
        patch("wesktop.desktop.ensure_gui_backend", return_value=False),
    ):
        assert _has_gui_backend() is False

    with (
        patch("sys.platform", "win32"),
        patch("wesktop.desktop.ensure_gui_backend", return_value=True),
    ):
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
@patch("wesktop.entries.entry_exists", return_value=False)
def test_auto_register_creates_entry_when_missing(
    mock_exists: MagicMock,
    mock_create: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_auto_register_entry creates a launcher script and a desktop entry."""
    from wesktop.desktop import _auto_register_entry

    monkeypatch.setattr("wesktop.entries._launcher_dir", lambda: tmp_path / "bin")
    with (
        patch("wesktop.desktop.Path.home", return_value=tmp_path),
        patch("sys.argv", ["/usr/bin/myapp", "open"]),
    ):
        _auto_register_entry("MyApp", None)

    mock_create.assert_called_once()
    kwargs = mock_create.call_args.kwargs
    assert kwargs["name"] == "MyApp"
    assert kwargs["icon"] is None
    assert kwargs["comment"] == ""

    launcher = tmp_path / "bin" / "myapp-open"
    assert launcher.exists()
    assert launcher.read_text() == "#!/bin/sh\nexec /usr/bin/myapp open\n"
    assert kwargs["command"] == str(launcher)


@patch("wesktop.entries.create_entry")
@patch("wesktop.entries.entry_exists", return_value=False)
def test_auto_register_quotes_command_with_spaces(
    mock_exists: MagicMock,
    mock_create: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Launcher command and Exec target are shell-quoted when paths contain spaces."""
    import shlex

    from wesktop.desktop import _auto_register_entry

    monkeypatch.setattr("wesktop.entries._launcher_dir", lambda: tmp_path / "my bin")
    with (
        patch("wesktop.desktop.Path.home", return_value=tmp_path),
        patch("sys.argv", ["/opt/My App/bin/myapp", "open"]),
    ):
        _auto_register_entry("MyApp", None)

    launcher = tmp_path / "my bin" / "myapp-open"
    assert launcher.read_text() == "#!/bin/sh\nexec '/opt/My App/bin/myapp' open\n"
    assert mock_create.call_args.kwargs["command"] == shlex.quote(str(launcher))


@patch("wesktop.entries.create_entry")
@patch("wesktop.entries.entry_exists", return_value=False)
def test_auto_register_python_dash_m_launch(
    mock_exists: MagicMock,
    mock_create: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `python -m pkg` launch builds `sys.executable -m pkg`, not __main__.py."""
    import importlib.machinery
    import shlex
    import types

    from wesktop.desktop import _auto_register_entry

    monkeypatch.setattr("wesktop.entries._launcher_dir", lambda: tmp_path / "bin")
    fake_main = types.ModuleType("__main__")
    fake_main.__spec__ = importlib.machinery.ModuleSpec("mypkg.__main__", None)
    with (
        patch("wesktop.desktop.Path.home", return_value=tmp_path),
        patch("sys.argv", ["/venv/lib/python3.13/site-packages/mypkg/__main__.py", "open"]),
        patch.dict(sys.modules, {"__main__": fake_main}),
    ):
        _auto_register_entry("MyApp", None)

    launcher = tmp_path / "bin" / "myapp-open"
    expected = f"#!/bin/sh\nexec {shlex.quote(sys.executable)} -m mypkg open\n"
    assert launcher.read_text() == expected


@patch("wesktop.entries.create_entry")
@patch("wesktop.entries.entry_exists", return_value=False)
def test_auto_register_python_dash_m_without_spec(
    mock_exists: MagicMock,
    mock_create: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without __main__.__spec__, the package is derived from the argv[0] path."""
    import shlex
    import types

    from wesktop.desktop import _auto_register_entry

    monkeypatch.setattr("wesktop.entries._launcher_dir", lambda: tmp_path / "bin")
    fake_main = types.ModuleType("__main__")
    fake_main.__spec__ = None
    with (
        patch("wesktop.desktop.Path.home", return_value=tmp_path),
        patch("sys.argv", ["/venv/lib/python3.13/site-packages/otherpkg/__main__.py", "open"]),
        patch.dict(sys.modules, {"__main__": fake_main}),
    ):
        _auto_register_entry("MyApp", None)

    launcher = tmp_path / "bin" / "myapp-open"
    expected = f"#!/bin/sh\nexec {shlex.quote(sys.executable)} -m otherpkg open\n"
    assert launcher.read_text() == expected


@patch("wesktop.entries.create_entry")
@patch("wesktop.entries.create_launcher")
@patch("wesktop.entries.entry_exists", return_value=False)
def test_auto_register_windows_uses_direct_target(
    mock_exists: MagicMock,
    mock_create_launcher: MagicMock,
    mock_create: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On Windows the shortcut points directly at the target -- no POSIX launcher script."""
    from wesktop.desktop import _auto_register_entry

    monkeypatch.setattr("wesktop.desktop.platform.system", lambda: "Windows")
    with patch("sys.argv", ["C:\\Program Files\\MyApp\\myapp.exe", "open"]):
        _auto_register_entry("MyApp", None)

    mock_create_launcher.assert_not_called()
    mock_create.assert_called_once()
    assert (
        mock_create.call_args.kwargs["command"]
        == '"C:\\Program Files\\MyApp\\myapp.exe" open'
    )


@patch("wesktop.entries.create_entry")
@patch("wesktop.entries.entry_exists", return_value=True)
def test_auto_register_skips_when_exists(
    mock_exists: MagicMock,
    mock_create: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_auto_register_entry does nothing when the entry exists and launcher is valid."""
    from wesktop.desktop import _auto_register_entry

    monkeypatch.setattr("wesktop.entries._launcher_dir", lambda: tmp_path / "bin")
    # Create a fake launcher so the self-healing check passes
    launcher = tmp_path / "bin" / "myapp-open"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.touch()

    with patch("wesktop.desktop.Path.home", return_value=tmp_path):
        _auto_register_entry("MyApp", None)

    mock_create.assert_not_called()


@patch("wesktop.entries.create_entry")
@patch("wesktop.entries.entry_exists", return_value=True)
def test_auto_register_windows_existing_entry_is_valid(
    mock_exists: MagicMock,
    mock_create: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On Windows there is no launcher to self-heal -- an existing entry is kept."""
    from wesktop.desktop import _auto_register_entry

    monkeypatch.setattr("wesktop.desktop.platform.system", lambda: "Windows")
    _auto_register_entry("MyApp", None)

    mock_create.assert_not_called()


@patch("wesktop.entries.create_entry")
@patch("wesktop.entries.remove_entry")
@patch("wesktop.entries.entry_exists", return_value=True)
def test_auto_register_self_heals_broken_launcher(
    mock_exists: MagicMock,
    mock_remove: MagicMock,
    mock_create: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_auto_register_entry removes and recreates entry when launcher is missing."""
    from wesktop.desktop import _auto_register_entry

    monkeypatch.setattr("wesktop.entries._launcher_dir", lambda: tmp_path / "bin")
    # No launcher exists at <bin>/myapp-open -- simulates uninstall
    with (
        patch("wesktop.desktop.Path.home", return_value=tmp_path),
        patch("sys.argv", ["/usr/bin/myapp", "open"]),
    ):
        _auto_register_entry("MyApp", None)

    # The broken entry should have been removed
    mock_remove.assert_called_once_with("MyApp")
    # And a new entry should have been created
    mock_create.assert_called_once()


@patch("wesktop.entries.entry_exists", side_effect=OSError("disk on fire"))
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

    # The server was NOT started by this invocation (it was already running)
    mock_serve_bg.assert_not_called()
    mock_create_window.assert_called_once()
    call_kwargs = mock_create_window.call_args
    assert f":{port}" in call_kwargs.kwargs.get("url", call_kwargs.args[1] if len(call_kwargs.args) > 1 else "")
    # Last window closed -> stop is called for the joined server
    mock_stop.assert_called_once_with(pid_path)


@patch("wesktop.desktop._has_gui_backend", return_value=True)
@patch("webview.start")
@patch("webview.create_window")
@patch("wesktop.server.serve_background")
@patch("wesktop.server.stop")
@patch("wesktop.server.check_already_running", return_value=42)
def test_run_single_instance_false_proceeds_with_conflict(
    mock_check: MagicMock,
    mock_stop: MagicMock,
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


@patch("wesktop.desktop._has_gui_backend", return_value=True)
@patch("webview.start")
@patch("webview.create_window")
@patch("wesktop.server.serve_background")
def test_run_single_instance_uses_real_check_signature(
    mock_serve_bg: MagicMock,
    mock_create_window: MagicMock,
    mock_wv_start: MagicMock,
    _mock_gui: MagicMock,
    tmp_path: Path,
) -> None:
    """run() calls fastware's check_already_running with its real one-arg signature."""
    port = _free_port()
    mock_serve_bg.return_value = f"http://127.0.0.1:{port}"
    pid_path = tmp_path / "app.pid"  # no such file -> no running instance

    from wesktop.desktop import run

    # Unpatched check_already_running: a wrong-arity call raises TypeError here
    run("myapp:app", host="127.0.0.1", port=port, pid_path=pid_path, single_instance=True)

    mock_serve_bg.assert_called_once()
    mock_create_window.assert_called_once()


# --- pre_serve / reload semantics ---


def test_run_rejects_pre_serve() -> None:
    """run()'s server is a detached subprocess; in-process pre_serve would be
    silently invisible to it -- hard error instead of silent divergence."""
    from wesktop.desktop import run

    called: list[int] = []
    with pytest.raises(ValueError, match="pre_serve"):
        run("myapp:app", pre_serve=lambda: called.append(1))
    assert called == []  # never executed in the wrong process


def test_run_rejects_reload() -> None:
    """reload cannot work for run()'s detached server subprocess -- hard error,
    not silently accepted-and-ignored."""
    from wesktop.desktop import run

    with pytest.raises(ValueError, match="reload"):
        run("myapp:app", reload=True)


# --- default PID path ---


def test_default_pid_path_linux_xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Linux default PID path lives under XDG_RUNTIME_DIR, slugged per app name."""
    from wesktop.desktop import _default_pid_path

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "rt"))
    monkeypatch.setattr("wesktop.desktop.platform.system", lambda: "Linux")

    p = _default_pid_path("My App")
    assert p == tmp_path / "rt" / "wesktop" / "my-app.pid"
    assert p.parent.is_dir()


def test_default_pid_path_linux_without_xdg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without XDG_RUNTIME_DIR, the XDG state dir is used."""
    from wesktop.desktop import _default_pid_path

    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setattr("wesktop.desktop.platform.system", lambda: "Linux")

    with patch("wesktop.desktop.Path.home", return_value=tmp_path):
        p = _default_pid_path("WESKTOP")
    assert p == tmp_path / ".local" / "state" / "wesktop" / "wesktop.pid"


def test_default_pid_path_darwin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from wesktop.desktop import _default_pid_path

    monkeypatch.setattr("wesktop.desktop.platform.system", lambda: "Darwin")
    with patch("wesktop.desktop.Path.home", return_value=tmp_path):
        p = _default_pid_path("WESKTOP")
    assert p == tmp_path / "Library" / "Application Support" / "wesktop" / "wesktop.pid"


def test_default_pid_path_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from wesktop.desktop import _default_pid_path

    monkeypatch.setattr("wesktop.desktop.platform.system", lambda: "Windows")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    p = _default_pid_path("WESKTOP")
    assert p == tmp_path / "AppData" / "Local" / "wesktop" / "wesktop.pid"


def test_default_pid_path_windows_requires_localappdata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No implicit fallback location on Windows -- LOCALAPPDATA must be set."""
    from wesktop.desktop import _default_pid_path

    monkeypatch.setattr("wesktop.desktop.platform.system", lambda: "Windows")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    with pytest.raises(OSError, match="LOCALAPPDATA"):
        _default_pid_path("WESKTOP")


@patch("wesktop.desktop._has_gui_backend", return_value=True)
@patch("webview.start")
@patch("webview.create_window")
@patch("wesktop.server.serve_background")
def test_run_default_pid_path_is_stable(
    mock_serve_bg: MagicMock,
    mock_create_window: MagicMock,
    mock_wv_start: MagicMock,
    _mock_gui: MagicMock,
    runtime_dir: Path,
) -> None:
    """The default PID path is absolute and per-app, not CWD-relative."""
    port = _free_port()
    mock_serve_bg.return_value = f"http://127.0.0.1:{port}"

    from wesktop.desktop import run

    run("myapp:app", host="127.0.0.1", port=port)

    pid_path = mock_serve_bg.call_args.kwargs["pid_path"]
    assert pid_path == runtime_dir / "wesktop" / "wesktop.pid"
    assert pid_path.is_absolute()


# --- server lifecycle (reference-counted stop on last window close) ---


@patch("wesktop.desktop._has_gui_backend", return_value=True)
@patch("webview.start")
@patch("webview.create_window")
@patch("wesktop.server.serve_background")
@patch("wesktop.server.stop")
def test_single_window_close_stops_server(
    mock_stop: MagicMock,
    mock_serve_bg: MagicMock,
    mock_create_window: MagicMock,
    mock_wv_start: MagicMock,
    _mock_gui: MagicMock,
    tmp_path: Path,
) -> None:
    """When the only window closes, stop() is called with the correct pid_path."""
    port = _free_port()
    pid_path = tmp_path / "app.pid"
    mock_serve_bg.return_value = f"http://127.0.0.1:{port}"

    from wesktop.desktop import run

    run("myapp:app", host="127.0.0.1", port=port, pid_path=pid_path)

    mock_stop.assert_called_once_with(pid_path)


@patch("wesktop.desktop._has_gui_backend", return_value=True)
@patch("webview.start")
@patch("webview.create_window")
@patch("wesktop.server.serve_background")
@patch("wesktop.server.stop")
@patch("wesktop.server.check_already_running")
@patch("wesktop.server.read_port_file")
def test_two_windows_first_close_no_stop_second_stops(
    mock_read_port: MagicMock,
    mock_check: MagicMock,
    mock_stop: MagicMock,
    mock_serve_bg: MagicMock,
    mock_create_window: MagicMock,
    mock_wv_start: MagicMock,
    _mock_gui: MagicMock,
    tmp_path: Path,
) -> None:
    """With two windows (primary + joined), the first close does not stop; the second does."""
    port = _free_port()
    pid_path = tmp_path / "app.pid"
    mock_serve_bg.return_value = f"http://127.0.0.1:{port}"
    # First call: no existing instance
    mock_check.return_value = None

    from wesktop.desktop import run, _window_counts

    # Window 1: primary (starts server)
    run("myapp:app", host="127.0.0.1", port=port, pid_path=pid_path, single_instance=True)

    # After window 1 closes, count should be 0 and stop should be called
    # But we want to simulate TWO windows. So we need to pre-increment
    # the count to simulate another window being open.
    # Let's reset and do it properly: simulate the primary window opening,
    # then a join window opening, then the join closing, then the primary closing.

    # Reset state
    mock_stop.reset_mock()
    _window_counts.clear()

    # Simulate: primary opens (increments to 1), join opens (increments to 2),
    # join closes (decrements to 1, no stop), primary closes (decrements to 0, stop).
    # We need to interleave the webview.start() calls. Since webview.start() blocks,
    # the second window must be opened in a different thread in reality.
    # In tests, we can simulate by manipulating _window_counts directly.

    key = str(pid_path)

    # Simulate primary window opened
    _window_counts[key] = 2  # primary + joined both open

    # Simulate joined window closing (decrement)
    _window_counts[key] -= 1
    assert _window_counts[key] == 1
    # Count > 0, so stop should NOT be called
    mock_stop.assert_not_called()

    # Simulate primary window closing (decrement)
    _window_counts[key] -= 1
    assert _window_counts[key] == 0
    # Count reaches 0 -- stop the server
    _window_counts.pop(key, None)
    from wesktop.server import stop
    try:
        stop(pid_path)
    except (FileNotFoundError, ProcessLookupError):
        pass
    mock_stop.assert_called_once_with(pid_path)


@patch("wesktop.desktop._has_gui_backend", return_value=True)
@patch("webview.start")
@patch("webview.create_window")
@patch("wesktop.server.serve_background")
@patch("wesktop.server.stop", side_effect=FileNotFoundError("no pid"))
def test_stop_file_not_found_handled_gracefully(
    mock_stop: MagicMock,
    mock_serve_bg: MagicMock,
    mock_create_window: MagicMock,
    mock_wv_start: MagicMock,
    _mock_gui: MagicMock,
    tmp_path: Path,
) -> None:
    """FileNotFoundError from stop() is handled gracefully -- no crash."""
    port = _free_port()
    pid_path = tmp_path / "app.pid"
    mock_serve_bg.return_value = f"http://127.0.0.1:{port}"

    from wesktop.desktop import run

    # Must not raise even though stop() raises FileNotFoundError
    run("myapp:app", host="127.0.0.1", port=port, pid_path=pid_path)

    mock_stop.assert_called_once_with(pid_path)


@patch("wesktop.desktop._has_gui_backend", return_value=True)
@patch("webview.start")
@patch("webview.create_window")
@patch("wesktop.server.stop", side_effect=ProcessLookupError("no process"))
@patch("wesktop.server.check_already_running", return_value=42)
@patch("wesktop.server.read_port_file")
def test_stop_process_lookup_error_handled_in_join_path(
    mock_read_port: MagicMock,
    mock_check: MagicMock,
    mock_stop: MagicMock,
    mock_create_window: MagicMock,
    mock_wv_start: MagicMock,
    _mock_gui: MagicMock,
    tmp_path: Path,
) -> None:
    """ProcessLookupError from stop() in the join path is handled gracefully."""
    port = _free_port()
    pid_path = tmp_path / "app.pid"
    pid_path.write_text("42")
    port_path = pid_path.with_suffix(".port")
    port_path.write_text(str(port))
    mock_read_port.return_value = port

    from wesktop.desktop import run

    # Must not raise even though stop() raises ProcessLookupError
    run("myapp:app", host="127.0.0.1", pid_path=pid_path, single_instance=True)

    mock_stop.assert_called_once_with(pid_path)
