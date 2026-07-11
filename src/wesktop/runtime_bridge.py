"""Host-side native bridge for reacting to fastware build changes.

The PRIMARY update path is page-side: native windows load the same page as the
browser, so the framework's ``/__fastware/client.js`` reloads the page (over the
SSE update channel) when the build id changes -- no host involvement, no polling.

This module is the host-side complement, used mainly for reset flows: it lets
the desktop host reload the window, clear the web cache, and -- where pywebview
exposes a window focus event -- poll ``/__fastware/version`` on focus to detect a
changed build id and reload.

Every function takes a duck-typed pywebview ``window`` object, so the module is
unit-testable with a fake window and imports no pywebview and no GUI.

Build ids have NO ordering: reload happens on a DIFFERENT id, never on a "newer"
one.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any, Callable

log = logging.getLogger(__name__)

__all__ = [
    "reload",
    "clear_web_cache",
    "fetch_build_id",
    "check_and_reload",
    "install_focus_poll",
]

# pywebview (as of the pinned version) exposes no cross-platform focus/activated
# event -- only lifecycle/geometry events (shown, minimized, restored, ...). We
# probe for a genuine focus event by these names so the hook lights up
# automatically if a future pywebview adds one; until then install_focus_poll is
# a documented no-op and the page-side client.js remains the update path.
_FOCUS_EVENT_CANDIDATES = ("focused", "focus", "activated")

# Clears the Cache Storage API from the page context. Used only when pywebview
# exposes no native cache-clearing API.
_CLEAR_CACHES_JS = (
    "(function(){if(window.caches){caches.keys()"
    ".then(function(ks){ks.forEach(function(k){caches.delete(k);});});}})();"
)


def reload(window: Any) -> None:
    """Reload the page in *window* by injecting ``location.reload()``."""
    window.evaluate_js("location.reload()")


def clear_web_cache(window: Any) -> bool:
    """Best-effort clear of *window*'s web cache.

    Uses pywebview's native ``clear_cache`` when the installed version exposes
    it (returns ``True``). Otherwise clears the Cache Storage API from the page
    via injected JS (returns ``False`` -- native API unavailable).
    """
    native = getattr(window, "clear_cache", None)
    if callable(native):
        native()
        return True
    window.evaluate_js(_CLEAR_CACHES_JS)
    return False


def fetch_build_id(version_url: str, *, timeout: float = 2.0) -> str | None:
    """GET the fastware version endpoint and return its ``build_id``.

    Returns ``None`` on any failure (network error, non-JSON body, or a missing/
    non-string ``build_id``) -- a probe failure must never crash the host.
    """
    try:
        with urllib.request.urlopen(version_url, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        build_id = payload.get("build_id")
        return build_id if isinstance(build_id, str) else None
    except Exception:
        log.debug("build id probe failed for %s", version_url, exc_info=True)
        return None


def check_and_reload(
    window: Any,
    version_url: str,
    last_build_id: str | None,
    *,
    clear_cache: bool = True,
    timeout: float = 2.0,
) -> str | None:
    """Probe *version_url*; reload *window* if the build id DIFFERS.

    Returns the observed build id: the new one on change, otherwise
    *last_build_id*; ``None`` is never returned on a successful probe. On a
    probe failure the function returns *last_build_id* unchanged and does not
    reload. The first observation (``last_build_id is None``) records the id
    without reloading.
    """
    current = fetch_build_id(version_url, timeout=timeout)
    if current is None:
        return last_build_id
    if last_build_id is not None and current != last_build_id:
        if clear_cache:
            clear_web_cache(window)
        reload(window)
    return current


def install_focus_poll(
    window: Any,
    version_url: str,
    *,
    on_change: Callable[[str], None] | None = None,
    initial_build_id: str | None = None,
    timeout: float = 2.0,
) -> bool:
    """Wire a version poll to *window*'s focus event, if one exists.

    On each focus the version endpoint is probed; on a DIFFERENT build id the
    window is reloaded and *on_change* is invoked with the new id.

    Returns ``True`` if a focus event was found and wired, ``False`` otherwise.
    A ``False`` result is the documented limitation on pywebview builds without a
    focus event -- the page-side ``client.js`` remains the update path there.
    """
    events = getattr(window, "events", None)
    if events is None:
        return False

    state: dict[str, str | None] = {"build_id": initial_build_id}

    def _handler(*_args: Any) -> None:
        new_id = check_and_reload(window, version_url, state["build_id"], timeout=timeout)
        if new_id is not None and new_id != state["build_id"]:
            state["build_id"] = new_id
            if on_change is not None:
                on_change(new_id)

    for name in _FOCUS_EVENT_CANDIDATES:
        event = getattr(events, name, None)
        if event is None:
            continue
        iadd = getattr(event, "__iadd__", None)
        if iadd is None:
            continue
        # Mirror `events.<name> += handler` (pywebview Event subscription).
        setattr(events, name, iadd(_handler))
        return True
    return False
