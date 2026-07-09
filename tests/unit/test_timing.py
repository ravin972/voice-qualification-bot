"""Latency instrumentation tests.

Verifies ``measure()`` emits exactly the structured event ``ConversationService``
relies on (event name, stage, latency_ms, arbitrary context) via structlog's own
``capture_logs`` test helper — no new logging framework, just asserting on the
existing one's output. Also covers ``with_deadline``'s timeout behaviour.
"""

from __future__ import annotations

import asyncio

import pytest
from app.services.logger import get_logger
from app.utils.timing import LATENCY_EVENT, measure, with_deadline
from structlog.testing import capture_logs


async def test_measure_logs_stage_latency_and_context() -> None:
    logger = get_logger("test.timing")
    with capture_logs() as logs:
        async with measure(logger, "stt", conversation_id="CA1", call_sid="CA1"):
            await asyncio.sleep(0.01)

    assert len(logs) == 1
    entry = logs[0]
    assert entry["event"] == LATENCY_EVENT
    assert entry["stage"] == "stt"
    assert entry["conversation_id"] == "CA1"
    assert entry["call_sid"] == "CA1"
    assert isinstance(entry["latency_ms"], float)
    assert entry["latency_ms"] >= 10  # at least the sleep duration, in ms


async def test_measure_logs_even_when_block_raises() -> None:
    logger = get_logger("test.timing")
    with capture_logs() as logs, pytest.raises(ValueError, match="boom"):
        async with measure(logger, "llm"):
            raise ValueError("boom")

    assert len(logs) == 1
    assert logs[0]["stage"] == "llm"
    assert logs[0]["event"] == LATENCY_EVENT


async def test_measure_supports_arbitrary_extra_context() -> None:
    logger = get_logger("test.timing")
    with capture_logs() as logs:
        async with measure(logger, "tts", conversation_id="CA2", call_sid="CA2", extra="x"):
            pass

    assert logs[0]["extra"] == "x"


async def test_with_deadline_returns_result_within_budget() -> None:
    async def quick() -> str:
        return "done"

    result = await with_deadline(quick(), seconds=1.0)
    assert result == "done"


async def test_with_deadline_raises_on_timeout() -> None:
    async def slow() -> None:
        await asyncio.sleep(1.0)

    with pytest.raises(TimeoutError):
        await with_deadline(slow(), seconds=0.05)
