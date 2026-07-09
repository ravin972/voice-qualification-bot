"""Triggers that drive state transitions.

A trigger is what *happens*; a state is where we *are*. Most triggers are a
direct lift of a normalised :class:`~app.models.intent.Intent`, plus two
lifecycle events (call start / hangup). Separating triggers from intents keeps
the state machine independent of how an answer was obtained.
"""

from __future__ import annotations

from enum import Enum

from app.models.intent import Intent


class Trigger(str, Enum):
    """The complete alphabet of events the state machine reacts to."""

    CALL_STARTED = "CALL_STARTED"
    ANSWER_YES = "ANSWER_YES"
    ANSWER_NO = "ANSWER_NO"
    ANSWER_REPEAT = "ANSWER_REPEAT"
    ANSWER_UNCLEAR = "ANSWER_UNCLEAR"
    HANGUP = "HANGUP"

    @classmethod
    def from_intent(cls, intent: Intent) -> Trigger:
        """Map a normalised caller intent to its corresponding trigger.

        Args:
            intent: The LLM-normalised answer.

        Returns:
            The matching ``ANSWER_*`` trigger.
        """
        return _INTENT_TO_TRIGGER[intent]


_INTENT_TO_TRIGGER: dict[Intent, Trigger] = {
    Intent.YES: Trigger.ANSWER_YES,
    Intent.NO: Trigger.ANSWER_NO,
    Intent.REPEAT: Trigger.ANSWER_REPEAT,
    Intent.UNCLEAR: Trigger.ANSWER_UNCLEAR,
}
