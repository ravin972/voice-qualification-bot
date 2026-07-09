"""InMemoryEventBus transport tests.

The bus is generic and domain-free, so these tests use plain strings/ints as
events — nothing here imports a ConversationUpdate. They pin the three
properties the call path depends on: fan-out to every subscriber, replay for
late joiners, and publishing that never blocks or raises even when a subscriber
is full or gone.
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest
from app.services.event_bus import InMemoryEventBus, NullEventPublisher


async def _next(updates: object, *, deadline_s: float = 1.0) -> object:
    """Pull the next event from a subscriber iterator with a safety timeout."""
    return await asyncio.wait_for(updates.__anext__(), timeout=deadline_s)  # type: ignore[attr-defined]


async def test_null_publisher_is_a_silent_no_op() -> None:
    publisher: NullEventPublisher[str] = NullEventPublisher()
    await publisher.publish("anything")  # no subscribers, no state, no error


async def test_subscriber_receives_published_events_in_order() -> None:
    bus: InMemoryEventBus[str] = InMemoryEventBus()
    async with bus.subscribe() as updates:
        await bus.publish("a")
        await bus.publish("b")
        assert await _next(updates) == "a"
        assert await _next(updates) == "b"


async def test_publish_fans_out_to_every_subscriber() -> None:
    bus: InMemoryEventBus[str] = InMemoryEventBus()
    async with bus.subscribe() as first, bus.subscribe() as second:
        assert bus.subscriber_count == 2
        await bus.publish("broadcast")
        assert await _next(first) == "broadcast"
        assert await _next(second) == "broadcast"


async def test_late_subscriber_is_replayed_recent_events() -> None:
    bus: InMemoryEventBus[str] = InMemoryEventBus(replay_buffer_size=10)
    await bus.publish("before-1")
    await bus.publish("before-2")
    async with bus.subscribe() as updates:
        assert await _next(updates) == "before-1"
        assert await _next(updates) == "before-2"


async def test_replay_buffer_is_bounded_to_the_most_recent_events() -> None:
    bus: InMemoryEventBus[int] = InMemoryEventBus(replay_buffer_size=3)
    for value in range(6):
        await bus.publish(value)
    async with bus.subscribe() as updates:
        replayed = [await _next(updates) for _ in range(3)]
    assert replayed == [3, 4, 5]  # only the last 3 survived


async def test_publish_never_blocks_or_raises_when_a_subscriber_is_full() -> None:
    # Tiny queue, no replay, and we never drain it: publishing far past capacity
    # must still return cleanly (oldest events dropped) rather than blocking.
    bus: InMemoryEventBus[int] = InMemoryEventBus(subscriber_queue_size=2, replay_buffer_size=0)
    async with bus.subscribe() as updates:
        for value in range(100):
            await bus.publish(value)
        # The subscriber only ever sees the most recent events; the call that
        # produced them was never stalled.
        drained = [await _next(updates) for _ in range(2)]
    assert drained == [98, 99]


async def test_unsubscribe_on_exit_stops_delivery_and_frees_the_slot() -> None:
    bus: InMemoryEventBus[str] = InMemoryEventBus()
    async with bus.subscribe():
        assert bus.subscriber_count == 1
    assert bus.subscriber_count == 0
    # Publishing with no subscribers is a clean no-op.
    await bus.publish("into the void")


async def test_one_slow_subscriber_does_not_starve_another() -> None:
    bus: InMemoryEventBus[int] = InMemoryEventBus(subscriber_queue_size=2, replay_buffer_size=0)
    async with bus.subscribe() as slow, bus.subscribe() as fast:  # noqa: F841 (slow never drained)
        for value in range(50):
            await bus.publish(value)
        # `fast` still gets recent events despite `slow` overflowing.
        assert await _next(fast) in range(50)


def test_subscribe_teardown_runs_even_if_body_raises() -> None:
    # A subscriber whose consumer errors out must still be removed.
    bus: InMemoryEventBus[str] = InMemoryEventBus()

    async def scenario() -> None:
        with contextlib.suppress(RuntimeError):
            async with bus.subscribe():
                assert bus.subscriber_count == 1
                raise RuntimeError("consumer blew up")

    asyncio.run(scenario())
    assert bus.subscriber_count == 0


def test_bus_is_reusable_after_pytest_raises_inside_a_subscription() -> None:
    bus: InMemoryEventBus[str] = InMemoryEventBus()

    async def scenario() -> None:
        with pytest.raises(ValueError):
            async with bus.subscribe():
                raise ValueError("boom")
        async with bus.subscribe() as updates:
            await bus.publish("still-works")
            assert await _next(updates) == "still-works"

    asyncio.run(scenario())
