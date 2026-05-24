"""Boolean feature flags with optional per-machine overrides via JSON file.

Apps declare flags with defaults at startup. Overrides are loaded from
a JSON file whose path is provided by the app. API: enabled(name),
all_flags(), set_override(name, value), reload().
"""

from __future__ import annotations

import json
import threading
from pathlib import Path


class FeatureFlags:
    """Feature flag store with defaults and optional file-based overrides.

    Parameters
    ----------
    defaults:
        Mapping of flag name to default boolean value.
    overrides_path:
        Optional path to a JSON file containing per-machine overrides.
        If ``None`` or the file does not exist, all flags use defaults.
    """

    def __init__(
        self,
        defaults: dict[str, bool],
        overrides_path: str | Path | None = None,
    ) -> None:
        self._defaults = dict(defaults)
        self._overrides_path = Path(overrides_path) if overrides_path else None
        self._lock = threading.Lock()
        self._overrides: dict[str, bool] = self._load_overrides()

    def _load_overrides(self) -> dict[str, bool]:
        """Read overrides from disk, returning {} on missing/malformed file."""
        if self._overrides_path is None or not self._overrides_path.is_file():
            return {}
        try:
            data = json.loads(self._overrides_path.read_text())
            return {k: bool(v) for k, v in data.items()}
        except (json.JSONDecodeError, AttributeError, OSError):
            return {}

    def enabled(self, name: str) -> bool:
        """Check whether a feature flag is enabled."""
        with self._lock:
            if name in self._overrides:
                return self._overrides[name]
        return self._defaults.get(name, False)

    def all_flags(self) -> dict[str, bool]:
        """Return the effective state of every known flag."""
        with self._lock:
            return {
                name: self._overrides.get(name, default)
                for name, default in self._defaults.items()
            }

    def set_override(self, name: str, value: bool) -> None:
        """Set an override and persist to the JSON file.

        Raises ``RuntimeError`` if no overrides path was configured.
        """
        if self._overrides_path is None:
            msg = "Cannot set override: no overrides_path configured"
            raise RuntimeError(msg)
        with self._lock:
            self._overrides[name] = value
            self._overrides_path.parent.mkdir(parents=True, exist_ok=True)
            self._overrides_path.write_text(
                json.dumps(self._overrides, indent=2) + "\n"
            )

    def reload(self) -> None:
        """Re-read overrides from the file on disk."""
        with self._lock:
            self._overrides = self._load_overrides()
