from __future__ import annotations

import json
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
        **wesktop.WindowChrome().as_window_kwargs(),
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
        **wesktop.WindowChrome().as_window_kwargs(),
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
        **wesktop.WindowChrome().as_window_kwargs(),
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


@patch("wesktop.desktop._has_gui_backend", return_value=True)
@patch("webview.start")
@patch("webview.create_window")
@patch("wesktop.server.serve_background")
def test_run_captures_window_handle(
    mock_serve_bg: MagicMock,
    mock_create_window: MagicMock,
    mock_wv_start: MagicMock,
    _mock_gui: MagicMock,
) -> None:
    """run() captures webview.create_window's return into the module-level
    active window handle (previously discarded)."""
    import wesktop.desktop as dt

    port = _free_port()
    mock_serve_bg.return_value = f"http://127.0.0.1:{port}"
    sentinel = MagicMock(name="window")
    mock_create_window.return_value = sentinel

    from wesktop.desktop import run

    run("myapp:app", host="127.0.0.1", port=port)

    assert dt._active_window is sentinel


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


def _seed_window_marker(pid_path: Path, pid: int, window_id: str) -> Path:
    """Directly write a window marker owned by an arbitrary PID (simulates another process)."""
    import msgspec

    from fastware.server import _registry_dir

    reg_dir = _registry_dir(pid_path)
    reg_dir.mkdir(parents=True, exist_ok=True)
    path = reg_dir / f"window--{pid}--{window_id}.marker"
    path.write_bytes(
        msgspec.json.encode(
            {"pid": pid, "marker_id": window_id, "kind": "window", "window_id": window_id}
        )
    )
    return path


@pytest.fixture
def live_pid() -> int:
    """A real, live subprocess PID that lasts for the test (torn down after)."""
    import subprocess

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        yield proc.pid
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@patch("wesktop.desktop._has_gui_backend", return_value=True)
@patch("webview.start")
@patch("webview.create_window")
@patch("wesktop.server.serve_background")
@patch("wesktop.server.stop")
@patch("wesktop.server.check_already_running", return_value=42)
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
    live_pid: int,
) -> None:
    """Cross-process refcount: closing one window while another process's window
    is still open must NOT stop the shared server; closing the last must.

    Simulates two processes via two window marker files -- one owned by a real
    live PID (the "other process"). This process joins the existing server, opens
    a window, and closes it.
    """
    port = _free_port()
    pid_path = tmp_path / "app.pid"
    pid_path.write_text("42")
    mock_read_port.return_value = port

    # Other process (live PID) has an open window.
    other_marker = _seed_window_marker(pid_path, live_pid, "wb")

    from wesktop.desktop import run

    # This process joins, opens a window, and closes it (webview.start mocked).
    run("myapp:app", host="127.0.0.1", pid_path=pid_path, single_instance=True)

    # The other process's window marker is still live -> server must NOT be stopped.
    mock_stop.assert_not_called()
    assert other_marker.exists()

    # Now the other process's window closes: remove its marker, then this process
    # opens+closes the last window -> server IS stopped.
    other_marker.unlink()
    mock_stop.reset_mock()
    run("myapp:app", host="127.0.0.1", pid_path=pid_path, single_instance=True)
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


# --- Phase 14: URL helpers ---


def test_app_url_and_port_helpers() -> None:
    from wesktop.desktop import _app_url, _port_from_url, _version_url

    url = _app_url("127.0.0.1", 8123)
    assert url == "http://127.0.0.1:8123"
    assert _port_from_url(url) == 8123
    assert _version_url(url) == "http://127.0.0.1:8123/__fastware/version"
    assert _version_url(url + "/") == "http://127.0.0.1:8123/__fastware/version"


def test_port_from_url_rejects_portless() -> None:
    from wesktop.desktop import _port_from_url

    with pytest.raises(ValueError, match="no port"):
        _port_from_url("http://127.0.0.1")


# --- Phase 14: second_open configuration ---


def test_second_open_invalid_rejected() -> None:
    from wesktop.desktop import run

    with pytest.raises(ValueError, match="second_open"):
        run("myapp:app", second_open="raise-hell")


@patch("wesktop.desktop._has_gui_backend", return_value=True)
@patch("webview.start")
@patch("webview.create_window")
@patch("wesktop.server.serve_background")
@patch("wesktop.server.stop")
@patch("wesktop.server.check_already_running", return_value=42)
@patch("wesktop.server.read_port_file")
def test_second_open_focus_existing_writes_marker_and_exits(
    mock_read_port: MagicMock,
    mock_check: MagicMock,
    mock_stop: MagicMock,
    mock_serve_bg: MagicMock,
    mock_create_window: MagicMock,
    mock_wv_start: MagicMock,
    _mock_gui: MagicMock,
    tmp_path: Path,
) -> None:
    """focus-existing on a second launch drops a focus-request marker and exits --
    no window is created, no server is started or stopped."""
    from wesktop.desktop import run
    from wesktop.server import list_markers

    port = _free_port()
    pid_path = tmp_path / "app.pid"
    pid_path.write_text("42")
    mock_read_port.return_value = port

    run(
        "myapp:app",
        host="127.0.0.1",
        pid_path=pid_path,
        single_instance=True,
        second_open="focus-existing",
    )

    mock_create_window.assert_not_called()
    mock_wv_start.assert_not_called()
    mock_serve_bg.assert_not_called()
    mock_stop.assert_not_called()

    requests = list_markers(pid_path, "focus-request")
    assert len(requests) == 1
    assert requests[0]["pid"] == __import__("os").getpid()


@patch("wesktop.desktop._require_webview_gui")
@patch("wesktop.server.check_already_running", return_value=42)
@patch("wesktop.server.read_port_file")
def test_focus_existing_needs_no_gui_backend(
    mock_read_port: MagicMock,
    mock_check: MagicMock,
    mock_require_gui: MagicMock,
    tmp_path: Path,
) -> None:
    """focus-existing exits before requiring pywebview/GUI (a signal-only launch)."""
    from wesktop.desktop import run

    port = _free_port()
    pid_path = tmp_path / "app.pid"
    pid_path.write_text("42")
    mock_read_port.return_value = port

    run(
        "myapp:app",
        pid_path=pid_path,
        single_instance=True,
        second_open="focus-existing",
    )
    mock_require_gui.assert_not_called()


# --- Phase 14: startup handshake ---


def _make_version_server(payload: bytes) -> tuple[object, int]:
    """A tiny threaded HTTP server that returns *payload* at /__fastware/version."""
    import http.server
    import threading as _th

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):  # silence
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    t = _th.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, srv.server_address[1]


def test_startup_handshake_success_no_error(capsys: pytest.CaptureFixture) -> None:
    from wesktop.desktop import _app_url, _startup_handshake

    srv, port = _make_version_server(b'{"build_id": "deadbeef"}')
    try:
        build_id = _startup_handshake(_app_url("127.0.0.1", port))
    finally:
        srv.shutdown()
    assert build_id == "deadbeef"
    assert "HANDSHAKE FAILED" not in capsys.readouterr().err


def test_startup_handshake_malformed_is_loud(capsys: pytest.CaptureFixture) -> None:
    from wesktop.desktop import _app_url, _startup_handshake

    srv, port = _make_version_server(b"not json")
    try:
        build_id = _startup_handshake(_app_url("127.0.0.1", port))
    finally:
        srv.shutdown()
    assert build_id is None
    assert "HANDSHAKE FAILED" in capsys.readouterr().err


def test_startup_handshake_unreachable_is_loud(capsys: pytest.CaptureFixture) -> None:
    from wesktop.desktop import _app_url, _startup_handshake

    build_id = _startup_handshake(_app_url("127.0.0.1", _free_port()), timeout=0.5)
    assert build_id is None
    err = capsys.readouterr().err
    assert "HANDSHAKE FAILED" in err


# --- Phase 14: runtime-config injection ---


class _InjectWindow:
    def __init__(self, fail_times: int) -> None:
        self._fail_times = fail_times
        self.calls: list[str] = []

    def evaluate_js(self, script: str) -> None:
        self.calls.append(script)
        if len(self.calls) <= self._fail_times:
            raise RuntimeError("page not ready")


def test_inject_runtime_config_success() -> None:
    from wesktop.desktop import _inject_runtime_config

    w = _InjectWindow(fail_times=0)
    assert _inject_runtime_config(w, "abc", 8123, "MyApp") is True
    assert len(w.calls) == 1
    assert "window.__wesktop" in w.calls[0]
    assert '"buildId": "abc"' in w.calls[0]
    assert '"port": 8123' in w.calls[0]
    assert '"appName": "MyApp"' in w.calls[0]


def test_inject_runtime_config_retries_once() -> None:
    from wesktop.desktop import _inject_runtime_config

    w = _InjectWindow(fail_times=1)  # first call raises, second succeeds
    assert _inject_runtime_config(w, "abc", 8123, "MyApp") is True
    assert len(w.calls) == 2


def test_inject_runtime_config_gives_up_after_retry() -> None:
    from wesktop.desktop import _inject_runtime_config

    w = _InjectWindow(fail_times=99)  # always raises
    assert _inject_runtime_config(w, "abc", 8123, "MyApp") is False
    assert len(w.calls) == 2  # exactly one retry


def test_wire_runtime_config_injection_fires_on_loaded() -> None:
    from wesktop.desktop import _wire_runtime_config_injection

    class _Event:
        def __init__(self) -> None:
            self.handlers: list = []

        def __iadd__(self, h):
            self.handlers.append(h)
            return self

        def fire(self):
            for h in list(self.handlers):
                h()

    class _Events:
        def __init__(self) -> None:
            self.loaded = _Event()

    w = _InjectWindow(fail_times=0)
    w.events = _Events()  # type: ignore[attr-defined]

    _wire_runtime_config_injection(w, "abc", 8123, "MyApp")
    assert w.calls == []  # not injected until the page loads
    w.events.loaded.fire()
    assert len(w.calls) == 1


# --- Phase 14: focus-request poll ---


def test_focus_request_poll_consumes_marker_and_raises() -> None:
    import threading as _th

    from wesktop.desktop import _install_focus_request_poll
    from wesktop.server import list_markers, write_marker

    tmp = Path(__import__("tempfile").mkdtemp())
    pid_path = tmp / "app.pid"

    raised = _th.Event()

    class _Win:
        def restore(self):
            pass

        def show(self):
            raised.set()

    stop_event = _th.Event()
    _install_focus_request_poll(_Win(), pid_path, stop_event, interval=0.05)
    try:
        write_marker(pid_path, "focus-request", "req1")
        assert raised.wait(timeout=3.0), "window was not raised on focus request"
        # The marker was consumed.
        assert list_markers(pid_path, "focus-request", prune_dead=False) == []
    finally:
        stop_event.set()


# --- Phase 14: registry enumeration ---


def test_list_app_instances(tmp_path: Path) -> None:
    from wesktop.desktop import list_app_instances
    from wesktop.server import register_instance, write_marker

    pid_path = tmp_path / "app.pid"
    register_instance(pid_path, port=8123, name="myapp")
    write_marker(pid_path, "window", "w1", fields={"window_id": "w1"})

    snap = list_app_instances(pid_path)
    assert [s.name for s in snap.servers] == ["myapp"]
    assert [m["window_id"] for m in snap.windows] == ["w1"]


# ---------------------------------------------------------------------------
# WindowChrome
# ---------------------------------------------------------------------------


def test_window_chrome_defaults_are_pywebviews() -> None:
    """A bare WindowChrome() carries pywebview's own create_window defaults."""
    import inspect

    import webview

    signature = inspect.signature(webview.create_window)
    for name, value in wesktop.WindowChrome().as_window_kwargs().items():
        assert signature.parameters[name].default == value, name


@patch("wesktop.desktop._has_gui_backend", return_value=True)
@patch("webview.start")
@patch("webview.create_window")
@patch("wesktop.server.serve_background")
def test_run_forwards_chrome(
    mock_serve_bg: MagicMock,
    mock_create_window: MagicMock,
    mock_wv_start: MagicMock,
    _mock_gui: MagicMock,
) -> None:
    """A frameless, transparent chrome reaches webview.create_window verbatim."""
    port = _free_port()
    mock_serve_bg.return_value = f"http://127.0.0.1:{port}"

    chrome = wesktop.WindowChrome(
        frameless=True, transparent=True, shadow=False, background_color="#00000000"
    )

    from wesktop.desktop import run

    run("myapp:app", host="127.0.0.1", port=port, chrome=chrome)

    kwargs = mock_create_window.call_args.kwargs
    assert kwargs["frameless"] is True
    assert kwargs["transparent"] is True
    assert kwargs["shadow"] is False
    assert kwargs["background_color"] == "#00000000"
    # Every other chrome field is still forwarded at its default.
    assert kwargs["resizable"] is True
    assert kwargs["min_size"] == (200, 100)


@patch("wesktop.desktop._has_gui_backend", return_value=True)
@patch("webview.start")
@patch("webview.create_window")
@patch("wesktop.server.check_already_running")
@patch("wesktop.server.read_port_file")
def test_join_forwards_chrome(
    mock_read_port: MagicMock,
    mock_running: MagicMock,
    mock_create_window: MagicMock,
    mock_wv_start: MagicMock,
    _mock_gui: MagicMock,
    tmp_path: Path,
) -> None:
    """The single-instance JOIN path opens its window with the same chrome."""
    port = _free_port()
    mock_running.return_value = 4242
    mock_read_port.return_value = port

    from wesktop.desktop import run

    run(
        "myapp:app",
        host="127.0.0.1",
        pid_path=tmp_path / "app.pid",
        chrome=wesktop.WindowChrome(frameless=True, on_top=True),
    )

    kwargs = mock_create_window.call_args.kwargs
    assert kwargs["frameless"] is True
    assert kwargs["on_top"] is True
    assert kwargs["url"] == f"http://127.0.0.1:{port}"


# ---------------------------------------------------------------------------
# Frameless-window host operations
# ---------------------------------------------------------------------------


class _FakeGtkWindow:
    """Stand-in GTK toplevel recording what was asked of it."""

    def __init__(self) -> None:
        self.regions: list[object] = []
        self.drags: list[int] = []

    def input_shape_combine_region(self, region: object) -> None:
        self.regions.append(region)

    def begin_move_drag(self, button: int, x: int, y: int, time: int) -> None:
        self.drags.append(button)

    def get_display(self) -> object:
        raise AssertionError("the test drives begin_move_drag directly")


def _fake_pywebview_window(gtk_window: object | None) -> object:
    """A pywebview-shaped window handle whose GTK toplevel is *gtk_window*."""
    browser_view = MagicMock()
    browser_view.instances = {} if gtk_window is None else {"w1": MagicMock(window=gtk_window)}
    gui = MagicMock()
    gui.BrowserView = browser_view
    window = MagicMock()
    window.gui = gui
    window.uid = "w1"
    return window


def test_active_window_is_none_before_any_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """active_window() answers None rather than raising when nothing is open."""
    from wesktop import desktop

    monkeypatch.setattr(desktop, "_active_window", None)
    assert desktop.active_window() is None


def test_active_window_returns_the_captured_handle(monkeypatch: pytest.MonkeyPatch) -> None:
    """The handle _wire_runtime_bridge captured is what active_window() hands back."""
    from wesktop import desktop

    sentinel = object()
    monkeypatch.setattr(desktop, "_active_window", sentinel)
    assert desktop.active_window() is sentinel


def test_set_input_region_refuses_a_non_gtk_backend() -> None:
    """A backend with no GTK toplevel is named in the error, and nothing changes."""
    from wesktop.desktop import set_input_region

    with pytest.raises(RuntimeError, match="GTK backend only"):
        set_input_region(_fake_pywebview_window(None), [(0, 0, 10, 10)])


def test_begin_window_drag_refuses_a_non_gtk_backend() -> None:
    """The drag refuses the same way, rather than silently doing nothing."""
    from wesktop.desktop import begin_window_drag

    with pytest.raises(RuntimeError, match="GTK backend only"):
        begin_window_drag(_fake_pywebview_window(None))


def test_set_input_region_builds_a_region_from_the_rectangles() -> None:
    """Each rectangle reaches cairo.Region, and the work is queued on the GTK loop."""
    wesktop.ensure_gui_backend()  # makes the system PyGObject importable here
    cairo = pytest.importorskip("cairo")
    glib = pytest.importorskip("gi.repository.GLib")

    gtk_window = _FakeGtkWindow()
    window = _fake_pywebview_window(gtk_window)

    queued: list[object] = []
    with patch.object(glib, "idle_add", side_effect=lambda fn: queued.append(fn)):
        from wesktop.desktop import set_input_region

        set_input_region(window, [(4, 5, 60, 70), (0, 0, 10, 10)])

    assert len(queued) == 1
    queued[0]()  # run what would have run on the GTK main loop

    assert len(gtk_window.regions) == 1
    region = gtk_window.regions[0]
    assert isinstance(region, cairo.Region)
    assert region.contains_point(10, 10)
    assert not region.contains_point(500, 500)


def test_set_input_region_none_restores_the_whole_window() -> None:
    """Passing None hands GTK a null region, which is how the default comes back."""
    wesktop.ensure_gui_backend()  # makes the system PyGObject importable here
    glib = pytest.importorskip("gi.repository.GLib")
    pytest.importorskip("cairo")

    gtk_window = _FakeGtkWindow()
    window = _fake_pywebview_window(gtk_window)

    queued: list[object] = []
    with patch.object(glib, "idle_add", side_effect=lambda fn: queued.append(fn)):
        from wesktop.desktop import set_input_region

        set_input_region(window, None)

    queued[0]()
    assert gtk_window.regions == [None]


# ---------------------------------------------------------------------------
# Window capture
# ---------------------------------------------------------------------------


def test_capture_window_refuses_a_non_gtk_backend(tmp_path: Path) -> None:
    """A backend with no WebKit view is named, and no file is written."""
    from wesktop.desktop import capture_window

    out = tmp_path / "shot.png"
    with pytest.raises(RuntimeError, match="GTK backend only"):
        capture_window(_fake_pywebview_window(None), out)
    assert not out.exists()


def test_wire_capture_is_a_no_op_without_a_path() -> None:
    """No capture_to means the loaded event is left exactly as it was."""
    from wesktop.desktop import _wire_capture

    window = MagicMock()
    before = window.events.loaded
    _wire_capture(window, None, 0.0)
    assert window.events.loaded is before


def test_wire_capture_refuses_a_build_without_a_loaded_event(tmp_path: Path) -> None:
    """A pywebview with no loaded event is an error, not a capture that never happens."""
    from wesktop.desktop import _wire_capture

    class _NoEvents:
        events = None

    with pytest.raises(RuntimeError, match="no window 'loaded' event"):
        _wire_capture(_NoEvents(), tmp_path / "shot.png", 0.0)


@patch("wesktop.desktop._has_gui_backend", return_value=True)
@patch("webview.start")
@patch("webview.create_window")
@patch("wesktop.server.serve_background")
def test_run_captures_on_load(
    mock_serve_bg: MagicMock,
    mock_create_window: MagicMock,
    mock_wv_start: MagicMock,
    _mock_gui: MagicMock,
    tmp_path: Path,
) -> None:
    """run(capture_to=...) hangs a capture on the window's loaded event."""
    port = _free_port()
    mock_serve_bg.return_value = f"http://127.0.0.1:{port}"

    handlers: list[object] = []

    class _Loaded:
        def __iadd__(self, handler: object) -> "_Loaded":
            handlers.append(handler)
            return self

    window = MagicMock()
    window.events.loaded = _Loaded()
    # No GTK backend behind this window, so the zoom lock that shares the
    # loaded event skips itself and only the capture is exercised.
    window.gui = None
    mock_create_window.return_value = window

    out = tmp_path / "shot.png"
    with patch("wesktop.desktop.capture_window", return_value=out) as mock_capture:
        from wesktop.desktop import run

        run("myapp:app", host="127.0.0.1", port=port, capture_to=out, capture_delay=0.0)

        # The runtime-config injection hangs on the same event; the capture is
        # the one that reaches capture_window.
        assert handlers
        for handler in handlers:
            handler()
        time.sleep(0.5)

    mock_capture.assert_called_once_with(window, out)


# ---------------------------------------------------------------------------
# Headless runs
# ---------------------------------------------------------------------------


def test_headless_serves_and_stops(tmp_path: Path) -> None:
    """A real headless run answers over HTTP and is stopped when the block ends."""
    import urllib.error
    import urllib.request

    app_file = tmp_path / "headless_app.py"
    app_file.write_text(
        "import wesktop\n"
        "router = wesktop.Router()\n"
        "@router.get('/health')\n"
        "async def health(req):\n"
        "    return {'status': 'ok'}\n"
        "app = wesktop.create_app(router)\n"
    )
    monkeypatched = sys.path[:]
    sys.path.insert(0, str(tmp_path))
    try:
        with wesktop.headless("headless_app:app", pid_path=tmp_path / "app.pid") as app:
            assert app.port > 0
            assert app.url == f"http://127.0.0.1:{app.port}"
            assert app.pid_path.exists()
            with urllib.request.urlopen(f"{app.url}/health", timeout=5) as response:
                assert json.loads(response.read())["status"] == "ok"
        # The server is gone with the block.
        with pytest.raises(urllib.error.URLError):
            urllib.request.urlopen(f"{app.url}/health", timeout=2)
    finally:
        sys.path[:] = monkeypatched


def test_headless_never_imports_pywebview(monkeypatch: pytest.MonkeyPatch) -> None:
    """A headless run needs no GUI: importing pywebview would be a hard error here."""
    calls: dict[str, object] = {}

    def _fake_serve_background(target, *, host, port, pid_path, name):
        calls["pid_path"] = pid_path
        return f"http://{host}:4321"

    def _fake_stop(pid_path):
        calls["stopped"] = pid_path

    monkeypatch.setattr("wesktop.server.serve_background", _fake_serve_background)
    monkeypatch.setattr("wesktop.server.stop", _fake_stop)
    monkeypatch.setattr(
        "wesktop.desktop._require_webview_gui",
        lambda: (_ for _ in ()).throw(AssertionError("a headless run must not need a GUI")),
    )

    with wesktop.headless("myapp:app") as app:
        assert app.port == 4321
        private_dir = app.pid_path.parent

    assert calls["stopped"] == calls["pid_path"]
    # The private pid directory it made for itself is gone too.
    assert not private_dir.exists()


def test_headless_stops_the_server_when_the_block_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An exception inside the block still stops the server -- no leaked instance."""
    stopped: list[Path] = []
    monkeypatch.setattr(
        "wesktop.server.serve_background",
        lambda target, *, host, port, pid_path, name: f"http://{host}:5555",
    )
    monkeypatch.setattr("wesktop.server.stop", lambda pid_path: stopped.append(pid_path))

    pid_path = tmp_path / "app.pid"
    with pytest.raises(ValueError, match="boom"):
        with wesktop.headless("myapp:app", pid_path=pid_path):
            raise ValueError("boom")

    assert stopped == [pid_path]


# ---------------------------------------------------------------------------
# Zoom lock
# ---------------------------------------------------------------------------


def test_zoom_lock_is_skipped_on_a_non_gtk_backend() -> None:
    """No WebKit view means no lock, and no exception either."""
    from wesktop.desktop import _install_zoom_lock

    assert _install_zoom_lock(_fake_pywebview_window(None)) is False


def test_zoom_lock_pins_the_level_and_refuses_the_gestures() -> None:
    """The level snaps back to 1.0, ctrl+scroll is swallowed, pinch is swallowed."""
    wesktop.ensure_gui_backend()
    gdk = pytest.importorskip("gi.repository.Gdk")

    class _FakeWebView:
        def __init__(self) -> None:
            self.level = 3.0
            self.handlers: dict[str, object] = {}

        def set_zoom_level(self, level: float) -> None:
            self.level = level

        def get_zoom_level(self) -> float:
            return self.level

        def connect(self, signal: str, handler: object) -> None:
            self.handlers[signal] = handler

    view = _FakeWebView()
    browser_view = MagicMock()
    browser_view.instances = {"w1": MagicMock(webview=view)}
    gui = MagicMock()
    gui.BrowserView = browser_view
    window = MagicMock()
    window.gui = gui
    window.uid = "w1"

    from wesktop.desktop import _install_zoom_lock

    assert _install_zoom_lock(window) is True
    assert view.level == 1.0  # pinned on install

    # Something rescaled the page: the notify handler undoes it.
    view.level = 2.5
    view.handlers["notify::zoom-level"](view, None)
    assert view.level == 1.0

    # ctrl+scroll is refused; a plain scroll is not.
    on_scroll = view.handlers["scroll-event"]
    assert on_scroll(view, MagicMock(state=gdk.ModifierType.CONTROL_MASK)) is True
    assert on_scroll(view, MagicMock(state=gdk.ModifierType(0))) is False

    # A touchpad pinch is refused; another event is not.
    on_event = view.handlers["event"]
    assert on_event(view, MagicMock(type=gdk.EventType.TOUCHPAD_PINCH)) is True
    assert on_event(view, MagicMock(type=gdk.EventType.BUTTON_PRESS)) is False


def test_zoom_lock_is_not_installed_when_the_app_wants_zoom() -> None:
    """zoomable=True leaves the loaded event untouched."""
    from wesktop.desktop import _wire_zoom_lock

    window = MagicMock()
    before = window.events.loaded
    _wire_zoom_lock(window, zoomable=True)
    assert window.events.loaded is before


# ---------------------------------------------------------------------------
# System theme
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [(0, "no-preference"), (1, "dark"), (2, "light"), (99, "no-preference")],
)
def test_desktop_color_scheme_reads_the_portal(
    value: int, expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The XDG appearance values map to the three answers, unknown ones included."""
    wesktop.ensure_gui_backend()
    pytest.importorskip("gi.repository.Gio")

    from wesktop import desktop

    proxy = MagicMock()
    proxy.call_sync.return_value = MagicMock(unpack=lambda: (value,))
    monkeypatch.setattr(desktop, "_appearance_portal", lambda: proxy)

    assert desktop.desktop_color_scheme() == expected


def test_desktop_color_scheme_without_a_portal(monkeypatch: pytest.MonkeyPatch) -> None:
    """No portal is 'nothing said which to use', not an exception."""
    from wesktop import desktop

    monkeypatch.setattr(desktop, "_appearance_portal", lambda: None)
    assert desktop.desktop_color_scheme() == "no-preference"


def test_desktop_color_scheme_when_the_portal_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A portal that raises is the same answer, and never reaches the caller."""
    wesktop.ensure_gui_backend()
    pytest.importorskip("gi.repository.Gio")

    from wesktop import desktop

    proxy = MagicMock()
    proxy.call_sync.side_effect = RuntimeError("no")
    monkeypatch.setattr(desktop, "_appearance_portal", lambda: proxy)

    assert desktop.desktop_color_scheme() == "no-preference"


def test_gtk_color_scheme_is_applied_as_prefer_dark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """'dark' sets GTK's prefer-dark property; anything else clears it."""
    wesktop.ensure_gui_backend()
    gtk = pytest.importorskip("gi.repository.Gtk")

    from wesktop.desktop import _apply_gtk_color_scheme

    settings = MagicMock()
    monkeypatch.setattr(gtk.Settings, "get_default", staticmethod(lambda: settings))

    _apply_gtk_color_scheme("dark")
    settings.set_property.assert_called_with("gtk-application-prefer-dark-theme", True)

    _apply_gtk_color_scheme("light")
    settings.set_property.assert_called_with("gtk-application-prefer-dark-theme", False)

    _apply_gtk_color_scheme("no-preference")
    settings.set_property.assert_called_with("gtk-application-prefer-dark-theme", False)


def test_theme_follow_subscribes_to_the_portals_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The window keeps following: a colour-scheme change re-applies the scheme."""
    wesktop.ensure_gui_backend()
    pytest.importorskip("gi.repository.GLib")

    from wesktop import desktop

    proxy = MagicMock()
    monkeypatch.setattr(desktop, "_appearance_portal", lambda: proxy)
    applied: list[str] = []
    monkeypatch.setattr(desktop, "desktop_color_scheme", lambda: "dark")
    monkeypatch.setattr(desktop, "_apply_gtk_color_scheme", applied.append)

    queued: list[object] = []
    from gi.repository import GLib

    monkeypatch.setattr(GLib, "idle_add", lambda fn: queued.append(fn))

    window = MagicMock()
    desktop._install_theme_follow(window)

    assert len(queued) == 1
    queued[0]()
    assert applied == ["dark"]

    # The proxy is kept alive on the window, or its subscription would die here.
    assert window._wesktop_appearance_proxy is proxy

    handler = proxy.connect.call_args[0][1]
    params = MagicMock(unpack=lambda: ("org.freedesktop.appearance", "color-scheme", 2))
    handler(proxy, ":1.2", "SettingChanged", params)
    assert len(queued) == 2
    queued[1]()
    assert applied == ["dark", "dark"]

    # An unrelated setting is ignored.
    other = MagicMock(unpack=lambda: ("org.gnome.desktop", "something", 1))
    handler(proxy, ":1.2", "SettingChanged", other)
    assert len(queued) == 2


def test_theme_follow_can_be_declined(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """follow_system_theme=False leaves the desktop preference unread."""
    from wesktop import desktop

    called: list[object] = []
    monkeypatch.setattr(desktop, "_install_theme_follow", called.append)
    monkeypatch.setattr(desktop, "_has_gui_backend", lambda: True)
    monkeypatch.setattr(desktop, "_auto_register_entry", lambda *a, **k: None)

    port = _free_port()
    with patch("wesktop.server.serve_background", return_value=f"http://127.0.0.1:{port}"), \
         patch("webview.create_window", return_value=MagicMock(gui=None)), \
         patch("webview.start"):
        desktop.run(
            "myapp:app",
            host="127.0.0.1",
            port=port,
            pid_path=tmp_path / "app.pid",
            follow_system_theme=False,
        )

    assert called == []
