"""In-process publish/subscribe transport for dashboard event streams.

Pure plumbing. This module is deliberately generic (``EventPublisher[T]``) and
imports nothing from the domain: it knows nothing about Twilio, Deepgram,
OpenAI, the state machine, or the qualification logic. It moves opaque immutable
events from one producer (a live call) to N consumers (dashboard WebSockets) and
does nothing else — no interpretation, no decisions, no serialisation.

Two guarantees the call path relies on:

* **Publishing never blocks.** Fan-out is non-awaiting ``put_nowait`` onto
  bounded per-subscriber queues; a slow or stuck consumer can never stall the
  call producing the events.
* **Publishing never raises.** A full queue drops its oldest event to make room
  rather than propagating an error back into the caller.
"""

from __future__ import annotations

import asyncio
import contextlib
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import AsyncIterator
from typing import Generic, TypeVar

from app.services.logger import get_logger

T = TypeVar("T")

#: Max buffered events per subscriber before the oldest is dropped.
_DEFAULT_SUBSCRIBER_QUEUE_SIZE = 256

#: How many recent events a freshly-connected subscriber is replayed.
_DEFAULT_REPLAY_BUFFER_SIZE = 50


class EventPublisher(ABC, Generic[T]):
    """Port: somewhere to publish an event. Producers depend only on this."""

    @abstractmethod
    async def publish(self, event: T) -> None:
        """Publish one event to whoever is listening (never blocks the caller)."""
        raise NotImplementedError


class NullEventPublisher(EventPublisher[T]):
    """No-op publisher — the default when no dashboard bus is wired in.

    Lets a producer (e.g. ``ConversationService``) emit unconditionally without
    caring whether anything is observing, and keeps behaviour identical to
    "no observability at all" when the bus is absent (tests, minimal runs).
    """

    async def publish(self, event: T) -> None:
        """Discard the event."""
        return None


class InMemoryEventBus(EventPublisher[T]):
    """Single-process fan-out bus with per-subscriber back-pressure and replay.

    All access happens on one asyncio event loop, so the mutations below are
    atomic between ``await`` points and need no locking.
    """

    def __init__(
        self,
        *,
        subscriber_queue_size: int = _DEFAULT_SUBSCRIBER_QUEUE_SIZE,
        replay_buffer_size: int = _DEFAULT_REPLAY_BUFFER_SIZE,
    ) -> None:
        """Configure queue bounds.

        Args:
            subscriber_queue_size: Max events buffered per subscriber before the
                oldest is dropped.
            replay_buffer_size: How many recent events a new subscriber receives
                on connect, so a dashboard joining mid-call catches up.
        """
        self._subscriber_queue_size = subscriber_queue_size
        self._subscribers: set[asyncio.Queue[T]] = set()
        self._replay: deque[T] = deque(maxlen=replay_buffer_size)
        self._log = get_logger("event_bus")

    @property
    def subscriber_count(self) -> int:
        """How many subscribers are currently connected (observability/tests)."""
        return len(self._subscribers)

    async def publish(self, event: T) -> None:
        """Fan ``event`` out to every subscriber without ever blocking or raising."""
        self._replay.append(event)
        for queue in self._subscribers:
            self._offer(queue, event)

    def _offer(self, queue: asyncio.Queue[T], event: T) -> None:
        """Enqueue ``event``, dropping this subscriber's oldest event if it is full."""
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            # A lagging consumer must never back-pressure the call path: drop its
            # oldest buffered event to make room for the newest.
            with contextlib.suppress(asyncio.QueueEmpty, asyncio.QueueFull):
                queue.get_nowait()
                queue.put_nowait(event)
            self._log.warning("event_bus.subscriber_lagging")

    @contextlib.asynccontextmanager
    async def subscribe(self) -> AsyncIterator[AsyncIterator[T]]:
        """Subscribe for the duration of the ``async with`` block.

        Yields an async iterator of events. The most recent buffered events are
        delivered first (replay) so a subscriber that connects mid-stream is not
        blank, followed by live events as they are published. The subscription
        is always torn down on exit.
        """
        queue: asyncio.Queue[T] = asyncio.Queue(maxsize=self._subscriber_queue_size)
        for event in self._replay:
            self._offer(queue, event)
        self._subscribers.add(queue)
        self._log.info("event_bus.subscribed", subscribers=len(self._subscribers))
        try:
            yield self._consume(queue)
        finally:
            self._subscribers.discard(queue)
            self._log.info("event_bus.unsubscribed", subscribers=len(self._subscribers))

    @staticmethod
    async def _consume(queue: asyncio.Queue[T]) -> AsyncIterator[T]:
        """Yield events from one subscriber's queue until the subscription ends."""
        while True:
            yield await queue.get()
