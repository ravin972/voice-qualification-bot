"""Per-call session state and the qualification outcome.

``CallSession`` is the single mutable object that travels through the
conversation for the lifetime of one phone call. It records what was asked,
what was heard, and where in the flow we are. It holds *data only*; the state
machine mutates ``state`` and the qualification service reads ``answers`` to
produce a ``QualificationResult``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from app.models.audio import Transcript
from app.models.intent import Intent
from app.state_machine.states import State


def _utcnow() -> datetime:
    """Timezone-aware current UTC timestamp (testable seam)."""
    return datetime.now(UTC)


class Turn(BaseModel):
    """One question/answer exchange, retained for audit and observability."""

    question_key: str
    transcript: Transcript | None = None
    intent: Intent | None = None
    reprompts: int = 0
    created_at: datetime = Field(default_factory=_utcnow)


class QualificationResult(BaseModel):
    """The final, Python-decided verdict for a call."""

    qualified: bool
    label: str = Field(description="Human/BI label, e.g. 'HOT_LEAD', 'ELIGIBLE', 'REJECTED'.")
    reason: str = Field(description="Which gate(s) drove the decision — for logs and CRM.")


class TurnLatency(BaseModel):
    """Wall-clock latency (milliseconds) for the most recently processed turn.

    Populated from the same ``measure()`` calls that already write these
    numbers to structured logs (see ``app.utils.timing``) — this is not a
    separate measurement, just the same real numbers made available to API
    callers. Any field is ``None`` if that stage didn't run this turn (e.g.
    local text-mode conversations never touch STT/TTS).
    """

    stt_ms: float | None = Field(default=None, description="Time waiting for the STT transcript.")
    llm_ms: float | None = Field(default=None, description="Time spent in the intent classifier.")
    tts_ms: float | None = Field(default=None, description="Time spent synthesising the reply.")
    total_ms: float | None = Field(
        default=None, description="Wall-clock time for the whole turn (classify + reply)."
    )


class CallSession(BaseModel):
    """Mutable state for a single voice call."""

    call_sid: str
    stream_sid: str | None = None
    scenario_id: str
    state: State = State.START
    current_question_index: int = 0
    answers: dict[str, Intent] = Field(default_factory=dict)
    turns: list[Turn] = Field(default_factory=list)
    result: QualificationResult | None = None
    last_turn_latency: TurnLatency | None = None
    started_at: datetime = Field(default_factory=_utcnow)
