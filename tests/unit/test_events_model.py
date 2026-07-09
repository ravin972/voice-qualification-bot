"""ConversationUpdate snapshot-model tests.

The snapshot is a pure projection of already-decided session state. These tests
pin that projection (per-gate progress, verdict/latency passthrough) and the
two properties the event bus relies on: the snapshot is frozen, and it owns an
independent copy of the transcript so later mutation can't rewrite history.
"""

from __future__ import annotations

import pytest
from app.models.events import (
    ConversationUpdate,
    TranscriptLine,
    build_conversation_update,
)
from app.models.intent import Intent
from app.models.scenario import Scenario
from app.models.session import CallSession, QualificationResult, TurnLatency
from app.state_machine.states import State
from pydantic import ValidationError


def _session(
    *,
    state: State = State.START,
    answers: dict[str, Intent] | None = None,
    result: QualificationResult | None = None,
    last_turn_latency: TurnLatency | None = None,
) -> CallSession:
    return CallSession(
        call_sid="CA_test",
        scenario_id="test",
        state=state,
        answers=answers or {},
        result=result,
        last_turn_latency=last_turn_latency,
    )


def test_progress_reflects_recorded_answers_gate_by_gate(sample_scenario: Scenario) -> None:
    session = _session(
        state=State.QUESTION_THREE,
        answers={"q1": Intent.YES, "q2": Intent.NO},  # q3 unanswered
    )

    update = build_conversation_update(
        session=session,
        scenario=sample_scenario,
        speaker="caller",
        message="no",
        sequence=5,
        transcript=[TranscriptLine(speaker="caller", message="no")],
    )

    assert [(p.key, p.status) for p in update.qualification_progress] == [
        ("q1", "yes"),
        ("q2", "no"),
        ("q3", "pending"),
    ]
    assert update.conversation_state is State.QUESTION_THREE
    assert update.sequence == 5
    assert update.speaker == "caller"
    assert update.message == "no"


def test_result_and_latency_pass_through_from_the_session(sample_scenario: Scenario) -> None:
    session = _session(
        state=State.QUALIFIED,
        answers={"q1": Intent.YES, "q2": Intent.YES, "q3": Intent.YES},
        result=QualificationResult(qualified=True, label="HOT_LEAD", reason="all gates YES"),
        last_turn_latency=TurnLatency(stt_ms=120.0, llm_ms=40.0, tts_ms=300.0, total_ms=500.0),
    )

    update = build_conversation_update(
        session=session,
        scenario=sample_scenario,
        speaker="bot",
        message="You qualify.",
        sequence=9,
        transcript=[],
    )

    assert update.final_result is not None
    assert update.final_result.qualified is True
    assert update.final_result.label == "HOT_LEAD"
    assert update.latency is not None
    assert update.latency.total_ms == 500.0
    assert all(p.status == "yes" for p in update.qualification_progress)


def test_no_answers_yet_is_all_pending_with_no_result(sample_scenario: Scenario) -> None:
    update = build_conversation_update(
        session=_session(),
        scenario=sample_scenario,
        speaker="bot",
        message=sample_scenario.script.greeting,
        sequence=1,
        transcript=[TranscriptLine(speaker="bot", message=sample_scenario.script.greeting)],
    )
    assert all(p.status == "pending" for p in update.qualification_progress)
    assert update.final_result is None
    assert update.latency is None


def test_snapshot_owns_an_independent_transcript_copy(sample_scenario: Scenario) -> None:
    transcript = [TranscriptLine(speaker="bot", message="hi")]
    update = build_conversation_update(
        session=_session(),
        scenario=sample_scenario,
        speaker="bot",
        message="hi",
        sequence=1,
        transcript=transcript,
    )
    transcript.append(TranscriptLine(speaker="caller", message="later"))
    assert update.transcript_so_far == [TranscriptLine(speaker="bot", message="hi")]


def test_snapshot_is_frozen(sample_scenario: Scenario) -> None:
    update = build_conversation_update(
        session=_session(),
        scenario=sample_scenario,
        speaker="bot",
        message="hi",
        sequence=1,
        transcript=[],
    )
    with pytest.raises(ValidationError):
        update.message = "tampered"  # type: ignore[misc]


def test_snapshot_serialises_enum_state_to_its_string_value(sample_scenario: Scenario) -> None:
    update = build_conversation_update(
        session=_session(state=State.QUESTION_ONE),
        scenario=sample_scenario,
        speaker="bot",
        message="Question one?",
        sequence=2,
        transcript=[],
    )
    payload = update.model_dump(mode="json")
    assert payload["conversation_state"] == "QUESTION_ONE"
    # Round-trips back into the model unchanged.
    assert ConversationUpdate.model_validate(payload).conversation_state is State.QUESTION_ONE
