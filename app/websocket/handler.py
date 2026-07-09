"""Media-stream transport handler.

Owns the full-duplex WebSocket lifecycle for one Twilio Media Stream: accept,
parse the wire protocol, bootstrap the :class:`~app.models.session.CallSession`,
bridge audio to/from :class:`~app.services.conversation_service.ConversationService`,
and tear down cleanly on ``stop`` or disconnect.

Scope boundary: this class handles **transport and the audio bridge only** —
decoding/encoding Twilio's wire audio and pumping it through
``ConversationService.run()``. It owns no conversation logic itself: STT, the
LLM, TTS, the state machine, and the qualification verdict all still live in
``ConversationService`` and its collaborators.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import structlog
from pydantic import ValidationError
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from app.config.settings import Settings
from app.models.audio import AudioChunk
from app.models.scenario import Scenario
from app.models.session import CallSession
from app.scenarios.registry import ScenarioNotFoundError, ScenarioRegistry
from app.services.conversation_service import ConversationService
from app.services.logger import BoundLogger, get_logger
from app.utils.audio import decode_twilio_media, encode_twilio_media
from app.websocket.protocol import InboundFrame, TwilioEvent, outbound_media

#: How long to let ConversationService.run() wind down after audio_in ends
#: (stop/disconnect) before giving up and closing the socket anyway. Deepgram
#: can take slightly over 10s to close its side after `finalize()` (observed
#: in live testing), so this is set with headroom above that.
_CONVERSATION_SHUTDOWN_TIMEOUT_SECONDS = 20.0


class MediaStreamHandler:
    """Drives one Twilio Media Stream WebSocket through transport and the conversation bridge."""

    def __init__(
        self,
        *,
        websocket: WebSocket,
        settings: Settings,
        conversation: ConversationService,
        scenario_registry: ScenarioRegistry,
        logger: BoundLogger | None = None,
    ) -> None:
        """Create a handler bound to a single socket.

        Args:
            websocket: The (not-yet-accepted) Twilio media WebSocket.
            settings: Application settings (default scenario, limits).
            conversation: Per-call orchestrator. Its ``run()`` is started as a
                concurrent task once the ``start`` frame arrives, fed by the
                inbound-audio queue and writing outbound audio back to the
                socket, for the rest of the call.
            scenario_registry: Resolves the stream's scenario id to a real
                :class:`~app.models.scenario.Scenario`.
            logger: Optional pre-bound logger; one is created if omitted.
        """
        self._ws = websocket
        self._settings = settings
        self._conversation = conversation
        self._scenario_registry = scenario_registry
        self._log = logger or get_logger("media_stream")
        self._session: CallSession | None = None
        self._media_frames = 0
        self._inbound_audio: asyncio.Queue[AudioChunk | None] | None = None
        self._conversation_task: asyncio.Task[None] | None = None

    @property
    def session(self) -> CallSession | None:
        """The call session, available once the ``start`` frame is received."""
        return self._session

    async def run(self) -> None:
        """Accept the socket and pump frames until ``stop`` or disconnect."""
        await self._ws.accept()
        client_host = getattr(self._ws.client, "host", None)
        self._log.info("media_stream.accepted", client=client_host)
        try:
            async for raw in self._ws.iter_text():
                frame = self._parse(raw)
                if frame is None:
                    continue
                if await self._dispatch(frame):
                    break
        except WebSocketDisconnect as exc:
            self._log.info("media_stream.disconnected", code=exc.code)
        finally:
            await self._close()

    def _parse(self, raw: str) -> InboundFrame | None:
        """Decode one raw text frame, tolerating malformed/unknown messages."""
        try:
            return InboundFrame.model_validate_json(raw)
        except ValidationError as exc:
            self._log.warning("media_stream.unparseable_frame", errors=exc.error_count())
            return None

    async def _dispatch(self, frame: InboundFrame) -> bool:
        """Route a frame to its handler.

        Returns:
            ``True`` when the stream should stop (``stop`` frame), else ``False``.
        """
        match frame.event:
            case TwilioEvent.CONNECTED:
                self._log.debug("media_stream.connected")
            case TwilioEvent.START:
                self._on_start(frame)
            case TwilioEvent.MEDIA:
                self._media_frames += 1
                await self._on_media(frame)
            case TwilioEvent.MARK:
                self._log.debug("media_stream.mark", name=frame.mark.name if frame.mark else None)
            case TwilioEvent.DTMF:
                self._log.debug("media_stream.dtmf")
            case TwilioEvent.STOP:
                self._log.info("media_stream.stop", media_frames=self._media_frames)
                return True
        return False

    def _on_start(self, frame: InboundFrame) -> None:
        """Bootstrap the call session and start the conversation bridge."""
        start = frame.start
        if start is None:
            self._log.warning("media_stream.start_without_metadata")
            return

        scenario_id = start.custom_parameters.get("scenario", self._settings.default_scenario_id)
        try:
            scenario = self._scenario_registry.get(scenario_id)
        except ScenarioNotFoundError:
            self._log.error("media_stream.unknown_scenario", scenario_id=scenario_id)
            return

        self._session = CallSession(
            call_sid=start.call_sid,
            stream_sid=start.stream_sid,
            scenario_id=scenario_id,
        )
        # Bind call identifiers so every subsequent log line is correlated.
        structlog.contextvars.bind_contextvars(
            call_sid=start.call_sid,
            stream_sid=start.stream_sid,
            scenario=scenario_id,
        )
        self._log.info(
            "media_stream.started",
            tracks=start.tracks,
            media_format=start.media_format.model_dump() if start.media_format else None,
        )
        # ── Conversation handoff ─────────────────────────────────────────────
        # Runs concurrently with this frame-pump loop for the rest of the call:
        # inbound MEDIA frames are decoded and queued for ConversationService.run()
        # to consume as audio_in, and every audio chunk it synthesises is encoded
        # and streamed straight back to Twilio via _send_audio.
        self._inbound_audio = asyncio.Queue()
        self._conversation_task = asyncio.create_task(
            self._run_conversation(self._session, scenario)
        )

    async def _on_media(self, frame: InboundFrame) -> None:
        """Decode one inbound audio frame and enqueue it for ``ConversationService.run()``."""
        inbound_audio = self._inbound_audio
        if inbound_audio is None or frame.media is None:
            return
        try:
            chunk = decode_twilio_media(frame.media.payload)
        except ValueError:
            self._log.warning("media_stream.unparseable_media_payload")
            return
        await inbound_audio.put(chunk)

    async def _run_conversation(self, session: CallSession, scenario: Scenario) -> None:
        """Drive the conversation for this call; failures are logged, never raised.

        Runs as a concurrent task started from ``_on_start`` so it can consume
        inbound audio and send outbound audio for the rest of the call while
        the transport loop keeps pumping frames off the socket.
        """
        try:
            await self._conversation.run(
                session, scenario, self._consume_inbound_audio(), self._send_audio
            )
        except Exception:  # deliberate catch-all: a failed call must not crash the transport
            self._log.exception("media_stream.conversation_failed")

    async def _consume_inbound_audio(self) -> AsyncIterator[AudioChunk]:
        """Adapt the inbound queue into the ``AsyncIterator[AudioChunk]`` STT expects."""
        queue = self._inbound_audio
        assert queue is not None  # only ever iterated after _on_start creates it
        while True:
            chunk = await queue.get()
            if chunk is None:  # sentinel pushed by _close() to end the stream
                return
            yield chunk

    async def _send_audio(self, chunk: AudioChunk) -> None:
        """Encode one synthesised audio chunk and stream it back to Twilio."""
        session = self._session
        if session is None or session.stream_sid is None:
            return
        if self._ws.application_state is not WebSocketState.CONNECTED:
            return
        frame = outbound_media(session.stream_sid, encode_twilio_media(chunk))
        await self._ws.send_text(json.dumps(frame))

    async def _close(self) -> None:
        """End the conversation bridge, log a session summary, and close the socket."""
        inbound_audio = self._inbound_audio
        if inbound_audio is not None:
            await inbound_audio.put(None)

        conversation_task = self._conversation_task
        if conversation_task is not None:
            try:
                await asyncio.wait_for(
                    conversation_task, timeout=_CONVERSATION_SHUTDOWN_TIMEOUT_SECONDS
                )
            except TimeoutError:
                self._log.warning("media_stream.conversation_shutdown_timeout")

        self._log.info(
            "media_stream.closed",
            media_frames=self._media_frames,
            had_session=self._session is not None,
        )
        structlog.contextvars.clear_contextvars()
        if self._ws.application_state is not WebSocketState.DISCONNECTED:
            try:
                await self._ws.close()
            except RuntimeError:
                # Socket already closing/closed underneath us — nothing to do.
                pass
