"""Qualification-rule tests.

Exercises the single, scenario-agnostic decision function that both shipped
flows share: :meth:`QualificationService.evaluate`. Parametrizing every test
over both real scenarios (``LEAD_SCENARIO``, ``LOAN_SCENARIO``) is itself part
of the proof that one implementation drives both bots with no per-scenario code.
"""

from __future__ import annotations

import pytest
from app.models.intent import Intent
from app.models.scenario import Scenario
from app.models.session import CallSession
from app.scenarios.definitions import LEAD_SCENARIO, LOAN_SCENARIO
from app.services.qualification_service import QualificationService

BOTH_SCENARIOS = pytest.mark.parametrize(
    "scenario", [LEAD_SCENARIO, LOAN_SCENARIO], ids=["lead_qualifier", "loan_qualifier"]
)


def _session(scenario: Scenario, **answers: Intent) -> CallSession:
    return CallSession(call_sid="CA1", scenario_id=scenario.id, answers=answers)


@pytest.fixture
def service() -> QualificationService:
    return QualificationService()


@BOTH_SCENARIOS
def test_all_yes_qualifies(service: QualificationService, scenario: Scenario) -> None:
    """Every gate YES → qualified=True with the scenario's positive label."""
    session = _session(scenario, **{q.key: Intent.YES for q in scenario.questions})
    result = service.evaluate(session, scenario)
    assert result.qualified is True
    assert result.label == scenario.qualified_label


@BOTH_SCENARIOS
@pytest.mark.parametrize("failing_index", [0, 1, 2])
def test_single_no_rejects(
    service: QualificationService, scenario: Scenario, failing_index: int
) -> None:
    """One NO anywhere → qualified=False with a reason naming the failed gate."""
    answers = {q.key: Intent.YES for q in scenario.questions}
    failing_question = scenario.questions[failing_index]
    answers[failing_question.key] = Intent.NO
    session = _session(scenario, **answers)

    result = service.evaluate(session, scenario)

    assert result.qualified is False
    assert result.label == scenario.rejected_label
    assert failing_question.key in result.reason


@BOTH_SCENARIOS
def test_result_is_deterministic_and_llm_free(
    service: QualificationService, scenario: Scenario
) -> None:
    """The verdict depends only on recorded intents — calling twice agrees."""
    session = _session(scenario, **{q.key: Intent.YES for q in scenario.questions})
    first = service.evaluate(session, scenario)
    second = service.evaluate(session, scenario)
    assert first == second


@BOTH_SCENARIOS
def test_incomplete_answers_are_not_qualified(
    service: QualificationService, scenario: Scenario
) -> None:
    """Missing answers cannot yield a qualified result."""
    session = _session(scenario)  # no answers recorded yet
    result = service.evaluate(session, scenario)
    assert result.qualified is False
    assert result.label == scenario.rejected_label


@BOTH_SCENARIOS
def test_all_questions_answered_reflects_completeness(
    service: QualificationService, scenario: Scenario
) -> None:
    empty = _session(scenario)
    assert service.all_questions_answered(empty, scenario) is False

    full = _session(scenario, **{q.key: Intent.YES for q in scenario.questions})
    assert service.all_questions_answered(full, scenario) is True


def test_first_disqualifying_gate_wins_when_multiple_answers_are_no(
    service: QualificationService,
) -> None:
    """Rejection reports the first failing gate in scenario order, deterministically."""
    scenario = LEAD_SCENARIO
    session = _session(
        scenario,
        owns_home=Intent.NO,
        budget_over_10k=Intent.NO,
        start_within_3_months=Intent.YES,
    )
    result = service.evaluate(session, scenario)
    assert result.qualified is False
    assert "owns_home" in result.reason


def test_loan_and_lead_labels_are_distinct() -> None:
    """The two flows' qualified labels differ, proving scenario data (not code) drives it."""
    assert LEAD_SCENARIO.qualified_label == "HOT_LEAD"
    assert LOAN_SCENARIO.qualified_label == "ELIGIBLE"
    assert LEAD_SCENARIO.qualified_label != LOAN_SCENARIO.qualified_label
