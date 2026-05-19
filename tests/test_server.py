from __future__ import annotations

import socket
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wesktop.server import (
    _make_server,
    check_already_running,
    ensure_port_available,
    start_server_in_background,
)


def test_check_already_running_no_pid(tmp_path: Path) -> None:
    """No PID file -- returns normally without error."""
    pid_path = tmp_path / "test.pid"
    check_already_running(pid_path)  # should not raise or exit


def test_check_already_running_stale_pid(tmp_path: Path) -> None:
    """PID file exists but the process is dead -- stale file is removed."""
    pid_path = tmp_path / "test.pid"
    pid_path.write_text("999999999")  # almost certainly not running
    check_already_running(pid_path)
    assert not pid_path.exists(), "Stale PID file should be cleaned up"


def test_check_already_running_corrupt_pid(tmp_path: Path) -> None:
    """PID file has non-numeric content -- treated as stale."""
    pid_path = tmp_path / "test.pid"
    pid_path.write_text("not-a-number")
    check_already_running(pid_path)
    assert not pid_path.exists()


def test_ensure_port_available_free() -> None:
    """A free port should be returned as-is."""
    # Bind to port 0 to find a free port, then release it
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]
    result = ensure_port_available("127.0.0.1", free_port)
    assert result == free_port


def test_ensure_port_available_occupied() -> None:
    """An occupied port causes sys.exit(1)."""
    # Hold the port open for the duration of the test
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        occupied_port = s.getsockname()[1]
        with pytest.raises(SystemExit) as exc_info:
            ensure_port_available("127.0.0.1", occupied_port)
        assert exc_info.value.code == 1


@patch("wesktop.server.Granian")
def test_make_server_creates_granian(mock_granian_cls: MagicMock) -> None:
    """Verify Granian is instantiated with the correct parameters."""
    _make_server("myapp:app", "0.0.0.0", 9000)
    mock_granian_cls.assert_called_once_with(
        target="myapp:app",
        address="0.0.0.0",
        port=9000,
        interface="asgi",
    )


@patch("wesktop.server.Granian")
def test_start_server_in_background_returns_url(mock_granian_cls: MagicMock) -> None:
    """Background start returns the correct URL and launches a daemon thread."""
    mock_instance = MagicMock()
    mock_granian_cls.return_value = mock_instance

    # Use a free port so ensure_port_available passes
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]

    url = start_server_in_background("myapp:app", "127.0.0.1", free_port)
    assert url == f"http://127.0.0.1:{free_port}"
    mock_instance.serve.assert_called_once()
