"""Text-to-Speech port and its fallback chain of vendor adapters.

Synthesises the bot's lines into audio streamed back over the media stream.
No single vendor is trusted to always be up or billed: :class:`FallbackTTSService`
tries ElevenLabs first (voice naturalness), then Cartesia, then OpenAI TTS —
falling through to the next tier on any failure (a billing/auth lapse, an
outage, a timeout, or a missing credential) — with a local OS voice appended
as a last resort in development only.

ElevenLabs and Cartesia both speak Twilio's wire format (mu-law/8kHz) natively.
OpenAI TTS and the local OS voice don't, so their output is resampled and
mu-law-encoded here via :func:`_pcm16_to_mulaw_8k`.
"""

from __future__ import annotations

import asyncio
import audioop
import contextlib
import os
import tempfile
import wave
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from typing import cast

from cartesia import AsyncCartesia
from elevenlabs.client import AsyncElevenLabs
from openai import AsyncOpenAI

from app.config.settings import Settings
from app.models.audio import AudioChunk, AudioEncoding
from app.services.logger import get_logger

try:  # pragma: no cover - dev-only dependency, never installed in production
    import pyttsx3
except ImportError:  # pragma: no cover
    pyttsx3 = None


class TextToSpeechService(ABC):
    """Port: text in, streamed audio chunks out."""

    @abstractmethod
    async def synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        """Stream synthesised speech for ``text``.

        As with :meth:`~app.services.stt_service.SpeechToTextService.stream`,
        callers that stop consuming early (e.g. barge-in cutting off playback)
        should close this generator explicitly (``contextlib.aclosing`` or
        ``try/finally``) rather than a bare ``break``, so the provider
        connection is released promptly instead of waiting on GC.

        Args:
            text: The line the bot should speak.

        Yields:
            Audio chunks ready to forward to the telephony stream.
        """
        raise NotImplementedError
        yield  # pragma: no cover

    @abstractmethod
    async def aclose(self) -> None:
        """Release provider connections/resources."""
        raise NotImplementedError


def _is_billing_or_auth_error(exc: Exception) -> bool:
    """Whether ``exc`` looks like a billing/authorization failure (401/402/403).

    ElevenLabs, Cartesia, and OpenAI's SDKs each attach the HTTP status code
    to their error as ``.status_code``, so this check is vendor-agnostic by
    design rather than importing each SDK's own exception hierarchy.
    """
    return getattr(exc, "status_code", None) in (401, 402, 403)


def _pcm16_to_mulaw_8k(pcm_bytes: bytes, source_rate: int) -> bytes:
    """Downsample 16-bit mono PCM to 8kHz and encode it as mu-law.

    Args:
        pcm_bytes: Signed 16-bit little-endian mono PCM samples.
        source_rate: The sample rate ``pcm_bytes`` was recorded at.

    Returns:
        Mu-law-encoded bytes at 8kHz, matching Twilio's wire format.
    """
    if source_rate != 8000:
        pcm_bytes, _ = audioop.ratecv(pcm_bytes, 2, 1, source_rate, 8000, None)
    return audioop.lin2ulaw(pcm_bytes, 2)


class ElevenLabsTTSService(TextToSpeechService):
    """Adapter: ElevenLabs streaming TTS. Fallback chain tier 1.

    Bounded by ``elevenlabs_timeout_seconds`` so a stalled stream can never hang
    a call indefinitely; the client is built lazily and reused across calls.
    """

    def __init__(self, settings: Settings, *, client: AsyncElevenLabs | None = None) -> None:
        """Store config; the ElevenLabs client is built lazily (injectable for tests).

        Args:
            settings: Provides API key, voice ID, model, and timeout.
            client: Optional pre-built client (used by tests).
        """
        self._settings = settings
        self._client = client
        self._log = get_logger("elevenlabs.tts")

    def _client_or_create(self) -> AsyncElevenLabs:
        """Return the ElevenLabs client, constructing it on first use."""
        if self._client is None:
            key = self._settings.elevenlabs_api_key
            self._client = AsyncElevenLabs(api_key=key.get_secret_value() if key else None)
        return self._client

    async def synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        """Stream mu-law/8kHz audio for ``text``, matching Twilio's wire format.

        Bounds the whole utterance's synthesis time so a stalled connection
        cannot hang the call. Unlike the pre-fallback-chain version of this
        adapter, failures are *not* swallowed here — they propagate so
        :class:`FallbackTTSService` can fall through to the next tier. This
        adapter is only ever used as one tier of that chain (see
        ``get_tts_service()``), never standalone.
        """
        client = self._client_or_create()
        async with asyncio.timeout(self._settings.elevenlabs_timeout_seconds):
            stream = client.text_to_speech.convert_as_stream(
                voice_id=self._settings.elevenlabs_voice_id,
                text=text,
                model_id=self._settings.elevenlabs_model,
                output_format="ulaw_8000",
            )
            async for chunk in stream:
                yield AudioChunk(payload=chunk, encoding=AudioEncoding.MULAW_8000)

    async def aclose(self) -> None:
        """No public teardown API is exposed by the ElevenLabs SDK client."""
        self._log.debug("elevenlabs.tts_closed")


class CartesiaTTSService(TextToSpeechService):
    """Adapter: Cartesia TTS. Fallback chain tier 2.

    Requested directly in mu-law/8kHz via ``output_format``, matching Twilio's
    wire format exactly like ElevenLabs — no resampling needed.
    """

    def __init__(self, settings: Settings, *, client: AsyncCartesia | None = None) -> None:
        """Store config; the Cartesia client is built lazily (injectable for tests).

        Args:
            settings: Provides API key, voice ID, model, and timeout.
            client: Optional pre-built client (used by tests).
        """
        self._settings = settings
        self._client = client
        self._log = get_logger("cartesia.tts")

    def _client_or_create(self) -> AsyncCartesia:
        """Return the Cartesia client, constructing it on first use."""
        if self._client is None:
            key = self._settings.cartesia_api_key
            self._client = AsyncCartesia(api_key=key.get_secret_value() if key else None)
        return self._client

    async def synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        """Stream mu-law/8kHz audio for ``text``.

        Raises on any failure rather than swallowing it — see
        :meth:`ElevenLabsTTSService.synthesize` for why. Also raises if no
        voice id is configured (``get_tts_service()`` only adds this tier to
        the chain when one is, but this guards direct/standalone use too).
        """
        voice_id = self._settings.cartesia_voice_id
        if voice_id is None:
            raise ValueError("cartesia_voice_id is not configured")
        client = self._client_or_create()
        async with asyncio.timeout(self._settings.cartesia_timeout_seconds):
            response = await client.tts.generate(
                model_id=self._settings.cartesia_model,
                transcript=text,
                voice={"mode": "id", "id": voice_id},
                output_format={"container": "raw", "encoding": "pcm_mulaw", "sample_rate": 8000},
            )
            async for chunk_bytes in response.iter_bytes():
                if chunk_bytes:
                    yield AudioChunk(payload=chunk_bytes, encoding=AudioEncoding.MULAW_8000)

    async def aclose(self) -> None:
        """No public teardown API is exposed by the Cartesia SDK client."""
        self._log.debug("cartesia.tts_closed")


class OpenAITTSService(TextToSpeechService):
    """Adapter: OpenAI TTS. Fallback chain tier 3.

    OpenAI's ``pcm`` response format is a fixed 24kHz/16-bit/mono stream (not
    configurable), so it is resampled down to Twilio's native 8kHz mu-law.
    """

    def __init__(self, settings: Settings, *, client: AsyncOpenAI | None = None) -> None:
        """Store config; the OpenAI client is built lazily (injectable for tests).

        Args:
            settings: Provides API key, model, voice, and timeout.
            client: Optional pre-built client (used by tests).
        """
        self._settings = settings
        self._client = client
        self._log = get_logger("openai.tts")

    def _client_or_create(self) -> AsyncOpenAI:
        """Return the OpenAI client, constructing it on first use."""
        if self._client is None:
            key = self._settings.openai_api_key
            self._client = AsyncOpenAI(api_key=key.get_secret_value() if key else None)
        return self._client

    async def synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        """Synthesise ``text`` and yield it resampled to mu-law/8kHz.

        Raises on any failure rather than swallowing it — see
        :meth:`ElevenLabsTTSService.synthesize` for why. Not a true progressive
        stream (OpenAI's ``pcm`` response is read in full before resampling),
        so this yields exactly one chunk.
        """
        client = self._client_or_create()
        async with asyncio.timeout(self._settings.openai_tts_timeout_seconds):
            response = await client.audio.speech.create(
                model=self._settings.openai_tts_model,
                # The installed SDK's `voice` type predates newer voice names
                # (e.g. "coral"); verified working against the real API
                # despite the narrower Literal type this SDK version declares.
                voice=self._settings.openai_tts_voice,  # type: ignore[arg-type]
                input=text,
                response_format="pcm",
            )
            pcm_bytes = await response.aread()
        mulaw_bytes = _pcm16_to_mulaw_8k(pcm_bytes, source_rate=24000)
        if mulaw_bytes:
            yield AudioChunk(payload=mulaw_bytes, encoding=AudioEncoding.MULAW_8000)

    async def aclose(self) -> None:
        """No public teardown API is exposed by the OpenAI SDK client."""
        self._log.debug("openai.tts_closed")


class SystemTTSService(TextToSpeechService):
    """Adapter: the local machine's OS voice via ``pyttsx3``. Fallback chain tier 4.

    Development only — never constructed outside ``settings.environment ==
    "local"`` (enforced by ``get_tts_service()``), since it speaks with
    whatever voice happens to be installed on the host machine, not a real
    vendor. ``pyttsx3`` is a dev-only dependency (see ``requirements-dev.txt``)
    that is never installed in the production image, so the import above is
    guarded and this adapter degrades to raising (letting the chain end
    silently, same as if every tier failed) rather than crashing at import time.
    """

    def __init__(self, settings: Settings) -> None:
        """Store config.

        Args:
            settings: Unused today beyond existing for interface symmetry with
                the other tiers; kept for parity and future voice/rate options.
        """
        self._settings = settings
        self._log = get_logger("system.tts")
        if pyttsx3 is None:
            self._log.warning("system_tts.pyttsx3_not_installed")

    async def synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        """Synthesise ``text`` with the local OS voice, resampled to mu-law/8kHz."""
        if pyttsx3 is None:
            raise RuntimeError("pyttsx3 is not installed; the system TTS fallback is unavailable")
        pcm_bytes, source_rate = await asyncio.to_thread(self._synthesize_sync, text)
        mulaw_bytes = _pcm16_to_mulaw_8k(pcm_bytes, source_rate)
        if mulaw_bytes:
            yield AudioChunk(payload=mulaw_bytes, encoding=AudioEncoding.MULAW_8000)

    @staticmethod
    def _synthesize_sync(text: str) -> tuple[bytes, int]:
        """Blocking: drive the OS voice engine on a worker thread; return its raw PCM + rate."""
        assert pyttsx3 is not None  # guaranteed by synthesize()'s check before this is scheduled
        com_initialized = False
        try:
            import pythoncom  # Windows-only; SAPI5 needs COM initialized per-thread.

            pythoncom.CoInitialize()
            com_initialized = True
        except ImportError:
            pass  # Other platforms (NSSpeechSynthesizer/espeak) don't use COM.

        try:
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp.close()
            path = tmp.name
            try:
                engine = pyttsx3.init()
                try:
                    engine.save_to_file(text, path)
                    engine.runAndWait()
                finally:
                    engine.stop()
                with wave.open(path, "rb") as wf:
                    if wf.getnchannels() != 1 or wf.getsampwidth() != 2:
                        raise RuntimeError(
                            "unexpected system TTS WAV format: "
                            f"channels={wf.getnchannels()} sampwidth={wf.getsampwidth()}"
                        )
                    return wf.readframes(wf.getnframes()), wf.getframerate()
            finally:
                os.unlink(path)
        finally:
            if com_initialized:
                import pythoncom

                pythoncom.CoUninitialize()

    async def aclose(self) -> None:
        """No persistent resources: a fresh engine is created per call."""
        self._log.debug("system.tts_closed")


class FallbackTTSService(TextToSpeechService):
    """Composes the TTS provider priority chain.

    Tries each tier's ``synthesize()`` in order. A tier that raises — or that
    yields no audio at all without raising — is logged and the next tier is
    tried. Once a tier starts producing audio it is used for the rest of that
    line; a failure partway through an already-started stream is not retried
    on a different tier (that would splice two different voices mid-sentence),
    it simply ends the utterance there, exactly as a single-provider failure
    always has for every caller of this port.
    """

    def __init__(self, tiers: Sequence[tuple[str, TextToSpeechService]]) -> None:
        """Build the chain.

        Args:
            tiers: ``(name, service)`` pairs in priority order. At least one
                is required.
        """
        if not tiers:
            raise ValueError("FallbackTTSService requires at least one tier")
        self._tiers = tuple(tiers)
        self._log = get_logger("tts.fallback")

    @property
    def tier_names(self) -> tuple[str, ...]:
        """The configured provider names, in priority order (observability/tests)."""
        return tuple(name for name, _ in self._tiers)

    async def synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        """Try each tier in order, logging which provider ends up speaking the line."""
        last_index = len(self._tiers) - 1
        for index, (name, service) in enumerate(self._tiers):
            produced_audio = False
            try:
                stream = cast(AsyncGenerator[AudioChunk, None], service.synthesize(text))
                async with contextlib.aclosing(stream) as chunks:
                    async for chunk in chunks:
                        if not produced_audio:
                            produced_audio = True
                            self._log.info("tts.provider_selected", provider=name)
                        yield chunk
            except Exception as exc:  # deliberate catch-all: fall back, never crash the call
                self._log.warning(
                    "tts.provider_failed",
                    provider=name,
                    error=str(exc),
                    billing_or_auth=_is_billing_or_auth_error(exc),
                    falling_back=index < last_index,
                )
                if produced_audio:
                    return  # already streamed partial audio; can't switch voices mid-line
                continue
            if produced_audio:
                return
            self._log.warning(
                "tts.provider_produced_no_audio", provider=name, falling_back=index < last_index
            )
        self._log.error("tts.all_providers_exhausted", tiers=[name for name, _ in self._tiers])

    async def aclose(self) -> None:
        """Release every tier's resources."""
        for _, service in self._tiers:
            await service.aclose()
