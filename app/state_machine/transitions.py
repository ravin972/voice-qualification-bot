"""Transition primitives for the conversation state machine.

These are the declarative building blocks — a guarded :class:`Transition` and an
immutable :class:`TransitionTable` — that let the machine resolve
``(state, trigger) -> state`` with **no nested conditionals**. They are entirely
flow-agnostic: every :class:`~app.state_machine.policies.TransitionPolicy`
reuses them unchanged, which is what keeps the system open for extension but
closed for modification.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from app.state_machine.events import Trigger
from app.state_machine.states import State


@dataclass
class MachineContext:
    """Mutable per-call runtime data consulted by guards and effects.

    Kept deliberately small; it holds only what transitions need to make a
    bounded decision (e.g. how many times the current question was re-asked).
    """

    reprompts: int = 0


#: A predicate over the runtime context deciding whether a transition applies.
Guard = Callable[[MachineContext], bool]

#: A side effect applied to the context when a transition fires.
Effect = Callable[[MachineContext], None]


@dataclass(frozen=True, slots=True)
class Transition:
    """A single declarative edge in the state graph.

    Multiple transitions may share a ``(source, trigger)`` key; the table
    selects the first whose :attr:`guard` passes, giving conditional routing
    without branching in the machine.
    """

    source: State
    trigger: Trigger
    dest: State
    guard: Guard | None = None
    effect: Effect | None = None
    label: str = ""


class TransitionTable:
    """Immutable, ordered lookup of guarded transitions.

    Built once per call by a policy, then queried by the machine. Ordering
    within a ``(source, trigger)`` group is preserved so guard precedence is
    deterministic.
    """

    def __init__(self, transitions: Iterable[Transition]) -> None:
        """Index transitions by their ``(source, trigger)`` key.

        Args:
            transitions: The complete set of edges for one flow.
        """
        table: dict[tuple[State, Trigger], list[Transition]] = {}
        for transition in transitions:
            table.setdefault((transition.source, transition.trigger), []).append(transition)
        self._table = table

    def resolve(
        self, state: State, trigger: Trigger, context: MachineContext
    ) -> Transition | None:
        """Return the first applicable transition, or ``None`` if none applies.

        Args:
            state: Current machine state.
            trigger: The event being processed.
            context: Runtime context evaluated by transition guards.

        Returns:
            The matching :class:`Transition`, or ``None`` when the move is illegal.
        """
        for transition in self._table.get((state, trigger), ()):
            if transition.guard is None or transition.guard(context):
                return transition
        return None

    def has_edge(self, state: State, trigger: Trigger) -> bool:
        """Whether any (possibly guarded) transition exists for the key."""
        return bool(self._table.get((state, trigger)))

    def source_states(self) -> frozenset[State]:
        """All states that have at least one outgoing transition."""
        return frozenset(source for source, _ in self._table)


def increment_reprompts(context: MachineContext) -> None:
    """Effect: count one re-ask of the current question."""
    context.reprompts += 1


def reset_reprompts(context: MachineContext) -> None:
    """Effect: clear the re-ask counter (e.g. when advancing to a new question)."""
    context.reprompts = 0
