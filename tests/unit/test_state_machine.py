"""State-machine transition tests.

Covers the deterministic control-flow core: the happy path, disqualification,
bounded reprompts, hangup, illegal transitions, generic scenario sizing, and the
Open/Closed extension seam (a custom policy plugged in without touching the
machine).
"""

from __future__ import annotations

import pytest
from app.models.scenario import Question, Scenario, ScenarioScript
from app.state_machine.events import Trigger
from app.state_machine.machine import ConversationStateMachine, InvalidTransitionError
from app.state_machine.policies import (
    LinearQualificationPolicy,
    ScenarioTooLargeError,
    TransitionPolicy,
)
from app.state_machine.states import State
from app.state_machine.transitions import Transition, TransitionTable


def _machine(scenario: Scenario, max_reprompts: int = 2) -> ConversationStateMachine:
    return ConversationStateMachine(scenario, max_reprompts=max_reprompts)


def _scenario_with(n_questions: int) -> Scenario:
    return Scenario(
        id=f"s{n_questions}",
        name="N",
        questions=[Question(key=f"q{i}", prompt=f"Q{i}?") for i in range(n_questions)],
        script=ScenarioScript(
            greeting="hi", qualified="yes", rejected="no",
            reprompt_unclear="what?", goodbye="bye",
        ),
    )


# --- Happy path ------------------------------------------------------------
def test_happy_path_all_yes_reaches_qualified(sample_scenario: Scenario) -> None:
    """START →(YES×3)→ QUALIFIED, then ENDED."""
    m = _machine(sample_scenario)
    assert m.current_state is State.START
    assert m.fire(Trigger.CALL_STARTED) is State.QUESTION_ONE
    assert m.fire(Trigger.ANSWER_YES) is State.QUESTION_TWO
    assert m.fire(Trigger.ANSWER_YES) is State.QUESTION_THREE
    assert m.fire(Trigger.ANSWER_YES) is State.QUALIFIED
    assert m.fire(Trigger.HANGUP) is State.ENDED
    assert m.is_terminal


# --- Disqualification ------------------------------------------------------
@pytest.mark.parametrize("question_index", [0, 1, 2])
def test_any_no_short_circuits_to_rejected(
    sample_scenario: Scenario, question_index: int
) -> None:
    """A NO on any question transitions directly to REJECTED."""
    m = _machine(sample_scenario)
    m.fire(Trigger.CALL_STARTED)
    for _ in range(question_index):
        m.fire(Trigger.ANSWER_YES)
    assert m.fire(Trigger.ANSWER_NO) is State.REJECTED


# --- Reprompt / unclear handling ------------------------------------------
def test_repeat_is_a_self_loop_on_current_question(sample_scenario: Scenario) -> None:
    """REPEAT re-asks without advancing the question index."""
    m = _machine(sample_scenario, max_reprompts=5)
    m.fire(Trigger.CALL_STARTED)
    assert m.fire(Trigger.ANSWER_REPEAT) is State.QUESTION_ONE
    assert m.reprompts == 1
    assert m.current_question_index == 0


def test_unclear_reprompts_until_limit_then_escalates(sample_scenario: Scenario) -> None:
    """UNCLEAR self-loops up to max_reprompts, then escalates to REJECTED."""
    m = _machine(sample_scenario, max_reprompts=2)
    m.fire(Trigger.CALL_STARTED)
    assert m.fire(Trigger.ANSWER_UNCLEAR) is State.QUESTION_ONE  # reprompt 1
    assert m.fire(Trigger.ANSWER_UNCLEAR) is State.QUESTION_ONE  # reprompt 2
    assert m.fire(Trigger.ANSWER_UNCLEAR) is State.REJECTED       # escalate


def test_zero_reprompt_budget_escalates_immediately() -> None:
    """max_reprompts=0 escalates on the first unclear reply."""
    m = _machine(_scenario_with(3), max_reprompts=0)
    m.fire(Trigger.CALL_STARTED)
    assert m.fire(Trigger.ANSWER_UNCLEAR) is State.REJECTED


def test_advancing_resets_the_reprompt_counter(sample_scenario: Scenario) -> None:
    """A YES after reprompts clears the counter for the next question."""
    m = _machine(sample_scenario, max_reprompts=2)
    m.fire(Trigger.CALL_STARTED)
    m.fire(Trigger.ANSWER_UNCLEAR)
    assert m.reprompts == 1
    assert m.fire(Trigger.ANSWER_YES) is State.QUESTION_TWO
    assert m.reprompts == 0


# --- Hangup & illegal transitions -----------------------------------------
def test_hangup_from_any_state_reaches_ended(sample_scenario: Scenario) -> None:
    """HANGUP always terminates the call."""
    from_start = _machine(sample_scenario)
    assert from_start.fire(Trigger.HANGUP) is State.ENDED

    from_question = _machine(sample_scenario)
    from_question.fire(Trigger.CALL_STARTED)
    assert from_question.fire(Trigger.HANGUP) is State.ENDED


def test_illegal_trigger_raises_invalid_transition(sample_scenario: Scenario) -> None:
    """An undefined (state, trigger) pair raises InvalidTransitionError."""
    m = _machine(sample_scenario)  # in START
    with pytest.raises(InvalidTransitionError) as exc:
        m.fire(Trigger.ANSWER_YES)
    assert exc.value.state is State.START
    assert exc.value.trigger is Trigger.ANSWER_YES


def test_can_fire_reflects_the_table(sample_scenario: Scenario) -> None:
    """can_fire mirrors whether a transition is currently applicable."""
    m = _machine(sample_scenario)
    assert m.can_fire(Trigger.CALL_STARTED) is True
    assert m.can_fire(Trigger.ANSWER_YES) is False


def test_terminal_qualified_accepts_only_hangup(sample_scenario: Scenario) -> None:
    """From QUALIFIED, only HANGUP is legal."""
    m = _machine(sample_scenario)
    triggers = (Trigger.CALL_STARTED, Trigger.ANSWER_YES, Trigger.ANSWER_YES, Trigger.ANSWER_YES)
    for trigger in triggers:
        m.fire(trigger)
    assert m.current_state is State.QUALIFIED
    assert m.can_fire(Trigger.ANSWER_YES) is False
    assert m.can_fire(Trigger.HANGUP) is True


# --- Extensibility: new flows without modifying existing code --------------
def test_scenario_size_is_generic_two_questions_qualifies_at_second() -> None:
    """A 2-question scenario qualifies after the second YES — no code change."""
    m = _machine(_scenario_with(2))
    m.fire(Trigger.CALL_STARTED)
    assert m.fire(Trigger.ANSWER_YES) is State.QUESTION_TWO
    assert m.fire(Trigger.ANSWER_YES) is State.QUALIFIED


def test_scenario_larger_than_state_capacity_is_rejected() -> None:
    """A scenario with more questions than ordinal states fails fast."""
    with pytest.raises(ScenarioTooLargeError):
        LinearQualificationPolicy().build(_scenario_with(4))


def test_custom_policy_is_pluggable_without_modifying_the_machine(
    sample_scenario: Scenario,
) -> None:
    """Open/Closed: a bespoke policy changes behaviour with zero machine edits."""

    class InstantQualifyPolicy(TransitionPolicy):
        def build(self, scenario: Scenario) -> TransitionTable:
            return TransitionTable(
                [Transition(State.START, Trigger.CALL_STARTED, State.QUALIFIED)]
            )

    m = ConversationStateMachine(sample_scenario, policy=InstantQualifyPolicy())
    assert m.fire(Trigger.CALL_STARTED) is State.QUALIFIED
