"""Dashboard live-stream integration test.

Drives a real media-stream call through the actual app (real state machine, real
qualification service, fakes only at the STT/TTS/LLM boundaries) while a second
client watches ``/dashboard/stream``, and asserts the call's snapshots arrive
live over that socket, in order, all the way to the final verdict. This is the
end-to-end proof of the observability path

    ConversationService.run()  ->  EventBus  ->  /dashboard/stream

The event bus is overridden with a fresh instance per test so the process-wide
singleton's replay buffer can't leak state across tests; because both the
conversation service and the dashboard route depend on ``get_event_bus``, the
one override is shared by producer and consumer alike.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from app.config.dependencies import (
    get_event_bus,
    get_intent_normalizer,
    get_stt_service,
    get_tts_service,
)
from app.main import app
from app.models.audio import AudioChunk, Transcript
from app.models.events import ConversationUpdate
from app.models.intent import Intent
from app.models.scenario import Question
from app.services.event_bus import InMemoryEventBus
from app.services.openai_service import IntentNormalizer
from app.services.stt_service import SpeechToTextService
from app.services.tts_service import TextToSpeechService
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession


class _ScriptedSTT(SpeechToTextService):
    """Yields a fixed list of final transcripts, ignoring the inbound audio."""

    def __init__(self, texts: list[str]) -> None:
        self._texts = texts

    async def stream(self, audio: AsyncIterator[AudioChunk]) -> AsyncIterator[Transcript]:
        for text in self._texts:
            yield Transcript(text=text, is_final=True)

    async def aclose(self) -> None:
        pass


class _SilentTTS(TextToSpeechService):
    """Produces no audio — this test watches the dashboard, not the Twilio wire."""

    async def synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        return
        yield  # pragma: no cover  (keeps this an async generator for typing)

    async def aclose(self) -> None:
        pass


class _FakeNormalizer(IntentNormalizer):
    _MAP = {"yes": Intent.YES, "no": Intent.NO}

    async def normalize(self, transcript: str, question: Question) -> Intent:
        return self._MAP.get(transcript.strip().lower(), Intent.UNCLEAR)


@pytest.fixture
def event_bus() -> InMemoryEventBus[ConversationUpdate]:
    return InMemoryEventBus()


@pytest.fixture
def client(event_bus: InMemoryEventBus[ConversationUpdate]) -> Iterator[TestClient]:
    app.dependency_overrides[get_stt_service] = lambda: _ScriptedSTT(["yes", "yes", "yes"])
    app.dependency_overrides[get_tts_service] = lambda: _SilentTTS()
    app.dependency_overrides[get_intent_normalizer] = lambda: _FakeNormalizer()
    app.dependency_overrides[get_event_bus] = lambda: event_bus
    try:
        with TestClient(app) as c:
            yield c
    finally:
        for dependency in (get_stt_service, get_tts_service, get_intent_normalizer, get_event_bus):
            app.dependency_overrides.pop(dependency, None)


def _start_frame(scenario: str = "lead_qualifier") -> str:
    return json.dumps(
        {
            "event": "start",
            "sequenceNumber": "1",
            "streamSid": "MZ_dash",
            "start": {
                "streamSid": "MZ_dash",
                "callSid": "CA_dash",
                "tracks": ["inbound"],
                "customParameters": {"scenario": scenario},
                "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
            },
        }
    )


def _drain_until_ended(
    dashboard: WebSocketTestSession, *, limit: int = 50
) -> list[dict[str, Any]]:
    """Collect snapshots from the dashboard socket until the call reaches ENDED."""
    updates: list[dict[str, Any]] = []
    for _ in range(limit):
        update = dashboard.receive_json()
        updates.append(update)
        if update["conversation_state"] == "ENDED":
            return updates
    raise AssertionError("dashboard stream did not reach ENDED within the frame limit")


def test_live_call_snapshots_stream_to_the_dashboard(client: TestClient) -> None:
    with client.websocket_connect("/dashboard/stream") as dashboard:
        # A real call runs on the media socket; the dashboard is a separate client.
        with client.websocket_connect("/media-stream") as media:
            media.send_text(
                json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"})
            )
            media.send_text(_start_frame())

            updates = _drain_until_ended(dashboard)

            media.send_text(
                json.dumps(
                    {"event": "stop", "streamSid": "MZ_dash", "stop": {"callSid": "CA_dash"}}
                )
            )

    # Every snapshot is for this call, and sequence numbers strictly increase.
    assert all(u["call_sid"] == "CA_dash" for u in updates)
    sequences = [u["sequence"] for u in updates]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)  # no duplicates

    # The stream opens with the bot's greeting and ends after the goodbye.
    assert updates[0]["speaker"] == "bot"
    assert "renovation" in str(updates[0]["message"]).lower()
    assert updates[-1]["conversation_state"] == "ENDED"

    # The caller's three spoken "yes" answers each surfaced live.
    caller_lines = [u["message"] for u in updates if u["speaker"] == "caller"]
    assert caller_lines == ["yes", "yes", "yes"]

    # The qualifying verdict was observed, carried on a snapshot mid-stream.
    decided = [u for u in updates if u["final_result"] is not None]
    assert decided, "expected at least one snapshot carrying the final result"
    verdict = decided[-1]["final_result"]
    assert isinstance(verdict, dict)
    assert verdict["qualified"] is True
    assert verdict["label"] == "HOT_LEAD"

    # The final snapshot's running transcript is the whole conversation.
    final_transcript = updates[-1]["transcript_so_far"]
    assert isinstance(final_transcript, list)
    assert [line["speaker"] for line in final_transcript].count("caller") == 3


def test_dashboard_stream_replays_recent_snapshots_to_a_late_subscriber(
    client: TestClient,
) -> None:
    # Run a whole call with no dashboard attached...
    with client.websocket_connect("/media-stream") as media:
        media.send_text(_start_frame())
        media.send_text(
            json.dumps({"event": "stop", "streamSid": "MZ_dash", "stop": {"callSid": "CA_dash"}})
        )

    # ...then connect: the replay buffer still catches the late dashboard up to
    # the finished call rather than showing nothing.
    with client.websocket_connect("/dashboard/stream") as dashboard:
        replayed = _drain_until_ended(dashboard)

    assert replayed[0]["speaker"] == "bot"
    assert replayed[-1]["conversation_state"] == "ENDED"
    assert any(u["final_result"] is not None for u in replayed)
