from __future__ import annotations

import socket
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wesktop.server import (
    _make_server,
    check_already_running,
    ensure_port_available,
    serve,
)


def test_check_already_running_no_pid(tmp_path: Path) -> None:
    """No PID file -- returns None."""
    pid_path = tmp_path / "test.pid"
    assert check_already_running(pid_path) is None


def test_check_already_running_stale_pid(tmp_path: Path) -> None:
    """PID file exists but the process is dead -- returns None and cleans up."""
    pid_path = tmp_path / "test.pid"
    pid_path.write_text("999999999")  # almost certainly not running
    assert check_already_running(pid_path) is None
    assert not pid_path.exists(), "Stale PID file should be cleaned up"


def test_check_already_running_corrupt_pid(tmp_path: Path) -> None:
    """PID file has non-numeric content -- returns None and cleans up."""
    pid_path = tmp_path / "test.pid"
    pid_path.write_text("not-a-number")
    assert check_already_running(pid_path) is None
    assert not pid_path.exists()


def test_check_already_running_live_process(tmp_path: Path) -> None:
    """PID file points to a running process -- returns the PID."""
    import os
    pid_path = tmp_path / "test.pid"
    pid_path.write_text(str(os.getpid()))  # current process is alive
    result = check_already_running(pid_path)
    assert result == os.getpid()
    assert pid_path.exists(), "PID file should NOT be removed for a live process"


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
def test_serve_background_returns_url(mock_granian_cls: MagicMock) -> None:
    """Background serve returns the correct URL and launches a daemon thread."""
    mock_instance = MagicMock()
    mock_granian_cls.return_value = mock_instance

    # Use a free port so ensure_port_available passes
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]

    url = serve("myapp:app", foreground=False, host="127.0.0.1", port=free_port)
    assert url == f"http://127.0.0.1:{free_port}"
    mock_instance.serve.assert_called_once()


def test_serve_single_instance_true_exits_on_conflict(tmp_path: Path) -> None:
    """serve() with single_instance=True exits when an instance is already running."""
    import os
    pid_path = tmp_path / "test.pid"
    pid_path.write_text(str(os.getpid()))  # current process is alive

    with pytest.raises(SystemExit) as exc_info:
        serve(
            "myapp:app",
            foreground=False,
            host="127.0.0.1",
            port=9999,
            pid_path=pid_path,
            single_instance=True,
        )
    assert exc_info.value.code == 1


@patch("wesktop.server.Granian")
def test_serve_single_instance_false_skips_pid_check(
    mock_granian_cls: MagicMock,
    tmp_path: Path,
) -> None:
    """serve() with single_instance=False does not check for existing instances."""
    import os
    mock_instance = MagicMock()
    mock_granian_cls.return_value = mock_instance

    pid_path = tmp_path / "test.pid"
    pid_path.write_text(str(os.getpid()))  # current process is alive

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]

    # Should NOT exit despite existing PID
    url = serve(
        "myapp:app",
        foreground=False,
        host="127.0.0.1",
        port=free_port,
        pid_path=pid_path,
        single_instance=False,
    )
    assert url == f"http://127.0.0.1:{free_port}"
    mock_instance.serve.assert_called_once()
