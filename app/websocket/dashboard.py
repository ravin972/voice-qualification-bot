"""Dashboard live-event WebSocket endpoint.

Streams :class:`~app.models.events.ConversationUpdate` snapshots to a connected
dashboard as they happen — the read side of the observability path

    ConversationService.run()  ->  EventBus  ->  /dashboard/stream  ->  dashboard

This route is pure transport glue: it subscribes to the bus and forwards each
snapshot as JSON. It never produces snapshots and holds no conversation logic.
A concurrent reader detects client disconnects promptly (even while idle) so a
closed dashboard is unsubscribed immediately rather than lingering until the
next event.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from fastapi import APIRouter
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from app.config.dependencies import EventBusDep
from app.models.events import ConversationUpdate
from app.services.event_bus import InMemoryEventBus
from app.services.logger import get_logger

router = APIRouter()


@router.websocket("/dashboard/stream")
async def dashboard_stream(websocket: WebSocket, event_bus: EventBusDep) -> None:
    """Forward live conversation snapshots to one connected dashboard.

    Args:
        websocket: The dashboard's WebSocket (accepted here).
        event_bus: The process-wide snapshot bus (injected).
    """
    await websocket.accept()
    log = get_logger("dashboard_stream")
    log.info("dashboard_stream.connected", client=getattr(websocket.client, "host", None))
    try:
        await _pump(websocket, event_bus)
    except WebSocketDisconnect as exc:
        log.info("dashboard_stream.disconnected", code=exc.code)
    finally:
        log.info("dashboard_stream.closed")
        if websocket.application_state is not WebSocketState.DISCONNECTED:
            with contextlib.suppress(RuntimeError):
                await websocket.close()


async def _pump(websocket: WebSocket, event_bus: InMemoryEventBus[ConversationUpdate]) -> None:
    """Forward bus snapshots to the socket until either side ends the connection.

    Runs the forwarder and a disconnect-watcher concurrently and stops as soon
    as either completes, so an idle-but-closed dashboard is noticed immediately.
    """
    async with event_bus.subscribe() as updates:
        forwarder = asyncio.create_task(_forward(websocket, updates))
        watcher = asyncio.create_task(_watch_for_disconnect(websocket))
        done, pending = await asyncio.wait(
            {forwarder, watcher}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            # A clean client disconnect is the normal way this ends; only a
            # genuine failure (e.g. a serialisation bug) should propagate.
            exc = task.exception()
            if exc is not None and not isinstance(exc, WebSocketDisconnect):
                raise exc


async def _forward(websocket: WebSocket, updates: AsyncIterator[ConversationUpdate]) -> None:
    """Send each snapshot to the dashboard as JSON."""
    async for update in updates:
        await websocket.send_text(update.model_dump_json())


async def _watch_for_disconnect(websocket: WebSocket) -> None:
    """Block on inbound frames purely to detect the client closing the socket.

    ``receive()`` *returns* a ``websocket.disconnect`` message rather than
    raising, so this stops at that message instead of calling ``receive()``
    again (which Starlette rejects once disconnected).
    """
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
