"""End-to-end proof that both assignment flows share one engine.

A single parametrized test drives ``LEAD_SCENARIO`` and ``LOAN_SCENARIO``
through the exact same :class:`ConversationStateMachine` (default
``LinearQualificationPolicy``) and the exact same
:class:`QualificationService` — no per-scenario branching anywhere in this
file or in the engine itself. Only the scenario *data* differs.
"""

from __future__ import annotations

import pytest
from app.models.intent import Intent
from app.models.scenario import Scenario
from app.models.session import CallSession
from app.scenarios.definitions import LEAD_SCENARIO, LOAN_SCENARIO
from app.services.qualification_service import QualificationService
from app.state_machine.events import Trigger
from app.state_machine.machine import ConversationStateMachine
from app.state_machine.states import State

FLOWS = [
    (LEAD_SCENARIO, "HOT_LEAD"),
    (LOAN_SCENARIO, "ELIGIBLE"),
]


@pytest.mark.parametrize(
    "scenario, expected_label", FLOWS, ids=["lead_qualifier", "loan_qualifier"]
)
def test_all_yes_reaches_qualified_with_correct_label(
    scenario: Scenario, expected_label: str
) -> None:
    """Same machine class, same policy, same qualification service — every flow."""
    machine = ConversationStateMachine(scenario)  # no scenario-specific setup
    session = CallSession(call_sid="CA1", scenario_id=scenario.id)

    machine.fire(Trigger.CALL_STARTED)
    for question in scenario.questions:
        session.answers[question.key] = Intent.YES
        machine.fire(Trigger.ANSWER_YES)

    assert machine.current_state is State.QUALIFIED

    result = QualificationService().evaluate(session, scenario)
    assert result.qualified is True
    assert result.label == expected_label


@pytest.mark.parametrize("scenario, _label", FLOWS, ids=["lead_qualifier", "loan_qualifier"])
def test_a_no_reaches_rejected_in_both_state_machine_and_qualification(
    scenario: Scenario, _label: str
) -> None:
    machine = ConversationStateMachine(scenario)
    session = CallSession(call_sid="CA2", scenario_id=scenario.id)

    machine.fire(Trigger.CALL_STARTED)
    first_question = scenario.questions[0]
    session.answers[first_question.key] = Intent.NO
    machine.fire(Trigger.ANSWER_NO)

    assert machine.current_state is State.REJECTED

    result = QualificationService().evaluate(session, scenario)
    assert result.qualified is False
    assert result.label == scenario.rejected_label


def test_engine_classes_are_identical_across_flows() -> None:
    """No subclassing or per-scenario engine variant exists — literally the same class."""
    lead_machine = ConversationStateMachine(LEAD_SCENARIO)
    loan_machine = ConversationStateMachine(LOAN_SCENARIO)
    assert type(lead_machine) is type(loan_machine) is ConversationStateMachine
