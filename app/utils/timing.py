"""Latency instrumentation helpers.

The product target is sub-second turn latency. ``measure`` times a block of
async work and emits one structured log event through the project's existing
structlog-based logger (``app.services.logger``) — no new logging framework,
no new destination. ``ConversationService`` uses it to log per-turn STT/LLM/TTS
and total response latency, tagged with ``conversation_id``/``call_sid``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator, Awaitable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TypeVar

from app.services.logger import BoundLogger

T = TypeVar("T")

#: Structured log event name every `measure()` call emits.
LATENCY_EVENT = "conversation.latency"


@dataclass
class Measurement:
    """Handle yielded by :func:`measure`; ``latency_ms`` is set once the block exits."""

    latency_ms: float | None = None


@asynccontextmanager
async def measure(
    logger: BoundLogger, stage: str, **context: object
) -> AsyncGenerator[Measurement]:
    """Time an async block of work, log its duration, and expose it to the caller.

    Logs on exit whether the block succeeds or raises, so a slow failure is
    just as visible as a slow success.

    Args:
        logger: Bound structlog logger to emit the timing event on.
        stage: Label for the timed stage, e.g. ``'stt'``, ``'llm'``, ``'tts'``,
            ``'turn_total'``.
        **context: Extra fields attached to the log event (e.g.
            ``conversation_id``, ``call_sid``).

    Yields:
        A :class:`Measurement` whose ``latency_ms`` is populated after the
        block exits — read it once the ``async with`` statement has ended.
    """
    measurement = Measurement()
    start = time.perf_counter()
    try:
        yield measurement
    finally:
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        measurement.latency_ms = latency_ms
        logger.info(LATENCY_EVENT, stage=stage, latency_ms=latency_ms, **context)


async def with_deadline(awaitable: Awaitable[T], *, seconds: float) -> T:
    """Await ``awaitable`` but fail fast if it exceeds ``seconds``.

    Args:
        awaitable: The coroutine/future to bound.
        seconds: Maximum time to wait before timing out.

    Returns:
        The awaited result.

    Raises:
        TimeoutError: If ``awaitable`` does not complete within ``seconds``.
    """
    return await asyncio.wait_for(awaitable, timeout=seconds)
