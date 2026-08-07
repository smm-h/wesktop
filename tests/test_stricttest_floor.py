"""Pin the stricttest test-isolation floor's adoption and stance.

Installing the plugin IS adoption, which makes the floor easy to lose by
accident: dropping the dev dependency, or relaxing an ini key, silently removes
protection from every other test in this suite without failing anything. These
tests make both failure modes loud.

The stance itself is a decision, not a default -- particularly
``stricttest_loopback = "allow"``, which is deliberately weaker than the rest of
the floor. It is justified below by a test that reproduces the exact shape the
suite needs.
"""

from __future__ import annotations

import os
import socket
import threading

import pytest
from stricttest import NetworkBlocked
from stricttest.envfloor import CREDENTIAL_VARS, session_env_dir
from stricttest.plugin import settings


def test_floor_is_installed():
    """HOME is repointed into the session's throwaway directory."""
    env_dir = session_env_dir()
    assert env_dir is not None, "stricttest env floor was never installed"
    assert os.environ["HOME"] == str(env_dir / "home")
    assert os.environ["USERPROFILE"] == str(env_dir / "home")
    assert os.environ["GIT_ALLOW_PROTOCOL"] == "file"


def test_ambient_credentials_are_stripped():
    """No credential vector survives into the test environment."""
    leaked = [var for var in CREDENTIAL_VARS if var in os.environ]
    assert leaked == [], f"credentials reachable from tests: {leaked}"


def test_declared_stance_is_pinned():
    """The five required keys hold exactly the stance this repo decided on.

    Changing any of these is a deliberate act; this test makes it one.
    """
    resolved = settings()
    assert resolved.sockets == "deny"
    assert resolved.socket_allowlist == ()
    assert resolved.unix_socket_allowlist == ()
    assert resolved.loopback == "allow"
    assert resolved.sandbox_required is False


def test_off_machine_egress_is_refused():
    """`stricttest_sockets = "deny"` still blocks everything off-machine.

    The refusal lands on name resolution, before any packet leaves.
    """
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("example.com", 443), timeout=1)


def test_ephemeral_loopback_bind_round_trips():
    """Why the loopback stance is "allow" rather than an exact allowlist.

    Several tests here (``test_mcp_tools``, ``test_desktop``) stand up a real
    server on ``("127.0.0.1", 0)`` and dial it back. The kernel assigns the port
    at bind time, so the ``host:port`` pair an allowlist would have to name does
    not exist until after the bind -- ``stricttest_socket_allowlist`` cannot
    express it at configuration time. ``loopback = "allow"`` is the only stance
    that permits this shape, and off-machine egress stays denied.
    """
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    accepted: list[socket.socket] = []

    def _accept():
        conn, _ = listener.accept()
        accepted.append(conn)

    thread = threading.Thread(target=_accept, daemon=True)
    thread.start()
    try:
        client = socket.create_connection(("127.0.0.1", port), timeout=5)
        thread.join(timeout=5)
        assert accepted, "the ephemeral loopback connection never landed"
        client.sendall(b"ping")
        assert accepted[0].recv(4) == b"ping"
        client.close()
        accepted[0].close()
    finally:
        listener.close()
