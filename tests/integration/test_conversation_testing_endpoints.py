"""Local conversation-testing endpoint integration tests.

Exercises ``POST /conversation/test/start`` and ``POST /conversation/test/message``
against the real FastAPI app — real state machine, real qualification service,
real scenario YAML — with only the OpenAI intent classifier swapped for a
deterministic fake via FastAPI's ``dependency_overrides``, so these tests never
make a real, billed network call and never depend on a configured
``OPENAI_API_KEY``. No Twilio, WebSocket, Deepgram, or ElevenLabs is touched by
these endpoints at all.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from app.config.dependencies import get_intent_normalizer
from app.main import app
from app.models.intent import Intent
from app.models.scenario import Question
from app.services.openai_service import IntentNormalizer
from fastapi.testclient import TestClient


class _FakeNormalizer(IntentNormalizer):
    """Deterministic yes/no/repeat mapping; anything else -> UNCLEAR."""

    _MAP = {"yes": Intent.YES, "no": Intent.NO, "repeat": Intent.REPEAT}

    async def normalize(self, transcript: str, question: Question) -> Intent:
        return self._MAP.get(transcript.strip().lower(), Intent.UNCLEAR)


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides[get_intent_normalizer] = lambda: _FakeNormalizer()
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_intent_normalizer, None)


def test_start_returns_greeting_and_first_question(client: TestClient) -> None:
    response = client.post("/conversation/test/start", json={"scenario_id": "lead_qualifier"})

    assert response.status_code == 201
    body = response.json()
    assert body["scenario_id"] == "lead_qualifier"
    assert body["state"] == "QUESTION_ONE"
    assert body["ended"] is False
    assert body["result"] is None
    assert len(body["messages"]) == 2  # greeting + first question
    assert body["conversation_id"]
    assert body["latency_ms"] is None  # no turn processed yet
    assert body["answers"] == {}
    assert body["summary"] is None
    assert [q["key"] for q in body["questions"]] == [
        "owns_home",
        "budget_over_10k",
        "start_within_3_months",
    ]


def test_start_defaults_to_server_default_scenario_when_omitted(client: TestClient) -> None:
    response = client.post("/conversation/test/start", json={})
    assert response.status_code == 201
    assert response.json()["scenario_id"] == "lead_qualifier"  # settings.default_scenario_id


def test_start_unknown_scenario_returns_404(client: TestClient) -> None:
    response = client.post("/conversation/test/start", json={"scenario_id": "not_a_real_bot"})
    assert response.status_code == 404
    assert "not_a_real_bot" in response.json()["detail"]


def test_full_conversation_reaches_qualified(client: TestClient) -> None:
    start = client.post("/conversation/test/start", json={"scenario_id": "lead_qualifier"})
    conversation_id = start.json()["conversation_id"]

    for _ in range(3):
        response = client.post(
            "/conversation/test/message",
            json={"conversation_id": conversation_id, "text": "yes"},
        )
        assert response.status_code == 200

    body = response.json()
    assert body["ended"] is True
    assert body["state"] == "ENDED"
    assert body["result"] == {
        "qualified": True,
        "label": "HOT_LEAD",
        "reason": "all gates answered YES",
    }
    assert body["messages"][-1]  # goodbye line present

    # Real per-turn latency, text-mode never touches stt/tts.
    assert body["latency_ms"]["stt_ms"] is None
    assert body["latency_ms"]["tts_ms"] is None
    assert isinstance(body["latency_ms"]["llm_ms"], float)
    assert isinstance(body["latency_ms"]["total_ms"], float)

    assert body["answers"] == {
        "owns_home": "YES",
        "budget_over_10k": "YES",
        "start_within_3_months": "YES",
    }
    assert body["summary"]["qualified"] is True
    assert body["summary"]["verdict"] == "HOT_LEAD"
    assert len(body["summary"]["highlights"]) == 3
    assert body["summary"]["recommendation"]

    # The conversation is discarded once ended.
    after_end = client.post(
        "/conversation/test/message",
        json={"conversation_id": conversation_id, "text": "yes"},
    )
    assert after_end.status_code == 404


def test_conversation_rejects_on_no(client: TestClient) -> None:
    start = client.post("/conversation/test/start", json={"scenario_id": "loan_qualifier"})
    conversation_id = start.json()["conversation_id"]

    response = client.post(
        "/conversation/test/message",
        json={"conversation_id": conversation_id, "text": "no"},
    )

    body = response.json()
    assert body["ended"] is True
    assert body["result"]["qualified"] is False
    assert body["result"]["label"] == "REJECTED"
    assert body["summary"]["qualified"] is False
    assert body["summary"]["highlights"] == ["Are you a salaried employee? → No"]
    assert "did not qualify" in body["summary"]["recommendation"]


def test_message_unknown_conversation_id_returns_404(client: TestClient) -> None:
    response = client.post(
        "/conversation/test/message",
        json={"conversation_id": "does-not-exist", "text": "yes"},
    )
    assert response.status_code == 404


def test_unclear_reply_reprompts_without_ending(client: TestClient) -> None:
    start = client.post("/conversation/test/start", json={"scenario_id": "lead_qualifier"})
    conversation_id = start.json()["conversation_id"]

    response = client.post(
        "/conversation/test/message",
        json={"conversation_id": conversation_id, "text": "maybe? not sure"},
    )

    body = response.json()
    assert body["ended"] is False
    assert body["state"] == "QUESTION_ONE"  # still on the same question


def test_openapi_documents_the_new_endpoints(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]

    assert "/conversation/test/start" in paths
    assert "/conversation/test/message" in paths

    start_op = paths["/conversation/test/start"]["post"]
    assert start_op["summary"]
    assert "ConversationTurnResponse" in start_op["responses"]["201"]["content"][
        "application/json"
    ]["schema"]["$ref"]

    schemas = schema["components"]["schemas"]
    assert "ConversationTurnResponse" in schemas
    assert "StartConversationRequest" in schemas
    assert "SubmitMessageRequest" in schemas
    # `state` reuses the real State enum, not a bare string, so OpenAPI lists
    # the exact allowed values.
    state_schema = schemas["ConversationTurnResponse"]["properties"]["state"]
    ref = state_schema.get("$ref") or state_schema.get("allOf", [{}])[0].get("$ref")
    assert ref and "State" in ref
