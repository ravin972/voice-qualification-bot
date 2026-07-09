"""Speech-to-Text port and Deepgram adapter.

Streaming ASR converts inbound μ-law audio frames (Twilio's native wire format —
no transcoding needed) into interim and final transcripts. The Deepgram SDK is
callback-based; this adapter bridges those callbacks onto an ``asyncio.Queue``
so it can expose the provider-agnostic ``AsyncIterator[Transcript]`` port.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from deepgram import (
    DeepgramClient,
    LiveOptions,
    LiveResultResponse,
    LiveTranscriptionEvents,
)

from app.config.settings import Settings
from app.models.audio import AudioChunk, Transcript
from app.services.logger import get_logger

#: Sentinel pushed onto the internal queue to signal the stream has ended.
_END_OF_STREAM: Transcript | None = None


class SpeechToTextService(ABC):
    """Port: stream audio in, receive transcripts out."""

    @abstractmethod
    async def stream(self, audio: AsyncIterator[AudioChunk]) -> AsyncIterator[Transcript]:
        """Consume an audio stream and yield transcripts as they are recognised.

        Callers that stop iterating before the stream ends naturally (e.g. on
        hangup) MUST close the generator explicitly — via ``contextlib.aclosing``
        or an equivalent ``try/finally`` — rather than just ``break``-ing out of
        the loop. A bare ``break`` does not synchronously run the generator's
        cleanup (that only happens on ``aclose()`` or eventual GC), so it can
        leave the underlying provider connection open longer than necessary.

        Args:
            audio: Async stream of inbound audio frames.

        Yields:
            Interim and final :class:`Transcript` objects.
        """
        raise NotImplementedError
        yield  # pragma: no cover  (makes this an async generator for typing)

    @abstractmethod
    async def aclose(self) -> None:
        """Release provider connections/resources."""
        raise NotImplementedError


class DeepgramSTTService(SpeechToTextService):
    """Adapter: Deepgram streaming ASR over WebSocket.

    A fresh Deepgram live connection is opened per :meth:`stream` call (i.e. per
    phone call) and torn down when the caller's audio stream ends. Twilio's
    8 kHz μ-law frames are forwarded to Deepgram unmodified.
    """

    def __init__(self, settings: Settings, *, client: DeepgramClient | None = None) -> None:
        """Store config; the Deepgram client is built lazily (injectable for tests).

        Args:
            settings: Provides API key, model, and language.
            client: Optional pre-built client (used by tests).
        """
        self._settings = settings
        self._client = client
        self._log = get_logger("deepgram.stt")

    def _client_or_create(self) -> DeepgramClient:
        """Return the Deepgram client, constructing it on first use."""
        if self._client is None:
            key = self._settings.deepgram_api_key
            self._client = DeepgramClient(api_key=key.get_secret_value() if key else "")
        return self._client

    def _live_options(self) -> LiveOptions:
        """Build the live-transcription options for a phone-call audio stream."""
        return LiveOptions(
            model=self._settings.deepgram_model,
            language=self._settings.deepgram_language,
            encoding="mulaw",
            sample_rate=8000,
            channels=1,
            interim_results=True,
            smart_format=True,
            punctuate=True,
            vad_events=True,
            utterance_end_ms="1000",
        )

    async def stream(self, audio: AsyncIterator[AudioChunk]) -> AsyncIterator[Transcript]:
        """Bridge Deepgram's callback API onto an async transcript stream.

        Opens one live connection, spawns a task that forwards ``audio`` frames
        to it, and yields :class:`Transcript` objects as Deepgram emits them.
        The connection and feeder task are always cleaned up on exit, including
        when the consumer stops iterating early.
        """
        connection = self._client_or_create().listen.asyncwebsocket.v("1")
        queue: asyncio.Queue[Transcript | None] = asyncio.Queue()

        async def on_transcript(
            _client: object, result: LiveResultResponse, **_kwargs: object
        ) -> None:
            alternatives = result.channel.alternatives if result.channel else []
            if not alternatives:
                return
            best = alternatives[0]
            # Deepgram emits final results with EMPTY text for silence segments
            # (VAD utterance boundaries). Those are not utterances — forwarding
            # them would make the conversation treat silence as an UNCLEAR
            # answer and burn its reprompt budget (observed on a real call).
            if not best.transcript.strip():
                return
            self._log.debug(
                "deepgram.transcript",
                is_final=result.is_final,
                chars=len(best.transcript),
                confidence=best.confidence,
            )
            await queue.put(
                Transcript(
                    text=best.transcript, is_final=result.is_final, confidence=best.confidence
                )
            )

        async def on_error(_client: object, error: object, **_kwargs: object) -> None:
            self._log.warning("deepgram.stt_error", error=str(error))
            await queue.put(_END_OF_STREAM)

        async def on_close(_client: object, **_kwargs: object) -> None:
            await queue.put(_END_OF_STREAM)

        connection.on(LiveTranscriptionEvents.Transcript, on_transcript)
        connection.on(LiveTranscriptionEvents.Error, on_error)
        connection.on(LiveTranscriptionEvents.Close, on_close)

        started = await connection.start(self._live_options())
        if not started:
            self._log.error("deepgram.stt_start_failed")
            return

        feeder = asyncio.create_task(self._feed_audio(connection, audio))
        try:
            while True:
                transcript = await queue.get()
                if transcript is None:  # sentinel: _END_OF_STREAM was pushed
                    break
                yield transcript
        finally:
            feeder.cancel()
            await connection.finish()

    async def _feed_audio(self, connection: object, audio: AsyncIterator[AudioChunk]) -> None:
        """Forward inbound audio chunks to the live Deepgram connection."""
        try:
            async for chunk in audio:
                await connection.send(chunk.payload)  # type: ignore[attr-defined]
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # deliberate catch-all: never let feeding crash the stream
            self._log.warning("deepgram.stt_feed_failed", error=str(exc))
        finally:
            await connection.finalize()  # type: ignore[attr-defined]

    async def aclose(self) -> None:
        """No persistent resources beyond the per-call connection in stream()."""
        self._log.debug("deepgram.stt_closed")
