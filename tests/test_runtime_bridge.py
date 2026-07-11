"""Tests for the host-side native update bridge (Phase 12.3).

All functions take a duck-typed pywebview window, so these exercise them with a
fake window -- no GUI, no pywebview, no network (urlopen is monkeypatched).
"""

from __future__ import annotations

import io
import json

import pytest

from wesktop import runtime_bridge


class FakeEvent:
    def __init__(self) -> None:
        self.handlers: list = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self, *args) -> None:
        for h in list(self.handlers):
            h(*args)


class FakeEvents:
    def __init__(self, *, focus: bool = False) -> None:
        if focus:
            self.focused = FakeEvent()


class FakeWindow:
    def __init__(self, *, focus_event: bool = False, native_clear: bool = False,
                 events: bool = True) -> None:
        self.evaluated: list[str] = []
        self.cleared = 0
        self.events = FakeEvents(focus=focus_event) if events else None
        if native_clear:
            self.clear_cache = self._clear

    def evaluate_js(self, js: str):
        self.evaluated.append(js)
        return None

    def _clear(self) -> None:
        self.cleared += 1


# ---------------------------------------------------------------------------
# reload / clear_web_cache
# ---------------------------------------------------------------------------


def test_reload_injects_reload_js():
    w = FakeWindow()
    runtime_bridge.reload(w)
    assert any("location.reload()" in js for js in w.evaluated)


def test_clear_web_cache_uses_native_when_present():
    w = FakeWindow(native_clear=True)
    assert runtime_bridge.clear_web_cache(w) is True
    assert w.cleared == 1
    assert w.evaluated == []  # native path -- no JS injection


def test_clear_web_cache_falls_back_to_js():
    w = FakeWindow(native_clear=False)
    assert runtime_bridge.clear_web_cache(w) is False
    assert any("caches" in js for js in w.evaluated)


# ---------------------------------------------------------------------------
# fetch_build_id
# ---------------------------------------------------------------------------


def _fake_urlopen(payload: dict):
    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.close()
            return False

    def _open(url, timeout=None):
        return _Resp(json.dumps(payload).encode())

    return _open


def test_fetch_build_id_parses_payload(monkeypatch):
    monkeypatch.setattr(
        runtime_bridge.urllib.request, "urlopen",
        _fake_urlopen({"build_id": "abc123", "name": "x"}),
    )
    assert runtime_bridge.fetch_build_id("http://x/__fastware/version") == "abc123"


def test_fetch_build_id_returns_none_on_error(monkeypatch):
    def _boom(url, timeout=None):
        raise OSError("network down")

    monkeypatch.setattr(runtime_bridge.urllib.request, "urlopen", _boom)
    assert runtime_bridge.fetch_build_id("http://x/__fastware/version") is None


def test_fetch_build_id_returns_none_on_missing_field(monkeypatch):
    monkeypatch.setattr(
        runtime_bridge.urllib.request, "urlopen", _fake_urlopen({"name": "x"})
    )
    assert runtime_bridge.fetch_build_id("http://x/__fastware/version") is None


# ---------------------------------------------------------------------------
# check_and_reload
# ---------------------------------------------------------------------------


def test_check_and_reload_reloads_on_different(monkeypatch):
    monkeypatch.setattr(runtime_bridge, "fetch_build_id", lambda *a, **k: "new")
    w = FakeWindow()
    result = runtime_bridge.check_and_reload(w, "http://x/v", "old")
    assert result == "new"
    assert any("location.reload()" in js for js in w.evaluated)


def test_check_and_reload_no_reload_on_same(monkeypatch):
    monkeypatch.setattr(runtime_bridge, "fetch_build_id", lambda *a, **k: "same")
    w = FakeWindow()
    result = runtime_bridge.check_and_reload(w, "http://x/v", "same")
    assert result == "same"
    assert not any("location.reload()" in js for js in w.evaluated)


def test_check_and_reload_first_observation_does_not_reload(monkeypatch):
    monkeypatch.setattr(runtime_bridge, "fetch_build_id", lambda *a, **k: "first")
    w = FakeWindow()
    result = runtime_bridge.check_and_reload(w, "http://x/v", None)
    assert result == "first"
    assert not any("location.reload()" in js for js in w.evaluated)


def test_check_and_reload_probe_failure_keeps_last(monkeypatch):
    monkeypatch.setattr(runtime_bridge, "fetch_build_id", lambda *a, **k: None)
    w = FakeWindow()
    result = runtime_bridge.check_and_reload(w, "http://x/v", "old")
    assert result == "old"
    assert w.evaluated == []


# ---------------------------------------------------------------------------
# install_focus_poll
# ---------------------------------------------------------------------------


def test_install_focus_poll_wires_focus_event(monkeypatch):
    monkeypatch.setattr(runtime_bridge, "fetch_build_id", lambda *a, **k: "v2")
    w = FakeWindow(focus_event=True)
    seen: list[str] = []
    ok = runtime_bridge.install_focus_poll(
        w, "http://x/v", on_change=seen.append, initial_build_id="v1"
    )
    assert ok is True
    # Fire the focus event -> build id differs -> reload + on_change.
    w.events.focused.fire()
    assert seen == ["v2"]
    assert any("location.reload()" in js for js in w.evaluated)


def test_install_focus_poll_returns_false_without_focus_event():
    w = FakeWindow(focus_event=False)
    assert runtime_bridge.install_focus_poll(w, "http://x/v") is False


def test_install_focus_poll_returns_false_when_no_events():
    w = FakeWindow(events=False)
    assert runtime_bridge.install_focus_poll(w, "http://x/v") is False
