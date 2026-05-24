"""Structured logging configuration using structlog.

Provides JSON-formatted log output in production (non-tty) and colored console
output in development (tty).  Call ``configure_logging()`` once at startup.

Usage::

    from wesktop.logging import configure_logging, get_logger

    configure_logging()
    logger = get_logger(component="auth")
    logger.info("login attempt", username="alice")
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from structlog.typing import FilteringBoundLogger


def configure_logging(*, json_output: bool | None = None) -> None:
    """Configure structlog processors and stdlib integration.

    Call once at server startup (e.g. in a lifespan handler).

    Args:
        json_output: If True, emit JSON lines.  If False, use colored
                     console output.  If None (default), auto-detect
                     based on whether stderr is a TTY.
    """
    if json_output is None:
        json_output = not sys.stderr.isatty()

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.CallsiteParameterAdder(
            [
                structlog.processors.CallsiteParameter.MODULE,
                structlog.processors.CallsiteParameter.FUNC_NAME,
                structlog.processors.CallsiteParameter.LINENO,
            ],
        ),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer: structlog.types.Processor
    if json_output:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.UnicodeDecoder(),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(component: str | None = None, **initial_binds: object) -> FilteringBoundLogger:
    """Return a bound structlog logger, optionally with a component name.

    Example::

        logger = get_logger("auth")
        logger.info("login attempt", username="alice")
    """
    if component is not None:
        initial_binds["component"] = component
    return structlog.get_logger(**initial_binds)  # type: ignore[no-any-return]


def init_sentry(dsn: str, **kwargs: object) -> None:
    """Initialize Sentry SDK for error tracking (optional dependency).

    If ``sentry-sdk`` is not installed, this is a no-op.  When available,
    it initializes with ASGI-compatible settings and a ``before_send``
    filter that drops 4xx ``HTTPError`` events (they are expected client
    errors, not actionable server issues).

    Args:
        dsn: Sentry DSN string.
        **kwargs: Additional arguments forwarded to ``sentry_sdk.init()``.
    """
    try:
        import sentry_sdk  # type: ignore[import-untyped]
    except ImportError:
        return

    def _before_send(event: dict, hint: dict) -> dict | None:
        exc_info = hint.get("exc_info")
        if exc_info:
            _, exc_value, _ = exc_info
            # Import lazily to avoid circular import at module level.
            from wesktop.asgi import HTTPError

            if isinstance(exc_value, HTTPError) and 400 <= exc_value.status_code < 500:
                return None
        return event

    sentry_sdk.init(
        dsn=dsn,
        before_send=_before_send,
        **kwargs,
    )
