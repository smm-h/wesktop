"""Verify wesktop.dev() forwards dev-proxy options to fastware's ViteDevProxy.

wesktop.dev is a bare re-export of fastware.dev.dev, which wraps the target
app in ViteDevProxy before serving. These tests prove that the
``backend_prefixes`` option -- used for same-origin dev mode where ``/api``
and ``/ws`` proxy to the backend and everything else hits the Vite origin --
reaches the proxy configuration verbatim. Vite spawning and the server are
mocked so nothing real starts.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import wesktop


def _run_dev(**kwargs) -> MagicMock:
    """Call wesktop.dev() with Vite + server mocked, return the ViteDevProxy.

    Patches the Vite subprocess and readiness probe so dev() proceeds
    straight to serve(), then intercepts serve() to capture the wrapped
    app (the ViteDevProxy instance) without actually serving.
    """
    app = MagicMock(name="asgi_app")
    captured: dict[str, object] = {}

    def fake_serve(wrapped, **_serve_kwargs):
        captured["wrapped"] = wrapped

    vite_proc = MagicMock()
    vite_proc.poll.return_value = None  # process stays alive

    with (
        patch("fastware.dev.subprocess.Popen", return_value=vite_proc),
        patch("fastware.dev.socket.create_connection", return_value=MagicMock()),
        patch("fastware.server.serve", side_effect=fake_serve),
    ):
        wesktop.dev(app, **kwargs)

    return captured["wrapped"]


def test_backend_prefixes_reach_vite_dev_proxy():
    """A custom backend_prefixes list is forwarded verbatim to ViteDevProxy."""
    from fastware.middleware import ViteDevProxy

    wrapped = _run_dev(backend_prefixes=["/api", "/ws"])

    assert isinstance(wrapped, ViteDevProxy)
    assert wrapped.backend_prefixes == ["/api", "/ws"]


def test_vite_port_reaches_vite_dev_proxy():
    """The vite_port passes through to the proxy alongside backend_prefixes."""
    wrapped = _run_dev(vite_port=4321, backend_prefixes=["/ws"])

    assert wrapped.vite_port == 4321
    assert wrapped.backend_prefixes == ["/ws"]


def test_backend_prefixes_default_includes_ws():
    """Omitting backend_prefixes leaves ViteDevProxy's default (/events, /ws)."""
    wrapped = _run_dev()

    assert wrapped.backend_prefixes == ["/events", "/ws"]
