"""Explicit conversation state machine.

The dialogue is a finite state machine with a declarative transition table —
never nested ``if`` statements. Control-flow variation is added by registering
new scenarios (data) or new :class:`TransitionPolicy` strategies (code), without
modifying existing classes (Open/Closed).

Public API:

* :class:`State`, :class:`Trigger` — the state/event vocabulary.
* :class:`ConversationStateMachine`, :class:`InvalidTransitionError` — the machine.
* :class:`TransitionPolicy`, :class:`LinearQualificationPolicy` — the extension seam.
* :class:`Transition`, :class:`TransitionTable`, :class:`MachineContext` — primitives.
"""

from app.state_machine.events import Trigger
from app.state_machine.machine import (
    DEFAULT_MAX_REPROMPTS,
    ConversationStateMachine,
    InvalidTransitionError,
)
from app.state_machine.policies import (
    LinearQualificationPolicy,
    ScenarioTooLargeError,
    TransitionPolicy,
)
from app.state_machine.states import QUESTION_STATE_SEQUENCE, State
from app.state_machine.transitions import MachineContext, Transition, TransitionTable

__all__ = [
    "State",
    "Trigger",
    "QUESTION_STATE_SEQUENCE",
    "ConversationStateMachine",
    "InvalidTransitionError",
    "DEFAULT_MAX_REPROMPTS",
    "TransitionPolicy",
    "LinearQualificationPolicy",
    "ScenarioTooLargeError",
    "Transition",
    "TransitionTable",
    "MachineContext",
]
