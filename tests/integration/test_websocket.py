"""WebSocket transport integration tests.

Drives the real ``/media-stream`` endpoint (routing, DI, ``MediaStreamHandler``,
and the conversation bridge) through the Twilio Media Streams wire protocol via
``TestClient``. STT, TTS, and the OpenAI intent classifier are always swapped
for deterministic fakes via FastAPI's ``dependency_overrides`` (the same
pattern the local conversation-testing endpoint tests use), so these tests
never make a real, billed network call and never depend on configured vendor
credentials.
"""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator, Iterator

import pytest
from app.config.dependencies import get_intent_normalizer, get_stt_service, get_tts_service
from app.main import app
from app.models.audio import AudioChunk, AudioEncoding, Transcript
from app.models.intent import Intent
from app.models.scenario import Question
from app.services.openai_service import IntentNormalizer
from app.services.stt_service import SpeechToTextService
from app.services.tts_service import TextToSpeechService
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession
from starlette.websockets import WebSocketDisconnect


class _SilentSTT(SpeechToTextService):
    """Drains inbound audio without ever emitting a transcript."""

    async def stream(self, audio: AsyncIterator[AudioChunk]) -> AsyncIterator[Transcript]:
        async for _chunk in audio:
            continue
        return
        yield  # pragma: no cover  (keeps this an async generator for typing)

    async def aclose(self) -> None:
        pass


class _SilentTTS(TextToSpeechService):
    """Synthesises nothing, so transport-only tests see no outbound audio frames."""

    async def synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        return
        yield  # pragma: no cover

    async def aclose(self) -> None:
        pass


class _OneShotSTT(SpeechToTextService):
    """Emits one fixed final transcript after the first inbound chunk, then drains silently."""

    def __init__(self, text: str) -> None:
        self._text = text

    async def stream(self, audio: AsyncIterator[AudioChunk]) -> AsyncIterator[Transcript]:
        emitted = False
        async for _chunk in audio:
            if not emitted:
                emitted = True
                yield Transcript(text=self._text, is_final=True)

    async def aclose(self) -> None:
        pass


class _EchoTTS(TextToSpeechService):
    """Encodes the spoken line itself as the "audio" payload.

    Lets a test verify exactly which line the bridge sent by base64-decoding
    the outbound frame, without needing real synthesised audio.
    """

    async def synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        yield AudioChunk(payload=text.encode("utf-8"), encoding=AudioEncoding.MULAW_8000)

    async def aclose(self) -> None:
        pass


class _FakeNormalizer(IntentNormalizer):
    """Deterministic yes/no mapping; anything else -> UNCLEAR."""

    _MAP = {"yes": Intent.YES, "no": Intent.NO}

    async def normalize(self, transcript: str, question: Question) -> Intent:
        return self._MAP.get(transcript.strip().lower(), Intent.UNCLEAR)


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A client whose conversation bridge runs but never speaks (transport-only tests)."""
    app.dependency_overrides[get_stt_service] = lambda: _SilentSTT()
    app.dependency_overrides[get_tts_service] = lambda: _SilentTTS()
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_stt_service, None)
        app.dependency_overrides.pop(get_tts_service, None)


@pytest.fixture
def spoken_turn_client() -> Iterator[TestClient]:
    """A client whose fakes actually speak, to verify the audio bridge end-to-end."""
    app.dependency_overrides[get_stt_service] = lambda: _OneShotSTT("yes")
    app.dependency_overrides[get_tts_service] = lambda: _EchoTTS()
    app.dependency_overrides[get_intent_normalizer] = lambda: _FakeNormalizer()
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_stt_service, None)
        app.dependency_overrides.pop(get_tts_service, None)
        app.dependency_overrides.pop(get_intent_normalizer, None)


def _start_frame(scenario: str = "lead_qualifier") -> str:
    return json.dumps(
        {
            "event": "start",
            "sequenceNumber": "1",
            "streamSid": "MZ_test",
            "start": {
                "streamSid": "MZ_test",
                "callSid": "CA_test",
                "tracks": ["inbound"],
                "customParameters": {"scenario": scenario},
                "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
            },
        }
    )


def _media_frame(payload: bytes = b"caller-audio") -> str:
    return json.dumps(
        {
            "event": "media",
            "streamSid": "MZ_test",
            "media": {
                "track": "inbound",
                "chunk": "1",
                "timestamp": "5",
                "payload": base64.b64encode(payload).decode("ascii"),
            },
        }
    )


def _receive_spoken_line(ws: WebSocketTestSession) -> str:
    """Receive one outbound frame and decode it back to the line the bot spoke."""
    frame = json.loads(ws.receive_text())
    assert frame["event"] == "media"
    return base64.b64decode(frame["media"]["payload"]).decode("utf-8")


def test_full_media_stream_lifecycle_closes_cleanly(client: TestClient) -> None:
    """connected -> start -> media -> stop, then the server closes the socket."""
    with client.websocket_connect("/media-stream") as ws:
        ws.send_text(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        ws.send_text(_start_frame())
        ws.send_text(
            json.dumps(
                {
                    "event": "media",
                    "streamSid": "MZ_test",
                    "media": {
                        "track": "inbound",
                        "chunk": "1",
                        "timestamp": "5",
                        "payload": "AAAA",
                    },
                }
            )
        )
        ws.send_text(
            json.dumps({"event": "stop", "streamSid": "MZ_test", "stop": {"callSid": "CA_test"}})
        )

        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()


def test_malformed_frame_is_skipped_without_dropping_the_connection(
    client: TestClient,
) -> None:
    """An unparseable frame is logged and ignored; the socket stays usable."""
    with client.websocket_connect("/media-stream") as ws:
        ws.send_text("not valid json at all")
        ws.send_text(_start_frame())
        ws.send_text(json.dumps({"event": "stop", "streamSid": "MZ_test", "stop": {}}))

        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()


def test_disconnect_without_stop_frame_does_not_raise(client: TestClient) -> None:
    """A caller hanging up mid-call (no 'stop' frame) is handled gracefully."""
    with client.websocket_connect("/media-stream") as ws:
        ws.send_text(_start_frame())
        # Exiting the `with` block closes the socket from the client side,
        # simulating an abrupt hangup; the handler must not raise.


def test_conversation_bridge_drives_one_spoken_turn(spoken_turn_client: TestClient) -> None:
    """One full turn — greeting, question, a spoken "yes", the next question, and the
    eventual goodbye — flows through decode -> queue -> STT -> normalize -> the real
    state machine -> TTS -> encode, exactly as a live call would.
    """
    with spoken_turn_client.websocket_connect("/media-stream") as ws:
        ws.send_text(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        ws.send_text(_start_frame())

        greeting = _receive_spoken_line(ws)
        question_one = _receive_spoken_line(ws)
        assert "renovation" in greeting.lower()
        assert "own your home" in question_one.lower()

        # The caller's (fake) spoken "yes" answers question one.
        ws.send_text(_media_frame())

        question_two = _receive_spoken_line(ws)
        assert "budget" in question_two.lower()

        ws.send_text(
            json.dumps({"event": "stop", "streamSid": "MZ_test", "stop": {"callSid": "CA_test"}})
        )

        goodbye = _receive_spoken_line(ws)
        assert "goodbye" in goodbye.lower()

        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()


def test_unknown_scenario_is_logged_and_ignored_without_dropping_the_connection(
    client: TestClient,
) -> None:
    """An unrecognised scenario id skips the conversation bridge but keeps the socket alive."""
    with client.websocket_connect("/media-stream") as ws:
        ws.send_text(_start_frame(scenario="not_a_real_bot"))
        ws.send_text(
            json.dumps({"event": "stop", "streamSid": "MZ_test", "stop": {"callSid": "CA_test"}})
        )

        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()
