"""Background task registry with feature-gated lifecycle.

Tasks implement the ``BackgroundTask`` protocol (``start()`` and ``stop()``
methods). Apps register zero-arg factories via ``TaskRegistry.register()``.
The registry instantiates and starts tasks during ``start_all()`` and stops
them during ``stop_all()``. Feature-gated tasks are skipped when their flag
is disabled.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable

    from wesktop.features import FeatureFlags

log = logging.getLogger(__name__)


@runtime_checkable
class BackgroundTask(Protocol):
    """Protocol for background tasks managed by the registry."""

    def start(self) -> None: ...
    def stop(self) -> None: ...


class TaskRegistry:
    """Registry for background tasks with optional feature gating.

    Tasks are registered as factories (callables returning ``BackgroundTask``
    instances). The registry instantiates and starts them during
    ``start_all()``, and stops them during ``stop_all()``.
    """

    def __init__(self) -> None:
        # Registered: name -> (factory, feature_gate)
        self._registered: dict[str, tuple[Callable[[], BackgroundTask], str | None]] = {}
        # Running: name -> instance (populated after start_all)
        self._running: dict[str, BackgroundTask] = {}

    def register(
        self,
        name: str,
        factory: Callable[[], BackgroundTask],
        *,
        feature: str | None = None,
    ) -> None:
        """Register a background task factory.

        If *feature* is set, the task only starts when that feature flag
        is enabled at ``start_all()`` time.

        Raises ``ValueError`` if a task with the same name is already
        registered.
        """
        if name in self._registered:
            msg = f"Background task {name!r} is already registered"
            raise ValueError(msg)
        self._registered[name] = (factory, feature)

    def start_all(self, features: FeatureFlags | None = None) -> None:
        """Instantiate and start all registered tasks, respecting feature gates."""
        for name, (factory, feature_gate) in self._registered.items():
            if name in self._running:
                continue
            if feature_gate is not None:
                if features is None or not features.enabled(feature_gate):
                    log.debug("Skipping task %r (feature %r disabled)", name, feature_gate)
                    continue
            try:
                instance = factory()
                instance.start()
                self._running[name] = instance
                log.info("Started background task %r", name)
            except Exception:
                log.exception("Failed to start background task %r", name)

    def stop_all(self) -> None:
        """Stop all running tasks."""
        for name in list(self._running):
            try:
                self._running[name].stop()
                log.info("Stopped background task %r", name)
            except Exception:
                log.exception("Failed to stop background task %r", name)
        self._running.clear()

    def list_tasks(self) -> list[dict[str, object]]:
        """List registered tasks with their running status."""
        result: list[dict[str, object]] = []
        for name, (_factory, feature_gate) in self._registered.items():
            result.append({
                "name": name,
                "feature": feature_gate,
                "running": name in self._running,
            })
        return result

    def get_task(self, name: str) -> BackgroundTask | None:
        """Return a running task instance by name, or ``None``."""
        return self._running.get(name)
