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


def test_run_calls_ensure_gui_backend_before_webview() -> None:
    """run() calls ensure_gui_backend() before importing webview."""
    call_order: list[str] = []

    original_ensure = ensure_gui_backend

    def tracking_ensure():
        call_order.append("ensure_gui_backend")
        return True

    port = _free_port()

    with (
        patch("wesktop.desktop.ensure_gui_backend", side_effect=tracking_ensure),
        patch("wesktop.desktop._has_gui_backend", return_value=True),
        patch("webview.start"),
        patch("webview.create_window"),
        patch("wesktop.server.serve_background", return_value=f"http://127.0.0.1:{port}"),
    ):
        from wesktop.desktop import run

        run("myapp:app", host="127.0.0.1", port=port)

    assert "ensure_gui_backend" in call_order


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
