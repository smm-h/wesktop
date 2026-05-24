"""Dependency injection: per-request resolution with caching and cleanup.

Supports sync/async factory callables and sync/async generator factories
(yield pattern). Generator factories get cleanup after the handler returns.
Results are cached per-request: the same factory called twice returns the
same resolved instance.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable


class DependencyResolver:
    """Resolves a dict of ``{name: factory}`` into ``{name: value}`` per request.

    *overrides* maps an original factory to a replacement factory. When an
    override exists for a factory, the replacement is called instead.
    """

    def __init__(self, overrides: dict[Callable, Callable] | None = None):
        self._overrides = overrides or {}

    async def resolve(
        self,
        deps: dict[str, Callable],
        request: Any,
    ) -> tuple[dict[str, Any], list[tuple[str, Any]]]:
        """Resolve *deps* against *request*.

        Returns ``(resolved, cleanups)`` where *resolved* is a
        ``{name: value}`` dict and *cleanups* is a list of
        ``("sync" | "async", generator)`` pairs to pass to :meth:`cleanup`.
        """
        resolved: dict[str, Any] = {}
        cleanups: list[tuple[str, Any]] = []
        cache: dict[int, Any] = {}  # id(actual_factory) -> resolved value

        for name, factory in deps.items():
            actual_factory = self._overrides.get(factory, factory)
            factory_id = id(actual_factory)

            if factory_id in cache:
                resolved[name] = cache[factory_id]
                continue

            result = actual_factory(request)

            # Handle awaitable (async def factory)
            if inspect.isawaitable(result):
                result = await result

            # Handle generators (sync and async)
            if inspect.isgenerator(result):
                value = next(result)
                cleanups.append(("sync", result))
            elif inspect.isasyncgen(result):
                value = await result.__anext__()
                cleanups.append(("async", result))
            else:
                value = result

            cache[factory_id] = value
            resolved[name] = value

        return resolved, cleanups

    @staticmethod
    async def cleanup(cleanups: list[tuple[str, Any]]) -> None:
        """Run generator cleanups in reverse order.

        Cleanup errors are suppressed -- a failing cleanup must not mask the
        handler's response or exception.
        """
        for kind, gen in reversed(cleanups):
            try:
                if kind == "sync":
                    try:
                        next(gen)
                    except StopIteration:
                        pass
                else:
                    try:
                        await gen.__anext__()
                    except StopAsyncIteration:
                        pass
            except Exception:
                pass  # swallow cleanup errors
