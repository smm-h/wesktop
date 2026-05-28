from __future__ import annotations

import http.server
import socket
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wesktop.server import (
    _find_free_port,
    _kill_port_holder,
    _make_server,
    _port_file_path,
    check_already_running,
    ensure_port_available,
    read_port_file,
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


def test_ensure_port_available_occupied_unknown_process() -> None:
    """An occupied port with no health endpoint causes sys.exit(1)."""
    # Hold the port open for the duration of the test
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        occupied_port = s.getsockname()[1]
        with pytest.raises(SystemExit) as exc_info:
            ensure_port_available("127.0.0.1", occupied_port)
        assert exc_info.value.code == 1


def test_ensure_port_available_kills_stale_server() -> None:
    """When a stale server responds to /health with 'ok', kill it and reclaim the port."""

    class _HealthHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/health":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *args: object) -> None:
            pass  # suppress stderr output during tests

    # Start a temporary HTTP server on a random port to simulate a stale instance.
    httpd = http.server.HTTPServer(("127.0.0.1", 0), _HealthHandler)
    port = httpd.server_address[1]
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    # Mock _kill_port_holder to shut down our test server instead of using lsof/kill.
    def _fake_kill(host: str, p: int) -> None:
        httpd.shutdown()
        httpd.server_close()

    with patch("wesktop.server._kill_port_holder", side_effect=_fake_kill):
        result = ensure_port_available("127.0.0.1", port, name="test")

    assert result == port


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


# --- Port file tests ---


def test_find_free_port_returns_nonzero() -> None:
    """_find_free_port returns a valid port number."""
    port = _find_free_port("127.0.0.1")
    assert 1 <= port <= 65535


def test_port_file_path_derives_from_pid_path(tmp_path: Path) -> None:
    """Port file path replaces .pid suffix with .port."""
    pid_path = tmp_path / "app.pid"
    assert _port_file_path(pid_path) == tmp_path / "app.port"


def test_read_port_file_returns_port(tmp_path: Path) -> None:
    """read_port_file reads the port from a companion .port file."""
    pid_path = tmp_path / "app.pid"
    port_path = pid_path.with_suffix(".port")
    port_path.write_text("9876")
    assert read_port_file(pid_path) == 9876


def test_read_port_file_returns_none_when_missing(tmp_path: Path) -> None:
    """read_port_file returns None when no port file exists."""
    pid_path = tmp_path / "app.pid"
    assert read_port_file(pid_path) is None


def test_read_port_file_returns_none_on_corrupt(tmp_path: Path) -> None:
    """read_port_file returns None when port file is not a valid integer."""
    pid_path = tmp_path / "app.pid"
    port_path = pid_path.with_suffix(".port")
    port_path.write_text("not-a-number")
    assert read_port_file(pid_path) is None


@patch("wesktop.server.Granian")
def test_serve_port_zero_picks_random_port(mock_granian_cls: MagicMock) -> None:
    """serve() with port=0 assigns a random free port."""
    mock_instance = MagicMock()
    mock_granian_cls.return_value = mock_instance

    url = serve("myapp:app", foreground=False, host="127.0.0.1", port=0)
    assert url is not None
    assert url.startswith("http://127.0.0.1:")
    # Port should not be 0 in the URL
    actual_port = int(url.rsplit(":", 1)[1])
    assert actual_port > 0


@patch("wesktop.server.Granian")
def test_serve_writes_port_file(mock_granian_cls: MagicMock, tmp_path: Path) -> None:
    """serve() writes a port file alongside the PID file."""
    mock_instance = MagicMock()
    mock_granian_cls.return_value = mock_instance

    pid_path = tmp_path / "test.pid"

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]

    serve(
        "myapp:app",
        foreground=False,
        host="127.0.0.1",
        port=free_port,
        pid_path=pid_path,
    )

    port_path = pid_path.with_suffix(".port")
    assert port_path.exists()
    assert int(port_path.read_text().strip()) == free_port
