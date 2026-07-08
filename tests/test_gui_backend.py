"""Tests for ensure_gui_backend() -- system PyGObject discovery for isolated venvs."""

from __future__ import annotations

import builtins
import importlib
import os
import socket
import sys
from unittest.mock import MagicMock, patch

from wesktop.desktop import ensure_gui_backend


def _free_port() -> int:
    """Find an ephemeral port that is currently free."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_ensure_gui_backend_gi_already_importable() -> None:
    """When gi is already importable, returns True without touching sys.path."""
    mock_gi = MagicMock()
    original_path = sys.path.copy()

    with patch.dict(sys.modules, {"gi": mock_gi}):
        result = ensure_gui_backend()

    assert result is True
    assert sys.path == original_path


def test_ensure_gui_backend_finds_system_gi() -> None:
    """When gi is not in the venv, finds it via system site-packages glob."""
    original_import = builtins.__import__
    call_count = 0

    def fake_import(name, *args, **kwargs):
        nonlocal call_count
        if name == "gi":
            call_count += 1
            if call_count == 1:
                # First attempt (venv) fails
                raise ImportError("no gi in venv")
            # Second attempt (after sys.path modification) succeeds
            return MagicMock()
        return original_import(name, *args, **kwargs)

    fake_system_path = "/usr/lib64/python3.12/site-packages"

    with (
        patch("builtins.__import__", side_effect=fake_import),
        patch("wesktop.desktop.glob.glob", return_value=[fake_system_path]),
        patch("os.path.isdir", return_value=True),
    ):
        # Ensure our fake path is not already in sys.path
        original_path = sys.path.copy()
        try:
            result = ensure_gui_backend()
            assert result is True
            assert fake_system_path in sys.path
        finally:
            # Clean up sys.path
            if fake_system_path in sys.path:
                sys.path.remove(fake_system_path)


def test_ensure_gui_backend_returns_false_when_gi_nowhere() -> None:
    """When gi is not available anywhere, returns False."""
    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "gi":
            raise ImportError("no gi anywhere")
        return original_import(name, *args, **kwargs)

    with (
        patch("builtins.__import__", side_effect=fake_import),
        patch("wesktop.desktop.glob.glob", return_value=[]),
    ):
        result = ensure_gui_backend()

    assert result is False


def test_ensure_gui_backend_skips_paths_without_gi_dir() -> None:
    """Paths that exist but don't contain a gi/ directory are skipped."""
    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "gi":
            raise ImportError("no gi")
        return original_import(name, *args, **kwargs)

    fake_path = "/usr/lib64/python3.12/site-packages"

    with (
        patch("builtins.__import__", side_effect=fake_import),
        patch("wesktop.desktop.glob.glob", return_value=[fake_path]),
        patch("os.path.isdir", return_value=False),
    ):
        result = ensure_gui_backend()

    assert result is False
    assert fake_path not in sys.path


def test_run_probes_gui_backend_exactly_once() -> None:
    """run() probes the GUI backend once via _has_gui_backend -- no double probe."""
    port = _free_port()

    with (
        patch("wesktop.desktop.ensure_gui_backend") as mock_ensure,
        patch("wesktop.desktop._has_gui_backend", return_value=True) as mock_has,
        patch("webview.start"),
        patch("webview.create_window"),
        patch("wesktop.server.serve_background", return_value=f"http://127.0.0.1:{port}"),
    ):
        from wesktop.desktop import run

        run("myapp:app", host="127.0.0.1", port=port)

    mock_has.assert_called_once_with()
    # ensure_gui_backend is _has_gui_backend's job now -- run() must not
    # probe a second time.
    mock_ensure.assert_not_called()


def test_has_gui_backend_linux_delegates_gtk_probe_to_ensure() -> None:
    """On Linux, the GTK probe goes through ensure_gui_backend (sys.path fix)."""
    from wesktop.desktop import _has_gui_backend

    with (
        patch("sys.platform", "linux"),
        patch.dict(os.environ, {}, clear=False),
        patch("wesktop.desktop.ensure_gui_backend", return_value=True) as mock_ensure,
    ):
        os.environ.pop("PYWEBVIEW_GUI", None)
        assert _has_gui_backend() is True

    mock_ensure.assert_called_once_with()


# --- Truthful per-platform availability ---


def _fake_find_spec(present: set[str]):
    def fake(name: str, *args, **kwargs):
        return MagicMock() if name in present else None

    return fake


def test_ensure_gui_backend_win32_pywebview_and_clr() -> None:
    """Windows with pywebview + pythonnet (EdgeWebView2 backend) reports True."""
    with (
        patch("sys.platform", "win32"),
        patch("importlib.util.find_spec", side_effect=_fake_find_spec({"webview", "clr"})),
    ):
        assert ensure_gui_backend() is True


def test_ensure_gui_backend_win32_qt_alternative() -> None:
    """Windows with pywebview + Qt reports True."""
    with (
        patch("sys.platform", "win32"),
        patch("importlib.util.find_spec", side_effect=_fake_find_spec({"webview", "qtpy"})),
    ):
        assert ensure_gui_backend() is True


def test_ensure_gui_backend_win32_no_backend() -> None:
    """Windows with pywebview but neither clr nor Qt reports False."""
    with (
        patch("sys.platform", "win32"),
        patch("importlib.util.find_spec", side_effect=_fake_find_spec({"webview"})),
    ):
        assert ensure_gui_backend() is False


def test_ensure_gui_backend_win32_no_pywebview() -> None:
    """Windows without pywebview reports False even if clr is present."""
    with (
        patch("sys.platform", "win32"),
        patch("importlib.util.find_spec", side_effect=_fake_find_spec({"clr", "qtpy"})),
    ):
        assert ensure_gui_backend() is False


def test_ensure_gui_backend_darwin_cocoa() -> None:
    """macOS with pyobjc (Cocoa needs no gi) reports True."""
    with (
        patch("sys.platform", "darwin"),
        patch("importlib.util.find_spec", side_effect=_fake_find_spec({"objc"})),
    ):
        assert ensure_gui_backend() is True


def test_ensure_gui_backend_darwin_qt_alternative() -> None:
    with (
        patch("sys.platform", "darwin"),
        patch("importlib.util.find_spec", side_effect=_fake_find_spec({"qtpy"})),
    ):
        assert ensure_gui_backend() is True


def test_ensure_gui_backend_darwin_no_backend() -> None:
    with (
        patch("sys.platform", "darwin"),
        patch("importlib.util.find_spec", side_effect=_fake_find_spec(set())),
    ):
        assert ensure_gui_backend() is False


def test_ensure_gui_backend_removes_path_on_failed_import() -> None:
    """If adding a system path still doesn't make gi importable, the path is removed."""
    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "gi":
            raise ImportError("no gi")
        return original_import(name, *args, **kwargs)

    fake_path = "/usr/lib64/python3.12/site-packages"
    original_sys_path = sys.path.copy()

    with (
        patch("builtins.__import__", side_effect=fake_import),
        patch("wesktop.desktop.glob.glob", return_value=[fake_path]),
        patch("os.path.isdir", return_value=True),
    ):
        result = ensure_gui_backend()

    assert result is False
    assert fake_path not in sys.path
