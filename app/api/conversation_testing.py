"""Local conversation-testing endpoints.

``POST /conversation/test/start`` and ``POST /conversation/test/message`` let
the complete conversation engine — the real state machine, the real LLM
intent classifier, the real qualification service — be exercised over plain
HTTP text, with no Twilio account, no WebSocket client, no Deepgram, and no
ElevenLabs required. They reuse :class:`~app.services.conversation_service.
ConversationService` exactly as the (future) live-call path does; no
qualification or state-transition logic is duplicated here — this module is
just request/response plumbing around
``start_test_conversation``/``submit_test_message``.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config.dependencies import (
    ConversationServiceDep,
    ConversationStoreDep,
    ScenarioRegistryDep,
)
from app.models.intent import Intent
from app.models.scenario import Question, Scenario
from app.models.session import CallSession, QualificationResult, TurnLatency
from app.scenarios.registry import ScenarioNotFoundError
from app.state_machine.states import State

router = APIRouter(prefix="/conversation/test", tags=["conversation-testing"])


class StartConversationRequest(BaseModel):
    """Body for ``POST /conversation/test/start``."""

    scenario_id: str | None = Field(
        default=None,
        description=(
            "Scenario to run. Defaults to the server's configured default "
            "scenario if omitted."
        ),
        examples=["lead_qualifier"],
    )


class SubmitMessageRequest(BaseModel):
    """Body for ``POST /conversation/test/message``."""

    conversation_id: str = Field(description="The id returned by POST /conversation/test/start.")
    text: str = Field(
        description="Simulated caller utterance, as if it had been transcribed by STT.",
        examples=["yes"],
    )


class ConversationSummary(BaseModel):
    """A deterministic recap built from the real recorded answers and verdict.

    Not an LLM-generated narrative — every line here is composed directly from
    ``session.answers``/``session.result``, so it's exactly as trustworthy as
    the qualification decision itself, with nothing invented.
    """

    highlights: list[str] = Field(description="One line per answered question, in order.")
    verdict: str = Field(description="The scenario's outcome label, e.g. 'HOT_LEAD', 'REJECTED'.")
    qualified: bool
    recommendation: str = Field(description="Suggested next action, derived from the verdict.")


class ConversationTurnResponse(BaseModel):
    """Response shape shared by both endpoints — the conversation's state after this turn."""

    conversation_id: str = Field(
        description="Pass this back in every /message call for this conversation."
    )
    scenario_id: str
    state: State = Field(description="Current state-machine state.")
    messages: list[str] = Field(
        description="Line(s) the bot says in response to this turn, in order."
    )
    ended: bool = Field(
        description="True once ENDED is reached; no further /message calls will be accepted."
    )
    result: QualificationResult | None = Field(
        default=None,
        description="Set once a verdict is reached: qualified or not, the label, and why.",
    )
    latency_ms: TurnLatency | None = Field(
        default=None,
        description=(
            "Real per-turn latency (the same numbers already written to "
            "structured logs) — stt/tts are always null in text-mode, which "
            "never touches those ports."
        ),
    )
    answers: dict[str, Intent] = Field(
        default_factory=dict,
        description="Recorded answers so far, keyed by question id.",
    )
    questions: list[Question] = Field(
        default_factory=list,
        description="The scenario's questions in order (for a live checklist UI).",
    )
    summary: ConversationSummary | None = Field(
        default=None, description="Set once the conversation ends."
    )


def _new_conversation_id() -> str:
    return f"test_{uuid4().hex[:12]}"


def _build_summary(session: CallSession, scenario: Scenario) -> ConversationSummary | None:
    """Compose a plain-language recap from the real recorded answers and verdict."""
    if session.result is None:
        return None
    highlights: list[str] = []
    for question in scenario.questions:
        answer = session.answers.get(question.key)
        if answer is None:
            continue
        verb = {Intent.YES: "Yes", Intent.NO: "No"}.get(answer, answer.value.title())
        highlights.append(f"{question.prompt} → {verb}")
    recommendation = (
        "Transfer to a sales agent."
        if session.result.qualified
        else "No further action — caller did not qualify."
    )
    return ConversationSummary(
        highlights=highlights,
        verdict=session.result.label,
        qualified=session.result.qualified,
        recommendation=recommendation,
    )


def _to_response(
    conversation_id: str, scenario: Scenario, session: CallSession, messages: list[str], ended: bool
) -> ConversationTurnResponse:
    """Build the shared response shape from a session + scenario, once per turn."""
    return ConversationTurnResponse(
        conversation_id=conversation_id,
        scenario_id=scenario.id,
        state=session.state,
        messages=messages,
        ended=ended,
        result=session.result,
        latency_ms=session.last_turn_latency,
        answers=dict(session.answers),
        questions=list(scenario.questions),
        summary=_build_summary(session, scenario) if ended else None,
    )


@router.post(
    "/start",
    response_model=ConversationTurnResponse,
    status_code=201,
    summary="Start a local test conversation",
    description=(
        "Creates a new conversation session for the given scenario and returns "
        "the opening line(s) — the greeting and the first question — without "
        "touching Twilio, WebSockets, Deepgram, or ElevenLabs."
    ),
)
async def start_conversation(
    request: StartConversationRequest,
    conversation: ConversationServiceDep,
    scenarios: ScenarioRegistryDep,
    store: ConversationStoreDep,
) -> ConversationTurnResponse:
    """Start a new local test conversation and return its opening line(s)."""
    scenario_id = request.scenario_id or scenarios.ids()[0]
    try:
        scenario = scenarios.get(scenario_id)
    except ScenarioNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown scenario_id {scenario_id!r}. Available: {', '.join(scenarios.ids())}",
        ) from None

    conversation_id = _new_conversation_id()
    session = CallSession(call_sid=conversation_id, scenario_id=scenario.id)
    machine, messages = await conversation.start_test_conversation(session, scenario)
    store.create(conversation_id, session, scenario, machine)

    return _to_response(conversation_id, scenario, session, messages, ended=False)


@router.post(
    "/message",
    response_model=ConversationTurnResponse,
    summary="Submit a message to a local test conversation",
    description=(
        "Sends one simulated caller utterance to an in-progress test "
        "conversation (started via POST /conversation/test/start) and returns "
        "the bot's next line(s). The real LLM classifier and state machine "
        "decide the outcome exactly as they would on a live call."
    ),
)
async def submit_message(
    request: SubmitMessageRequest,
    conversation: ConversationServiceDep,
    store: ConversationStoreDep,
) -> ConversationTurnResponse:
    """Advance an in-progress local test conversation by one turn."""
    entry = store.get(request.conversation_id)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No in-progress conversation with id {request.conversation_id!r} "
                "(it may not exist, or has already ended)."
            ),
        )

    messages, ended = await conversation.submit_test_message(
        entry.session, entry.scenario, entry.machine, request.text
    )
    response = _to_response(
        request.conversation_id, entry.scenario, entry.session, messages, ended
    )
    if ended:
        store.discard(request.conversation_id)
    return response
