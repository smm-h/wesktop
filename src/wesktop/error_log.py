"""SQLite-backed error log for 5xx responses.

Provides a simple append-only store that the request timing middleware
can write to on server errors.  Each entry captures enough context for
dashboard display and post-mortem investigation.

Usage::

    from wesktop.error_log import ErrorLog

    error_log = ErrorLog("errors.db")
    error_log.append(
        method="POST",
        path="/api/deploy",
        status_code=500,
        detail="Docker timeout",
        request_id="abc-123",
    )
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path


_CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS errors (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp  REAL    NOT NULL,
    method     TEXT    NOT NULL,
    path       TEXT    NOT NULL,
    status_code INTEGER NOT NULL,
    detail     TEXT    NOT NULL DEFAULT '',
    request_id TEXT    NOT NULL DEFAULT '',
    user       TEXT    NOT NULL DEFAULT '',
    traceback  TEXT    NOT NULL DEFAULT ''
)
"""


class ErrorLog:
    """Append-only SQLite error log.

    Thread-safe: uses a lock around writes so concurrent ASGI tasks
    do not conflict.

    Args:
        path: Filesystem path for the SQLite database.  Created on
              first write if it does not exist.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._lock = threading.Lock()
        self._table_created = False

    def _ensure_table(self, conn: sqlite3.Connection) -> None:
        if not self._table_created:
            conn.execute(_CREATE_TABLE)
            conn.commit()
            self._table_created = True

    def append(
        self,
        *,
        method: str,
        path: str,
        status_code: int,
        detail: str = "",
        request_id: str = "",
        user: str = "",
        traceback: str = "",
    ) -> None:
        """Append an error entry to the log."""
        with self._lock:
            conn = sqlite3.connect(self._path)
            try:
                self._ensure_table(conn)
                conn.execute(
                    "INSERT INTO errors "
                    "(timestamp, method, path, status_code, detail, request_id, user, traceback) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (time.time(), method, path, status_code, detail, request_id, user, traceback),
                )
                conn.commit()
            finally:
                conn.close()

    def recent(self, limit: int = 50) -> list[dict]:
        """Return the most recent *limit* error entries, newest first."""
        conn = sqlite3.connect(self._path)
        try:
            self._ensure_table(conn)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM errors ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
