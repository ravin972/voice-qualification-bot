"""Structured logging configuration.

Wraps ``structlog`` so every log line is a structured event with consistent
context (call SID, scenario, state, latency). ``print`` is never used anywhere
in the codebase. This module is infrastructure and is fully implemented.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, cast

import structlog

from app.config.settings import Settings

BoundLogger = structlog.stdlib.BoundLogger


def configure_logging(settings: Settings) -> None:
    """Configure the global ``structlog`` + stdlib logging pipeline.

    Called exactly once during application startup (see ``app.main`` lifespan).
    Emits JSON in production for machine ingestion, or a colourised console
    renderer locally for developer ergonomics.

    Args:
        settings: Validated application settings controlling level and format.
    """
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=settings.log_level,
    )

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if settings.log_json
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str, **initial_context: Any) -> BoundLogger:
    """Return a bound logger, optionally pre-populated with static context.

    Args:
        name: Logger name, conventionally the module ``__name__``.
        **initial_context: Key/value pairs bound to every event from this logger.

    Returns:
        A ``structlog`` bound logger ready for structured event emission.
    """
    return cast(BoundLogger, structlog.get_logger(name).bind(**initial_context))
