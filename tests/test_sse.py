"""Tests for the SSE broadcaster with typed event system."""

from __future__ import annotations

import asyncio
import json

import pytest

from webpane.sse import Broadcaster, sse_route


# ---------------------------------------------------------------------------
# Event registration
# ---------------------------------------------------------------------------


class TestRegisterEvent:
    def test_register_single_event(self):
        b = Broadcaster()
        b.register_event("update")
        assert "update" in b.event_types

    def test_register_multiple_events(self):
        b = Broadcaster()
        b.register_event("update")
        b.register_event("toast")
        assert b.event_types == frozenset({"update", "toast"})

    def test_register_idempotent(self):
        b = Broadcaster()
        b.register_event("update")
        b.register_event("update")
        assert b.event_types == frozenset({"update"})

    def test_event_types_is_frozen(self):
        """The property returns a frozenset -- callers cannot mutate it."""
        b = Broadcaster()
        b.register_event("update")
        with pytest.raises(AttributeError):
            b.event_types.add("sneaky")


# ---------------------------------------------------------------------------
# Strict mode validation
# ---------------------------------------------------------------------------


class TestBroadcastUnregisteredRaises:
    def test_raises_on_unregistered_event(self):
        b = Broadcaster()
        with pytest.raises(ValueError, match="unregistered event type"):
            b.broadcast("unknown", {"key": "val"})

    def test_raises_shows_registered_types(self):
        b = Broadcaster()
        b.register_event("allowed")
        with pytest.raises(ValueError, match="allowed"):
            b.broadcast("nope", {})

    def test_non_strict_skips_validation(self):
        b = Broadcaster(strict=False)
        # Should not raise even with no registered events
        b.broadcast("anything", {"key": "val"})


# ---------------------------------------------------------------------------
# Broadcasting delivers to clients
# ---------------------------------------------------------------------------


class TestBroadcastDeliversToClient:
    def test_single_client_receives_message(self):
        b = Broadcaster()
        b.register_event("ping")
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=256)
        b._clients.append(q)

        b.broadcast("ping", {"ts": 1})
        assert not q.empty()
        msg = q.get_nowait()
        assert msg.startswith("event: ping\n")
        assert '"ts": 1' in msg

    def test_multiple_clients_receive_message(self):
        b = Broadcaster()
        b.register_event("tick")
        queues = [asyncio.Queue(maxsize=256) for _ in range(3)]
        for q in queues:
            b._clients.append(q)

        b.broadcast("tick", {"n": 42})
        for q in queues:
            assert not q.empty()
            msg = q.get_nowait()
            assert "tick" in msg

    def test_string_data_sent_verbatim(self):
        b = Broadcaster()
        b.register_event("raw")
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=256)
        b._clients.append(q)

        b.broadcast("raw", "hello world")
        msg = q.get_nowait()
        assert "data: hello world\n" in msg


# ---------------------------------------------------------------------------
# Pruning full queues
# ---------------------------------------------------------------------------


class TestBroadcastPrunesFullQueue:
    def test_full_queue_is_pruned(self):
        b = Broadcaster(buffer_size=1)
        b.register_event("x")
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=1)
        b._clients.append(q)

        # Fill the queue
        b.broadcast("x", {})
        assert b.client_count == 1

        # Next broadcast overflows -- queue should be pruned
        b.broadcast("x", {})
        assert b.client_count == 0

    def test_healthy_client_survives_alongside_pruned(self):
        b = Broadcaster(buffer_size=1)
        b.register_event("x")
        full_q: asyncio.Queue[str] = asyncio.Queue(maxsize=1)
        healthy_q: asyncio.Queue[str] = asyncio.Queue(maxsize=256)
        b._clients.append(full_q)
        b._clients.append(healthy_q)

        # Fill the small queue
        b.broadcast("x", {"n": 1})
        assert b.client_count == 2

        # Overflow the small queue; healthy one stays
        b.broadcast("x", {"n": 2})
        assert b.client_count == 1
        assert healthy_q in b._clients
        assert full_q not in b._clients


# ---------------------------------------------------------------------------
# Client count
# ---------------------------------------------------------------------------


class TestClientCount:
    def test_initially_zero(self):
        b = Broadcaster()
        assert b.client_count == 0

    def test_tracks_appended_clients(self):
        b = Broadcaster()
        b._clients.append(asyncio.Queue(maxsize=256))
        assert b.client_count == 1
        b._clients.append(asyncio.Queue(maxsize=256))
        assert b.client_count == 2


# ---------------------------------------------------------------------------
# SSE wire format
# ---------------------------------------------------------------------------


class TestSSEWireFormat:
    def test_dict_data_is_json_serialized(self):
        b = Broadcaster(strict=False)
        msg = b._format_sse("update", {"key": "value"})
        assert msg == f'event: update\ndata: {json.dumps({"key": "value"})}\n\n'

    def test_string_data_sent_as_is(self):
        b = Broadcaster(strict=False)
        msg = b._format_sse("raw", "plain text")
        assert msg == "event: raw\ndata: plain text\n\n"

    def test_empty_dict(self):
        b = Broadcaster(strict=False)
        msg = b._format_sse("ping", {})
        assert msg == "event: ping\ndata: {}\n\n"

    def test_ends_with_double_newline(self):
        b = Broadcaster(strict=False)
        msg = b._format_sse("ev", {})
        assert msg.endswith("\n\n")

    def test_event_line_comes_first(self):
        b = Broadcaster(strict=False)
        msg = b._format_sse("ev", {"a": 1})
        lines = msg.split("\n")
        assert lines[0] == "event: ev"
        assert lines[1].startswith("data: ")


# ---------------------------------------------------------------------------
# Multiple broadcasters are independent
# ---------------------------------------------------------------------------


class TestMultipleBroadcastersIndependent:
    def test_separate_client_lists(self):
        a = Broadcaster()
        b = Broadcaster()
        a.register_event("x")
        b.register_event("y")

        qa: asyncio.Queue[str] = asyncio.Queue(maxsize=256)
        qb: asyncio.Queue[str] = asyncio.Queue(maxsize=256)
        a._clients.append(qa)
        b._clients.append(qb)

        a.broadcast("x", {"from": "a"})
        assert not qa.empty()
        assert qb.empty()

        b.broadcast("y", {"from": "b"})
        assert not qb.empty()

    def test_separate_event_registries(self):
        a = Broadcaster()
        b = Broadcaster()
        a.register_event("only_a")

        assert "only_a" in a.event_types
        assert "only_a" not in b.event_types

    def test_pruning_one_does_not_affect_other(self):
        a = Broadcaster(buffer_size=1)
        b = Broadcaster(buffer_size=1)
        a.register_event("x")
        b.register_event("x")

        qa: asyncio.Queue[str] = asyncio.Queue(maxsize=1)
        qb: asyncio.Queue[str] = asyncio.Queue(maxsize=1)
        a._clients.append(qa)
        b._clients.append(qb)

        # Fill and prune in a
        a.broadcast("x", {})
        a.broadcast("x", {})
        assert a.client_count == 0

        # b is unaffected
        assert b.client_count == 1


# ---------------------------------------------------------------------------
# sse_route convenience
# ---------------------------------------------------------------------------


class TestSSERoute:
    def test_returns_callable(self):
        b = Broadcaster()
        handler = sse_route(b)
        assert callable(handler)
