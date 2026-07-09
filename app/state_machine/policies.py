"""Transition policies — the Open/Closed seam of the state machine.

A *policy* compiles a :class:`~app.models.scenario.Scenario` into a
:class:`~app.state_machine.transitions.TransitionTable`. This is the single
extension point of the state machine:

* **Add a new standard flow** (e.g. a new client's qualifier) → just register a
  new ``Scenario`` *data object*. :class:`LinearQualificationPolicy` builds its
  table generically from the scenario, so **no code changes**.
* **Add new control semantics** (e.g. a flow where a "no" branches instead of
  rejecting) → implement a new :class:`TransitionPolicy`. Existing policies and
  :class:`~app.state_machine.machine.ConversationStateMachine` are never modified.

The shared "all YES qualifies, any NO rejects, unclear/repeat re-asks (bounded)"
behaviour of both current assignments lives in one place: ``LinearQualificationPolicy``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.scenario import Scenario
from app.state_machine.events import Trigger
from app.state_machine.states import QUESTION_STATE_SEQUENCE, State
from app.state_machine.transitions import (
    MachineContext,
    Transition,
    TransitionTable,
    increment_reprompts,
    reset_reprompts,
)


class ScenarioTooLargeError(ValueError):
    """Raised when a scenario has more questions than there are question states."""


class TransitionPolicy(ABC):
    """Port: compiles a scenario into a transition table.

    Subclass this to introduce a flow whose *control flow* differs from the
    default. The machine depends on this abstraction, never on a concrete policy.
    """

    @abstractmethod
    def build(self, scenario: Scenario) -> TransitionTable:
        """Compile ``scenario`` into a complete transition table.

        Args:
            scenario: The flow to compile.

        Returns:
            A :class:`TransitionTable` covering every legal transition.
        """
        raise NotImplementedError


class LinearQualificationPolicy(TransitionPolicy):
    """Default flow: a linear gauntlet of yes/no gates.

    Semantics, applied uniformly to every question in the scenario:

    * ``YES`` advances to the next question, or to ``QUALIFIED`` on the last one.
    * ``NO`` short-circuits to ``REJECTED``.
    * ``REPEAT`` / ``UNCLEAR`` re-ask the current question (a self-loop), bounded
      by ``max_reprompts``; once exhausted the call escalates to
      ``escalation_state`` (``REJECTED`` by default).
    * ``HANGUP`` from any non-terminal state ends the call.
    """

    def __init__(
        self,
        *,
        max_reprompts: int = 2,
        escalation_state: State = State.REJECTED,
    ) -> None:
        """Configure the policy.

        Args:
            max_reprompts: How many times a single question may be re-asked
                before escalating. ``0`` escalates on the first unclear reply.
            escalation_state: Terminal state entered when reprompts are exhausted.

        Raises:
            ValueError: If ``max_reprompts`` is negative.
        """
        if max_reprompts < 0:
            raise ValueError("max_reprompts must be non-negative")
        self._max_reprompts = max_reprompts
        self._escalation_state = escalation_state

    def build(self, scenario: Scenario) -> TransitionTable:
        """Generically compile any scenario into its linear transition table.

        Args:
            scenario: The flow to compile.

        Returns:
            The compiled table.

        Raises:
            ScenarioTooLargeError: If the scenario has more questions than the
                available ordinal question states.
        """
        count = scenario.question_count
        if count > len(QUESTION_STATE_SEQUENCE):
            raise ScenarioTooLargeError(
                f"Scenario '{scenario.id}' has {count} questions; "
                f"only {len(QUESTION_STATE_SEQUENCE)} question states exist."
            )
        question_states = QUESTION_STATE_SEQUENCE[:count]

        transitions: list[Transition] = [
            Transition(State.START, Trigger.CALL_STARTED, question_states[0], label="begin"),
        ]
        for index, state in enumerate(question_states):
            is_last = index == count - 1
            advance_to = State.QUALIFIED if is_last else question_states[index + 1]
            transitions.append(
                Transition(
                    state, Trigger.ANSWER_YES, advance_to, effect=reset_reprompts, label="advance"
                )
            )
            transitions.append(
                Transition(state, Trigger.ANSWER_NO, State.REJECTED, label="disqualify")
            )
            transitions.extend(self._reprompt(state, Trigger.ANSWER_REPEAT))
            transitions.extend(self._reprompt(state, Trigger.ANSWER_UNCLEAR))

        for state in (State.START, *question_states, State.QUALIFIED, State.REJECTED):
            transitions.append(Transition(state, Trigger.HANGUP, State.ENDED, label="hangup"))

        return TransitionTable(transitions)

    def _reprompt(self, state: State, trigger: Trigger) -> list[Transition]:
        """Build the bounded self-loop + escalation pair for one question/event."""
        return [
            Transition(
                state, trigger, state,
                guard=self._under_limit, effect=increment_reprompts, label="reprompt",
            ),
            Transition(
                state, trigger, self._escalation_state,
                guard=self._at_limit, effect=reset_reprompts, label="escalate",
            ),
        ]

    def _under_limit(self, context: MachineContext) -> bool:
        """Guard: still within the reprompt budget."""
        return context.reprompts < self._max_reprompts

    def _at_limit(self, context: MachineContext) -> bool:
        """Guard: reprompt budget exhausted."""
        return context.reprompts >= self._max_reprompts
