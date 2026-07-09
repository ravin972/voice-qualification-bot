"""The conversation state machine.

Drives one call through a qualification flow by consulting a
:class:`~app.state_machine.transitions.TransitionTable` that a
:class:`~app.state_machine.policies.TransitionPolicy` compiled from the
scenario. The machine itself contains **no flow rules and no nested conditionals**
— it looks up the next state, applies the transition's effect, and moves. All
variation lives in swappable policies (Open/Closed).

Scope: control flow only. The machine never performs I/O and never decides
qualification — the authoritative verdict is produced by
``QualificationService`` from the recorded answers.
"""

from __future__ import annotations

from app.models.scenario import Scenario
from app.state_machine.events import Trigger
from app.state_machine.policies import LinearQualificationPolicy, TransitionPolicy
from app.state_machine.states import QUESTION_STATE_SEQUENCE, State
from app.state_machine.transitions import MachineContext

#: Default reprompt budget when neither a policy nor an explicit value is given.
DEFAULT_MAX_REPROMPTS = 2


class InvalidTransitionError(RuntimeError):
    """Raised when a trigger is not valid for the current state."""

    def __init__(self, state: State, trigger: Trigger) -> None:
        """Record the offending state/trigger for diagnostics.

        Args:
            state: The state the machine was in.
            trigger: The illegal trigger.
        """
        super().__init__(f"No transition from {state.value} on {trigger.value}")
        self.state = state
        self.trigger = trigger


class ConversationStateMachine:
    """Per-call finite state machine over a compiled transition table.

    Instances are stateful with respect to :attr:`current_state` and the
    reprompt counter, and are not thread-safe (one machine per call).
    """

    def __init__(
        self,
        scenario: Scenario,
        *,
        policy: TransitionPolicy | None = None,
        max_reprompts: int = DEFAULT_MAX_REPROMPTS,
        initial: State = State.START,
    ) -> None:
        """Compile the scenario and position the machine at its initial state.

        Args:
            scenario: The flow to run.
            policy: Strategy that compiles the scenario. Defaults to
                :class:`LinearQualificationPolicy` — inject another to change
                control semantics without modifying this class.
            max_reprompts: Reprompt budget for the default policy. Ignored when
                an explicit ``policy`` is supplied.
            initial: Starting state (defaults to ``START``).
        """
        self._scenario = scenario
        self._policy = policy or LinearQualificationPolicy(max_reprompts=max_reprompts)
        self._table = self._policy.build(scenario)
        self._context = MachineContext()
        self._state = initial

    @property
    def current_state(self) -> State:
        """The machine's current state."""
        return self._state

    @property
    def is_terminal(self) -> bool:
        """True once the machine has reached ``ENDED``."""
        return self._state.is_terminal

    @property
    def reprompts(self) -> int:
        """How many times the current question has been re-asked."""
        return self._context.reprompts

    @property
    def current_question_index(self) -> int | None:
        """Zero-based index of the active question, or ``None`` if not on one."""
        try:
            return QUESTION_STATE_SEQUENCE.index(self._state)
        except ValueError:
            return None

    def can_fire(self, trigger: Trigger) -> bool:
        """Return whether ``trigger`` is legal from the current state.

        Args:
            trigger: The event to test.

        Returns:
            True if a transition is currently applicable.
        """
        return self._table.resolve(self._state, trigger, self._context) is not None

    def fire(self, trigger: Trigger) -> State:
        """Apply ``trigger`` and advance the machine.

        Args:
            trigger: The event to process.

        Returns:
            The new current state.

        Raises:
            InvalidTransitionError: If the trigger is illegal for the state.
        """
        transition = self._table.resolve(self._state, trigger, self._context)
        if transition is None:
            raise InvalidTransitionError(self._state, trigger)
        if transition.effect is not None:
            transition.effect(self._context)
        self._state = transition.dest
        return self._state
