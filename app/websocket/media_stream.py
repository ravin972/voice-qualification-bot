"""Twilio Media Streams WebSocket endpoint.

The real-time, full-duplex audio boundary (``wss://``). This module is a thin
route that injects settings and the conversation collaborators and hands the
socket to :class:`~app.websocket.handler.MediaStreamHandler`, which owns the
transport lifecycle and the bridge to ``ConversationService.run()``.
"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket

from app.config.dependencies import ConversationServiceDep, ScenarioRegistryDep, SettingsDep
from app.services.logger import get_logger
from app.websocket.handler import MediaStreamHandler

router = APIRouter()


@router.websocket("/media-stream")
async def media_stream(
    websocket: WebSocket,
    settings: SettingsDep,
    conversation: ConversationServiceDep,
    scenario_registry: ScenarioRegistryDep,
) -> None:
    """Handle one Twilio Media Stream for the lifetime of a call.

    Args:
        websocket: The Twilio media WebSocket (accepted inside the handler).
        settings: Injected application settings.
        conversation: Per-call orchestrator wired to the real STT/LLM/TTS ports.
        scenario_registry: Resolves the stream's scenario id to a real Scenario.
    """
    handler = MediaStreamHandler(
        websocket=websocket,
        settings=settings,
        conversation=conversation,
        scenario_registry=scenario_registry,
        logger=get_logger("media_stream"),
    )
    await handler.run()
