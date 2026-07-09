"""The finite set of conversation states.

Kept dependency-free (imports nothing internal) so it can sit at the very
bottom of the dependency graph — ``models.session`` and ``state_machine.machine``
both build on it without risk of an import cycle.
"""

from __future__ import annotations

from enum import Enum


class State(str, Enum):
    """Every state a call can occupy.

    Flow (happy path): START → QUESTION_ONE → QUESTION_TWO → QUESTION_THREE →
    QUALIFIED → ENDED. Any NO short-circuits to REJECTED → ENDED.
    """

    START = "START"
    QUESTION_ONE = "QUESTION_ONE"
    QUESTION_TWO = "QUESTION_TWO"
    QUESTION_THREE = "QUESTION_THREE"
    QUALIFIED = "QUALIFIED"
    REJECTED = "REJECTED"
    ENDED = "ENDED"

    @property
    def is_terminal(self) -> bool:
        """True when no further transitions are possible from this state."""
        return self is State.ENDED

    @property
    def is_question(self) -> bool:
        """True when the bot is awaiting an answer to a qualifying question."""
        return self in _QUESTION_STATES


#: Ordered question states, indexable by ``current_question_index``.
QUESTION_STATE_SEQUENCE: tuple[State, ...] = (
    State.QUESTION_ONE,
    State.QUESTION_TWO,
    State.QUESTION_THREE,
)

_QUESTION_STATES: frozenset[State] = frozenset(QUESTION_STATE_SEQUENCE)
