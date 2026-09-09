#!/usr/bin/env python3
"""Open a real window and check that the zoom lock actually holds the page at 1:1.

The unit tests drive the lock's handlers against a fake web view. This drives
the real one: it opens a window, rescales the live WebKit view the way a pinch
would, reads the level back, and reports.

Needs a display and a GTK backend, so it is a manual probe rather than part of
the suite:

    python scripts/probe_zoom_lock.py

The file is importable on purpose -- the server runs in a subprocess that
re-imports the target, and a ``__main__`` module cannot be re-imported. Running
it puts its own directory on PYTHONPATH so the child finds it by name.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import wesktop

router = wesktop.Router()


@router.get("/")
async def index(req: wesktop.Request):
    return wesktop.HTMLResponse(
        "<!doctype html><meta charset=utf-8>"
        "<body style='font:16px sans-serif;padding:2rem'>"
        "<h1>zoom lock probe</h1><p>This window closes itself.</p>"
    )


app = wesktop.create_app(router)

RESULT: dict[str, object] = {}


def _probe() -> None:
    """Rescale the live view, read it back, then close the window."""
    from wesktop.desktop import _gtk_web_view

    deadline = time.monotonic() + 20
    view = None
    window = None
    while time.monotonic() < deadline:
        window = wesktop.active_window()
        if window is not None:
            view = _gtk_web_view(window)
            if view is not None:
                break
        time.sleep(0.1)
    if view is None:
        RESULT["error"] = "no GTK web view appeared within 20s"
        if window is not None:
            window.destroy()
        return

    time.sleep(2.0)  # let the page load, so the lock is installed
    RESULT["before"] = view.get_zoom_level()
    view.set_zoom_level(2.5)
    time.sleep(0.5)
    RESULT["after_rescale"] = view.get_zoom_level()
    window.destroy()


def main() -> int:
    os.environ["PYTHONPATH"] = os.pathsep.join(
        [str(Path(__file__).resolve().parent), os.environ.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)

    threading.Thread(target=_probe, name="probe", daemon=True).start()
    wesktop.run(
        "probe_zoom_lock:app",
        title="wesktop zoom lock probe",
        width=420,
        height=240,
        single_instance=False,
    )

    if "error" in RESULT:
        print(f"FAILED: {RESULT['error']}", file=sys.stderr)
        return 1
    before = RESULT.get("before")
    after = RESULT.get("after_rescale")
    print(f"zoom level on load: {before}")
    print(f"zoom level after a 2.5x rescale: {after}")
    if before == 1.0 and after == 1.0:
        print("PASS: the lock held the page at 1:1")
        return 0
    print("FAILED: the page did not stay at 1:1", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
