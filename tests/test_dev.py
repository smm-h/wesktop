from __future__ import annotations

import socket
import subprocess
from unittest.mock import MagicMock, call, patch

import pytest


def _fake_app(scope, receive, send):
    """Dummy ASGI app for testing."""
    pass


class TestDevSpawnsVite:
    """dev() spawns a subprocess with the vite_command."""

    @patch("wesktop.server.serve")
    @patch("socket.create_connection")
    @patch("subprocess.Popen")
    def test_spawns_vite_subprocess(
        self,
        mock_popen: MagicMock,
        mock_connect: MagicMock,
        mock_serve: MagicMock,
    ) -> None:
        proc = MagicMock()
        proc.poll.return_value = None
        mock_popen.return_value = proc

        # create_connection succeeds immediately (Vite is "ready")
        mock_sock = MagicMock()
        mock_connect.return_value = mock_sock

        from wesktop.dev import dev

        dev(_fake_app, host="127.0.0.1", port=8000)

        mock_popen.assert_called_once_with(
            "npm run dev",
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

    @patch("wesktop.server.serve")
    @patch("socket.create_connection")
    @patch("subprocess.Popen")
    def test_custom_vite_command(
        self,
        mock_popen: MagicMock,
        mock_connect: MagicMock,
        mock_serve: MagicMock,
    ) -> None:
        proc = MagicMock()
        proc.poll.return_value = None
        mock_popen.return_value = proc
        mock_connect.return_value = MagicMock()

        from wesktop.dev import dev

        dev(_fake_app, vite_command="pnpm dev", host="127.0.0.1", port=8000)

        mock_popen.assert_called_once_with(
            "pnpm dev",
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )


class TestDevWrapsWithViteDevProxy:
    """dev() wraps the app with ViteDevProxy before passing to serve()."""

    @patch("wesktop.server.serve")
    @patch("socket.create_connection")
    @patch("subprocess.Popen")
    def test_wraps_app_with_proxy(
        self,
        mock_popen: MagicMock,
        mock_connect: MagicMock,
        mock_serve: MagicMock,
    ) -> None:
        proc = MagicMock()
        proc.poll.return_value = None
        mock_popen.return_value = proc
        mock_connect.return_value = MagicMock()

        from wesktop.dev import dev
        from wesktop.middleware import ViteDevProxy

        dev(_fake_app, vite_port=3000, host="127.0.0.1", port=8000)

        # serve() was called with a ViteDevProxy wrapping the original app
        args, kwargs = mock_serve.call_args
        wrapped = args[0]
        assert isinstance(wrapped, ViteDevProxy)
        assert wrapped.app is _fake_app
        assert wrapped.vite_port == 3000


class TestDevCallsServe:
    """dev() calls serve() with the wrapped app and foreground=True."""

    @patch("wesktop.server.serve")
    @patch("socket.create_connection")
    @patch("subprocess.Popen")
    def test_calls_serve_foreground(
        self,
        mock_popen: MagicMock,
        mock_connect: MagicMock,
        mock_serve: MagicMock,
    ) -> None:
        proc = MagicMock()
        proc.poll.return_value = None
        mock_popen.return_value = proc
        mock_connect.return_value = MagicMock()

        from wesktop.dev import dev

        dev(_fake_app, host="127.0.0.1", port=9000, name="MYAPP")

        mock_serve.assert_called_once()
        _, kwargs = mock_serve.call_args
        assert kwargs["foreground"] is True
        assert kwargs["host"] == "127.0.0.1"
        assert kwargs["port"] == 9000
        assert kwargs["name"] == "MYAPP"
        assert kwargs["pid_path"] is None
        assert kwargs["pre_serve"] is None


class TestDevTerminatesVite:
    """dev() terminates the Vite process on shutdown."""

    @patch("wesktop.server.serve")
    @patch("socket.create_connection")
    @patch("subprocess.Popen")
    def test_terminates_vite_on_normal_exit(
        self,
        mock_popen: MagicMock,
        mock_connect: MagicMock,
        mock_serve: MagicMock,
    ) -> None:
        proc = MagicMock()
        proc.poll.return_value = None
        mock_popen.return_value = proc
        mock_connect.return_value = MagicMock()

        from wesktop.dev import dev

        dev(_fake_app, host="127.0.0.1", port=8000)

        proc.terminate.assert_called_once()
        proc.wait.assert_called_once_with(timeout=5)

    @patch("wesktop.server.serve", side_effect=KeyboardInterrupt)
    @patch("socket.create_connection")
    @patch("subprocess.Popen")
    def test_terminates_vite_on_exception(
        self,
        mock_popen: MagicMock,
        mock_connect: MagicMock,
        mock_serve: MagicMock,
    ) -> None:
        proc = MagicMock()
        proc.poll.return_value = None
        mock_popen.return_value = proc
        mock_connect.return_value = MagicMock()

        from wesktop.dev import dev

        with pytest.raises(KeyboardInterrupt):
            dev(_fake_app, host="127.0.0.1", port=8000)

        proc.terminate.assert_called_once()

    @patch("wesktop.server.serve")
    @patch("socket.create_connection")
    @patch("subprocess.Popen")
    def test_kills_vite_if_terminate_times_out(
        self,
        mock_popen: MagicMock,
        mock_connect: MagicMock,
        mock_serve: MagicMock,
    ) -> None:
        proc = MagicMock()
        proc.poll.return_value = None
        proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="npm", timeout=5), None]
        mock_popen.return_value = proc
        mock_connect.return_value = MagicMock()

        from wesktop.dev import dev

        dev(_fake_app, host="127.0.0.1", port=8000)

        proc.terminate.assert_called_once()
        proc.kill.assert_called_once()
        # wait called twice: once with timeout (raises), once after kill
        assert proc.wait.call_count == 2


class TestDevViteFailsToStart:
    """dev() raises RuntimeError if Vite fails to start."""

    @patch("socket.create_connection", side_effect=ConnectionRefusedError)
    @patch("subprocess.Popen")
    def test_raises_if_vite_exits_immediately(
        self,
        mock_popen: MagicMock,
        mock_connect: MagicMock,
    ) -> None:
        proc = MagicMock()
        proc.poll.return_value = 1  # process exited
        proc.returncode = 1
        proc.stderr = MagicMock()
        proc.stderr.read.return_value = b"vite: command not found"
        mock_popen.return_value = proc

        from wesktop.dev import dev

        with pytest.raises(RuntimeError, match="Vite process exited with code 1"):
            dev(_fake_app, host="127.0.0.1", port=8000)

    @patch("time.monotonic")
    @patch("time.sleep")
    @patch("socket.create_connection", side_effect=ConnectionRefusedError)
    @patch("subprocess.Popen")
    def test_raises_if_vite_never_ready(
        self,
        mock_popen: MagicMock,
        mock_connect: MagicMock,
        mock_sleep: MagicMock,
        mock_monotonic: MagicMock,
    ) -> None:
        proc = MagicMock()
        proc.poll.return_value = None  # process still running but never ready
        mock_popen.return_value = proc

        # Simulate time passing beyond the 15s deadline
        mock_monotonic.side_effect = [0.0, 0.0, 16.0]

        from wesktop.dev import dev

        with pytest.raises(RuntimeError, match="did not start within 15s"):
            dev(_fake_app, host="127.0.0.1", port=8000)

        proc.terminate.assert_called_once()


class TestDevStringTarget:
    """dev() resolves string targets via importlib."""

    @patch("wesktop.server.serve")
    @patch("socket.create_connection")
    @patch("subprocess.Popen")
    def test_resolves_string_target(
        self,
        mock_popen: MagicMock,
        mock_connect: MagicMock,
        mock_serve: MagicMock,
    ) -> None:
        proc = MagicMock()
        proc.poll.return_value = None
        mock_popen.return_value = proc
        mock_connect.return_value = MagicMock()

        from wesktop.dev import dev
        from wesktop.middleware import ViteDevProxy

        # Use a real importable module:attribute
        dev("wesktop.asgi:create_app", host="127.0.0.1", port=8000)

        args, kwargs = mock_serve.call_args
        wrapped = args[0]
        assert isinstance(wrapped, ViteDevProxy)
        # The resolved app should be the actual create_app function
        from wesktop.asgi import create_app
        assert wrapped.app is create_app
