"""ConversationService orchestration tests.

Fakes exist only at the true I/O boundaries (STT, TTS, LLM normaliser,
telephony); the state machine and qualification service are the *real*
implementations, so these tests exercise genuine FSM transitions and genuine
qualification rules driven by scripted vendor I/O — no network, no ASGI app.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from app.config.settings import Settings
from app.models.audio import AudioChunk, Transcript
from app.models.intent import Intent
from app.models.scenario import Question, Scenario
from app.models.session import CallSession
from app.services.conversation_service import ConversationService, StateMachineFactory
from app.services.logger import get_logger
from app.services.openai_service import IntentNormalizer
from app.services.qualification_service import QualificationService
from app.services.stt_service import SpeechToTextService
from app.services.tts_service import TextToSpeechService
from app.services.twilio_service import TelephonyService
from app.state_machine.machine import ConversationStateMachine
from app.state_machine.states import State
from structlog.testing import capture_logs
from structlog.typing import EventDict


class FakeSTT(SpeechToTextService):
    """Ignores the inbound audio entirely; yields pre-scripted final transcripts."""

    def __init__(self, texts: list[str]) -> None:
        self._texts = texts

    async def stream(self, audio: AsyncIterator[AudioChunk]) -> AsyncIterator[Transcript]:
        for text in self._texts:
            yield Transcript(text=text, is_final=True)

    async def aclose(self) -> None:
        pass


class FakeNormalizer(IntentNormalizer):
    """Maps transcript text to a pre-declared intent; unknown text -> UNCLEAR."""

    def __init__(self, mapping: dict[str, Intent]) -> None:
        self._mapping = mapping

    async def normalize(self, transcript: str, question: Question) -> Intent:
        return self._mapping.get(transcript, Intent.UNCLEAR)


class FakeTTS(TextToSpeechService):
    """Records every line spoken; yields one trivial chunk per call."""

    def __init__(self) -> None:
        self.spoken: list[str] = []

    async def synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        self.spoken.append(text)
        yield AudioChunk(payload=f"chunk:{text}".encode())

    async def aclose(self) -> None:
        pass


class FakeTelephony(TelephonyService):
    """Records transfer attempts instead of calling real Twilio."""

    def __init__(self) -> None:
        self.transfers: list[tuple[str, str]] = []

    def build_stream_twiml(self, *, websocket_url: str, scenario_id: str) -> str:
        return "<Response/>"

    async def transfer_to_agent(self, call_sid: str, agent_number: str) -> None:
        self.transfers.append((call_sid, agent_number))


async def _empty_audio_in() -> AsyncIterator[AudioChunk]:
    return
    yield  # pragma: no cover  (makes this an async generator)


def _machine_factory(max_reprompts: int) -> StateMachineFactory:
    def factory(scenario: Scenario) -> ConversationStateMachine:
        return ConversationStateMachine(scenario, max_reprompts=max_reprompts)

    return factory


def _service(
    *,
    texts: list[str],
    mapping: dict[str, Intent] | None = None,
    max_reprompts: int = 2,
    telephony: TelephonyService | None = None,
    agent_transfer_number: str | None = None,
) -> tuple[ConversationService, FakeTTS]:
    tts = FakeTTS()
    stt = FakeSTT(texts)
    normalizer = FakeNormalizer(mapping or {"yes": Intent.YES, "no": Intent.NO})
    settings = Settings(agent_transfer_number=agent_transfer_number)
    service = ConversationService(
        stt=stt,
        normalizer=normalizer,
        tts=tts,
        qualification=QualificationService(),
        machine_factory=_machine_factory(max_reprompts),
        settings=settings,
        logger=get_logger("test.conversation_service"),
        telephony=telephony,
    )
    return service, tts


async def _drive(
    service: ConversationService, scenario: Scenario
) -> tuple[CallSession, list[AudioChunk]]:
    session = CallSession(call_sid="CA_test", scenario_id=scenario.id)
    sent: list[AudioChunk] = []

    async def audio_out(chunk: AudioChunk) -> None:
        sent.append(chunk)

    result = await service.run(session, scenario, _empty_audio_in(), audio_out)
    return result, sent


# --- Happy path --------------------------------------------------------------
async def test_all_yes_qualifies_and_speaks_the_full_script(sample_scenario: Scenario) -> None:
    service, tts = _service(texts=["yes", "yes", "yes"])
    session, sent = await _drive(service, sample_scenario)

    assert session.result is not None
    assert session.result.qualified is True
    assert session.result.label == sample_scenario.qualified_label
    assert session.state is State.ENDED
    assert session.answers == {q.key: Intent.YES for q in sample_scenario.questions}
    assert len(session.turns) == 3

    expected_lines = [
        sample_scenario.script.greeting,
        sample_scenario.questions[0].prompt,
        sample_scenario.questions[1].prompt,
        sample_scenario.questions[2].prompt,
        sample_scenario.script.qualified,
        sample_scenario.script.goodbye,
    ]
    assert tts.spoken == expected_lines
    assert len(sent) == len(expected_lines)  # one chunk per synthesize() call


# --- Disqualification: stops early, never asks remaining questions ----------
async def test_no_rejects_immediately_and_skips_remaining_questions(
    sample_scenario: Scenario,
) -> None:
    service, tts = _service(texts=["yes", "no"])
    session, _sent = await _drive(service, sample_scenario)

    assert session.result is not None
    assert session.result.qualified is False
    assert session.result.label == sample_scenario.rejected_label
    assert session.state is State.ENDED

    assert sample_scenario.questions[2].prompt not in tts.spoken  # q3 never asked
    assert tts.spoken[-2:] == [sample_scenario.script.rejected, sample_scenario.script.goodbye]


# --- Reprompt handling --------------------------------------------------------
async def test_unclear_reprompts_then_recovers(sample_scenario: Scenario) -> None:
    service, tts = _service(texts=["mumble", "yes", "yes", "yes"], max_reprompts=1)
    session, _sent = await _drive(service, sample_scenario)

    assert tts.spoken.count(sample_scenario.script.reprompt_unclear) == 1
    assert session.result is not None
    assert session.result.qualified is True
    # The eventual YES is what's recorded, not the earlier UNCLEAR.
    assert session.answers[sample_scenario.questions[0].key] is Intent.YES
    assert session.turns[0].reprompts == 1


async def test_unclear_escalates_to_rejected_when_budget_exhausted(
    sample_scenario: Scenario,
) -> None:
    service, tts = _service(texts=["mumble"], max_reprompts=0)
    session, _sent = await _drive(service, sample_scenario)

    assert session.result is not None
    assert session.result.qualified is False
    assert "incomplete" in session.result.reason
    assert sample_scenario.questions[0].key not in session.answers
    assert tts.spoken[-2:] == [sample_scenario.script.rejected, sample_scenario.script.goodbye]


# --- Agent transfer ------------------------------------------------------------
async def test_qualified_triggers_agent_transfer_when_configured(
    sample_scenario: Scenario,
) -> None:
    telephony = FakeTelephony()
    service, _tts = _service(
        texts=["yes", "yes", "yes"],
        telephony=telephony,
        agent_transfer_number="+15550001111",
    )
    session, _sent = await _drive(service, sample_scenario)

    assert telephony.transfers == [(session.call_sid, "+15550001111")]


async def test_qualified_skips_transfer_when_telephony_not_configured(
    sample_scenario: Scenario,
) -> None:
    service, _tts = _service(
        texts=["yes", "yes", "yes"], telephony=None, agent_transfer_number="+15550001111"
    )
    session, _sent = await _drive(service, sample_scenario)  # must not raise
    assert session.result is not None
    assert session.result.qualified is True


async def test_qualified_skips_transfer_when_number_not_configured(
    sample_scenario: Scenario,
) -> None:
    telephony = FakeTelephony()
    service, _tts = _service(
        texts=["yes", "yes", "yes"], telephony=telephony, agent_transfer_number=None
    )
    await _drive(service, sample_scenario)
    assert telephony.transfers == []


async def test_rejected_never_triggers_transfer(sample_scenario: Scenario) -> None:
    telephony = FakeTelephony()
    service, _tts = _service(
        texts=["no"], telephony=telephony, agent_transfer_number="+15550001111"
    )
    await _drive(service, sample_scenario)
    assert telephony.transfers == []


# --- Graceful hangup -----------------------------------------------------------
async def test_caller_hangup_mid_call_ends_gracefully(sample_scenario: Scenario) -> None:
    """Audio simply stops (caller hangs up) before any decision is reached."""
    service, tts = _service(texts=["yes"])  # only answers question 1, then stream ends
    session, _sent = await _drive(service, sample_scenario)

    assert session.result is None
    assert session.state is State.ENDED
    assert tts.spoken[-1] == sample_scenario.script.goodbye


# --- Local test-mode: same decision core, plain text instead of audio --------
async def test_start_test_conversation_returns_greeting_and_first_question(
    sample_scenario: Scenario,
) -> None:
    service, tts = _service(texts=[])
    session = CallSession(call_sid="CA_text", scenario_id=sample_scenario.id)

    machine, lines = await service.start_test_conversation(session, sample_scenario)

    assert lines == [sample_scenario.script.greeting, sample_scenario.questions[0].prompt]
    assert machine.current_state is State.QUESTION_ONE
    assert session.state is State.QUESTION_ONE
    assert session.current_question_index == 0
    assert tts.spoken == []  # test mode never touches TTS


async def test_submit_test_message_all_yes_qualifies(sample_scenario: Scenario) -> None:
    service, tts = _service(texts=[])
    session = CallSession(call_sid="CA_text", scenario_id=sample_scenario.id)
    machine, _opening = await service.start_test_conversation(session, sample_scenario)

    lines1, ended1 = await service.submit_test_message(session, sample_scenario, machine, "yes")
    assert lines1 == [sample_scenario.questions[1].prompt]
    assert ended1 is False

    lines2, ended2 = await service.submit_test_message(session, sample_scenario, machine, "yes")
    assert lines2 == [sample_scenario.questions[2].prompt]
    assert ended2 is False

    lines3, ended3 = await service.submit_test_message(session, sample_scenario, machine, "yes")
    assert ended3 is True
    assert lines3 == [sample_scenario.script.qualified, sample_scenario.script.goodbye]

    assert session.result is not None
    assert session.result.qualified is True
    assert session.result.label == sample_scenario.qualified_label
    assert session.state is State.ENDED
    assert tts.spoken == []  # test mode never touches TTS, even on the outcome turn


async def test_submit_test_message_no_rejects_immediately(sample_scenario: Scenario) -> None:
    service, _tts = _service(texts=[])
    session = CallSession(call_sid="CA_text", scenario_id=sample_scenario.id)
    machine, _opening = await service.start_test_conversation(session, sample_scenario)

    lines, ended = await service.submit_test_message(session, sample_scenario, machine, "no")

    assert ended is True
    assert lines == [sample_scenario.script.rejected, sample_scenario.script.goodbye]
    assert session.result is not None
    assert session.result.qualified is False


async def test_submit_test_message_unclear_then_recovers(sample_scenario: Scenario) -> None:
    service, _tts = _service(texts=[], max_reprompts=1)
    session = CallSession(call_sid="CA_text", scenario_id=sample_scenario.id)
    machine, _opening = await service.start_test_conversation(session, sample_scenario)

    lines1, ended1 = await service.submit_test_message(session, sample_scenario, machine, "mumble")
    assert ended1 is False
    assert lines1 == [sample_scenario.script.reprompt_unclear]

    lines2, ended2 = await service.submit_test_message(session, sample_scenario, machine, "yes")
    assert ended2 is False
    assert lines2 == [sample_scenario.questions[1].prompt]


# --- Latency logging -----------------------------------------------------------
def _latency_events(logs: list[EventDict]) -> list[EventDict]:
    return [entry for entry in logs if entry.get("event") == "conversation.latency"]


async def test_run_logs_stt_llm_tts_and_turn_total_latency(sample_scenario: Scenario) -> None:
    service, _tts = _service(texts=["yes", "yes", "yes"])

    with capture_logs() as logs:
        session, _sent = await _drive(service, sample_scenario)

    events = _latency_events(logs)
    stages = [e["stage"] for e in events]
    # 3 turns * (stt, llm, tts) + 3 turn_totals + 5 tts calls for greeting/Q1..Q3/goodbye
    # (exact TTS count depends on script length; assert presence, not exact count).
    assert stages.count("stt") == 3
    assert stages.count("llm") == 3
    assert stages.count("turn_total") == 3
    assert "tts" in stages

    for event in events:
        assert event["conversation_id"] == session.call_sid
        assert event["call_sid"] == session.call_sid
        assert isinstance(event["latency_ms"], float)
        assert event["latency_ms"] >= 0


async def test_submit_test_message_logs_llm_and_turn_total_but_never_stt_or_tts(
    sample_scenario: Scenario,
) -> None:
    service, _tts = _service(texts=[])
    session = CallSession(call_sid="CA_text", scenario_id=sample_scenario.id)
    machine, _opening = await service.start_test_conversation(session, sample_scenario)

    with capture_logs() as logs:
        await service.submit_test_message(session, sample_scenario, machine, "yes")

    stages = [e["stage"] for e in _latency_events(logs)]
    assert "llm" in stages
    assert "turn_total" in stages
    assert "stt" not in stages  # test mode never touches STT
    assert "tts" not in stages  # test mode never touches TTS
