"""Append-only JSONL audit log writer.

Each entry is a single JSON line with an ISO timestamp, event type, and
optional payload dict. Thread-safe via ``threading.Lock``.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path


class AuditLog:
    """Append-only JSONL audit log.

    Parameters
    ----------
    path:
        Path to the JSONL file. Created on first write if it does not exist.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    def log(self, event_type: str, payload: dict | None = None) -> None:
        """Append a single audit entry as a JSON line.

        Each line has the shape::

            {"timestamp": "...", "event_type": "...", "payload": {...}}
        """
        entry: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
        }
        if payload is not None:
            entry["payload"] = payload
        line = json.dumps(entry, separators=(",", ":"))
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a") as f:
                f.write(line + "\n")
