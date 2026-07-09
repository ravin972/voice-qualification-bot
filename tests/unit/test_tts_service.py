"""TTS fallback-chain unit tests.

Fakes exist only at the vendor-adapter boundary (the injected SDK client, or
`pyttsx3` for the local OS voice); FallbackTTSService's own cascade/logging
logic and the PCM->mu-law resample helper are exercised for real. No network
calls, no ASGI app.
"""

from __future__ import annotations

import audioop
import wave
from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
from app.config.settings import Settings
from app.models.audio import AudioChunk, AudioEncoding
from app.services.tts_service import (
    CartesiaTTSService,
    ElevenLabsTTSService,
    FallbackTTSService,
    OpenAITTSService,
    SystemTTSService,
    TextToSpeechService,
    _is_billing_or_auth_error,
    _pcm16_to_mulaw_8k,
)
from structlog.testing import capture_logs
from structlog.typing import EventDict


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]


class _StatusError(Exception):
    """Minimal stand-in for any vendor SDK's HTTP-status-carrying exception."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"stub error {status_code}")
        self.status_code = status_code


def _events(logs: list[EventDict], event: str) -> list[EventDict]:
    return [entry for entry in logs if entry.get("event") == event]


async def _collect(service: TextToSpeechService, text: str = "hello") -> list[bytes]:
    return [chunk.payload async for chunk in service.synthesize(text)]


# --- _is_billing_or_auth_error --------------------------------------------------


@pytest.mark.parametrize("status_code", [401, 402, 403])
def test_billing_or_auth_error_detects_401_402_403(status_code: int) -> None:
    assert _is_billing_or_auth_error(_StatusError(status_code)) is True


@pytest.mark.parametrize("status_code", [400, 404, 429, 500])
def test_billing_or_auth_error_ignores_other_status_codes(status_code: int) -> None:
    assert _is_billing_or_auth_error(_StatusError(status_code)) is False


def test_billing_or_auth_error_ignores_exceptions_without_a_status_code() -> None:
    assert _is_billing_or_auth_error(TimeoutError("slow")) is False
    assert _is_billing_or_auth_error(RuntimeError("boom")) is False


# --- _pcm16_to_mulaw_8k -----------------------------------------------------------


def test_resample_downsamples_and_encodes_to_one_byte_per_sample() -> None:
    pcm = b"\x10\x00" * 24000  # 1s of mono 16-bit silence-ish PCM @ 24kHz
    mulaw = _pcm16_to_mulaw_8k(pcm, source_rate=24000)
    assert len(mulaw) == pytest.approx(8000, abs=5)  # ~1s @ 8kHz, 1 byte/sample


def test_resample_skips_ratecv_when_already_8khz() -> None:
    pcm = b"\x10\x00" * 8000
    assert _pcm16_to_mulaw_8k(pcm, source_rate=8000) == audioop.lin2ulaw(pcm, 2)


# --- ElevenLabsTTSService (fallback tier 1) ---------------------------------------


class _FakeElevenLabsStream:
    def __init__(self, chunks: list[bytes], error: Exception | None) -> None:
        self._chunks = chunks
        self._error = error

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self._generate()

    async def _generate(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk
        if self._error is not None:
            raise self._error


def _fake_elevenlabs_client(chunks: list[bytes], error: Exception | None = None) -> object:
    text_to_speech = SimpleNamespace(
        convert_as_stream=lambda **_kwargs: _FakeElevenLabsStream(chunks, error)
    )
    return SimpleNamespace(text_to_speech=text_to_speech)


async def test_elevenlabs_wraps_chunks_as_mulaw_audio() -> None:
    client = _fake_elevenlabs_client([b"a", b"b"])
    service = ElevenLabsTTSService(_settings(), client=client)  # type: ignore[arg-type]

    chunks = [chunk async for chunk in service.synthesize("hi")]

    assert [c.payload for c in chunks] == [b"a", b"b"]
    assert all(c.encoding == AudioEncoding.MULAW_8000 for c in chunks)


async def test_elevenlabs_propagates_errors_instead_of_swallowing_them() -> None:
    client = _fake_elevenlabs_client([], error=_StatusError(402))
    service = ElevenLabsTTSService(_settings(), client=client)  # type: ignore[arg-type]

    with pytest.raises(_StatusError):
        await _collect(service)


# --- CartesiaTTSService (fallback tier 2) -----------------------------------------


class _FakeCartesiaResponse:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def iter_bytes(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk


def _fake_cartesia_client(chunks: list[bytes], error: Exception | None = None) -> object:
    async def generate(**_kwargs: object) -> _FakeCartesiaResponse:
        if error is not None:
            raise error
        return _FakeCartesiaResponse(chunks)

    return SimpleNamespace(tts=SimpleNamespace(generate=generate))


async def test_cartesia_requires_a_configured_voice_id() -> None:
    service = CartesiaTTSService(_settings(cartesia_voice_id=None))

    with pytest.raises(ValueError, match="cartesia_voice_id"):
        await _collect(service)


async def test_cartesia_wraps_chunks_as_mulaw_audio() -> None:
    client = _fake_cartesia_client([b"a", b"b"])
    service = CartesiaTTSService(
        _settings(cartesia_voice_id="voice-123"),
        client=client,  # type: ignore[arg-type]
    )

    chunks = [chunk async for chunk in service.synthesize("hi")]

    assert [c.payload for c in chunks] == [b"a", b"b"]
    assert all(c.encoding == AudioEncoding.MULAW_8000 for c in chunks)


async def test_cartesia_propagates_errors_instead_of_swallowing_them() -> None:
    client = _fake_cartesia_client([], error=_StatusError(403))
    service = CartesiaTTSService(
        _settings(cartesia_voice_id="voice-123"),
        client=client,  # type: ignore[arg-type]
    )

    with pytest.raises(_StatusError):
        await _collect(service)


# --- OpenAITTSService (fallback tier 3) -------------------------------------------


def _fake_openai_client(pcm_bytes: bytes, error: Exception | None = None) -> object:
    async def create(**_kwargs: object) -> object:
        if error is not None:
            raise error

        async def aread() -> bytes:
            return pcm_bytes

        return SimpleNamespace(aread=aread)

    return SimpleNamespace(audio=SimpleNamespace(speech=SimpleNamespace(create=create)))


async def test_openai_tts_resamples_pcm_to_mulaw_8k() -> None:
    pcm_bytes = b"\x10\x00" * 24000  # OpenAI's fixed 24kHz mono PCM
    client = _fake_openai_client(pcm_bytes)
    service = OpenAITTSService(_settings(), client=client)  # type: ignore[arg-type]

    chunks = await _collect(service)

    assert chunks == [_pcm16_to_mulaw_8k(pcm_bytes, source_rate=24000)]


async def test_openai_tts_propagates_errors_instead_of_swallowing_them() -> None:
    client = _fake_openai_client(b"", error=_StatusError(401))
    service = OpenAITTSService(_settings(), client=client)  # type: ignore[arg-type]

    with pytest.raises(_StatusError):
        await _collect(service)


# --- SystemTTSService (fallback tier 4, development only) ------------------------


class _FakeEngine:
    """Stands in for a pyttsx3 engine: writes a real, deterministic WAV file."""

    def __init__(self, *, channels: int = 1, sampwidth: int = 2, framerate: int = 22050) -> None:
        self._channels = channels
        self._sampwidth = sampwidth
        self._framerate = framerate
        self._path: str | None = None

    def save_to_file(self, _text: str, path: str) -> None:
        self._path = path

    def runAndWait(self) -> None:  # noqa: N802 (matches pyttsx3's real API name)
        assert self._path is not None
        with wave.open(self._path, "wb") as wf:
            wf.setnchannels(self._channels)
            wf.setsampwidth(self._sampwidth)
            wf.setframerate(self._framerate)
            wf.writeframes(b"\x10\x00" * self._framerate)  # ~1s of PCM

    def stop(self) -> None:
        pass


async def test_system_tts_raises_when_pyttsx3_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.tts_service.pyttsx3", None)
    service = SystemTTSService(_settings())

    with pytest.raises(RuntimeError, match="pyttsx3"):
        await _collect(service)


async def test_system_tts_resamples_engine_output_to_mulaw_8k(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_module = SimpleNamespace(init=lambda: _FakeEngine(framerate=22050))
    monkeypatch.setattr("app.services.tts_service.pyttsx3", fake_module)
    service = SystemTTSService(_settings())

    chunks = await _collect(service)

    assert len(chunks) == 1
    assert len(chunks[0]) == pytest.approx(8000, abs=5)  # ~1s @ 8kHz mu-law


async def test_system_tts_rejects_unexpected_wav_format(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = SimpleNamespace(init=lambda: _FakeEngine(channels=2))  # stereo, unsupported
    monkeypatch.setattr("app.services.tts_service.pyttsx3", fake_module)
    service = SystemTTSService(_settings())

    with pytest.raises(RuntimeError, match="unexpected system TTS WAV format"):
        await _collect(service)


# --- FallbackTTSService ------------------------------------------------------------


class _FakeProvider(TextToSpeechService):
    """Yields pre-scripted chunks, then optionally raises."""

    def __init__(self, chunks: list[bytes], *, error: Exception | None = None) -> None:
        self._chunks = chunks
        self._error = error
        self.calls: list[str] = []
        self.closed = False

    async def synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        self.calls.append(text)
        for payload in self._chunks:
            yield AudioChunk(payload=payload)
        if self._error is not None:
            raise self._error

    async def aclose(self) -> None:
        self.closed = True


def _fallback(*tiers: tuple[str, TextToSpeechService]) -> FallbackTTSService:
    return FallbackTTSService(list(tiers))


async def test_first_tier_success_is_used_and_selection_is_logged() -> None:
    primary = _FakeProvider([b"a", b"b"])
    backup = _FakeProvider([b"z"])
    service = _fallback(("primary", primary), ("backup", backup))

    with capture_logs() as logs:
        chunks = await _collect(service)

    assert chunks == [b"a", b"b"]
    assert backup.calls == []
    assert [e["provider"] for e in _events(logs, "tts.provider_selected")] == ["primary"]


async def test_failure_before_any_audio_falls_back_to_next_tier() -> None:
    primary = _FakeProvider([], error=_StatusError(402))
    backup = _FakeProvider([b"z"])
    service = _fallback(("primary", primary), ("backup", backup))

    with capture_logs() as logs:
        chunks = await _collect(service)

    assert chunks == [b"z"]
    assert backup.calls == ["hello"]
    failed = _events(logs, "tts.provider_failed")
    assert failed[0]["provider"] == "primary"
    assert failed[0]["billing_or_auth"] is True
    assert [e["provider"] for e in _events(logs, "tts.provider_selected")] == ["backup"]


async def test_non_billing_failure_is_logged_without_the_billing_flag() -> None:
    primary = _FakeProvider([], error=RuntimeError("network blip"))
    backup = _FakeProvider([b"z"])
    service = _fallback(("primary", primary), ("backup", backup))

    with capture_logs() as logs:
        await _collect(service)

    assert _events(logs, "tts.provider_failed")[0]["billing_or_auth"] is False


async def test_silent_failure_without_raising_still_falls_back() -> None:
    primary = _FakeProvider([])  # yields nothing, doesn't raise
    backup = _FakeProvider([b"z"])
    service = _fallback(("primary", primary), ("backup", backup))

    chunks = await _collect(service)

    assert chunks == [b"z"]
    assert backup.calls == ["hello"]


async def test_failure_partway_through_a_stream_is_not_retried_on_another_tier() -> None:
    """Once a tier starts speaking, a mid-stream failure ends the line there rather
    than switching to a different voice mid-sentence."""
    primary = _FakeProvider([b"a"], error=RuntimeError("dropped"))
    backup = _FakeProvider([b"z"])
    service = _fallback(("primary", primary), ("backup", backup))

    chunks = await _collect(service)

    assert chunks == [b"a"]
    assert backup.calls == []


async def test_all_tiers_failing_yields_nothing_and_never_raises() -> None:
    primary = _FakeProvider([], error=RuntimeError("down"))
    backup = _FakeProvider([], error=_StatusError(401))
    service = _fallback(("primary", primary), ("backup", backup))

    with capture_logs() as logs:
        chunks = await _collect(service)

    assert chunks == []
    assert _events(logs, "tts.all_providers_exhausted")


async def test_aclose_closes_every_tier() -> None:
    primary = _FakeProvider([])
    backup = _FakeProvider([])
    service = _fallback(("primary", primary), ("backup", backup))

    await service.aclose()

    assert primary.closed is True
    assert backup.closed is True


def test_requires_at_least_one_tier() -> None:
    with pytest.raises(ValueError):
        FallbackTTSService([])


def test_tier_names_reports_configured_providers_in_order() -> None:
    service = _fallback(("primary", _FakeProvider([])), ("backup", _FakeProvider([])))
    assert service.tier_names == ("primary", "backup")
