"""The dashboard observability snapshot.

A live phone call is driven by ``ConversationService.run()`` and streamed to
Twilio; nothing sits in the middle for a dashboard to watch. ``ConversationUpdate``
is that observation surface: one immutable, self-contained snapshot of everything
a dashboard needs to render the conversation *as it happens*, published after
every meaningful state transition.

Deliberately a **single canonical event type**, not a family of them. Every
snapshot carries the whole observable state (current line, state-machine node,
per-question progress, final verdict, latency, and the running transcript), so
a dashboard renders purely from the latest snapshot it received — no client-side
event-type dispatch, and a dashboard that connects mid-call catches up from one
message.

This module is pure data + a mapping factory. It holds no conversation logic:
the state machine still owns transitions and the qualification service still
owns the verdict; this only *reflects* what they already decided.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.intent import Intent
from app.models.scenario import Scenario
from app.models.session import CallSession, QualificationResult, TurnLatency
from app.state_machine.states import State

#: Who produced the line that this snapshot was emitted for.
Speaker = Literal["bot", "caller"]

#: Answer state of one qualification gate, mirrored to the dashboard checklist.
ProgressStatus = Literal["pending", "yes", "no"]


class TranscriptLine(BaseModel):
    """One utterance in the running transcript (bot line or caller answer)."""

    model_config = ConfigDict(frozen=True)

    speaker: Speaker
    message: str


class QualificationProgressItem(BaseModel):
    """One qualification gate and whether it has been answered yet."""

    model_config = ConfigDict(frozen=True)

    key: str
    prompt: str
    status: ProgressStatus


class ConversationUpdate(BaseModel):
    """An immutable snapshot of a live call's observable state at one instant.

    Frozen on purpose: a snapshot handed to the event bus must never change
    afterwards, even as ``run()`` keeps mutating its ``CallSession``.
    """

    model_config = ConfigDict(frozen=True)

    call_sid: str
    timestamp: datetime
    sequence: int = Field(description="Monotonic per-call index; lets a client order/dedupe.")
    speaker: Speaker
    message: str = Field(description="The line just spoken (bot) or heard (caller).")
    conversation_state: State
    qualification_progress: list[QualificationProgressItem]
    final_result: QualificationResult | None = Field(
        default=None, description="The verdict, present only once a decision has been reached."
    )
    latency: TurnLatency | None = Field(
        default=None, description="Latency of the most recently completed turn, if any."
    )
    transcript_so_far: list[TranscriptLine] | None = Field(
        default=None,
        description="Full running transcript, so a late-joining client renders from one snapshot.",
    )


def _progress(session: CallSession, scenario: Scenario) -> list[QualificationProgressItem]:
    """Map the session's recorded answers onto the scenario's gates, in order."""
    items: list[QualificationProgressItem] = []
    for question in scenario.questions:
        answer = session.answers.get(question.key)
        if answer == Intent.YES:
            status: ProgressStatus = "yes"
        elif answer == Intent.NO:
            status = "no"
        else:
            status = "pending"
        items.append(
            QualificationProgressItem(key=question.key, prompt=question.prompt, status=status)
        )
    return items


def build_conversation_update(
    *,
    session: CallSession,
    scenario: Scenario,
    speaker: Speaker,
    message: str,
    sequence: int,
    transcript: list[TranscriptLine],
) -> ConversationUpdate:
    """Snapshot the current observable state into an immutable ``ConversationUpdate``.

    Reads only already-computed state off ``session`` (state, answers, result,
    last-turn latency) — it makes no decisions of its own. ``transcript`` is
    copied so the returned snapshot is independent of the caller's list.

    Args:
        session: The in-flight call session (already mutated for this turn).
        scenario: The flow being run, for gate prompts/order.
        speaker: Who produced ``message``.
        message: The line this snapshot is being emitted for.
        sequence: Monotonic per-call snapshot index.
        transcript: The running transcript up to and including ``message``.

    Returns:
        A frozen snapshot safe to hand to the (transport-only) event bus.
    """
    return ConversationUpdate(
        call_sid=session.call_sid,
        timestamp=datetime.now(UTC),
        sequence=sequence,
        speaker=speaker,
        message=message,
        conversation_state=session.state,
        qualification_progress=_progress(session, scenario),
        final_result=session.result,
        latency=session.last_turn_latency,
        transcript_so_far=list(transcript),
    )
