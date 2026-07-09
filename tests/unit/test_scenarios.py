"""Scenario content and registry tests.

Covers the two shipped assignment flows as data: correct question ordering,
correct labels, and registry lookup behaviour.
"""

from __future__ import annotations

import pytest
from app.scenarios.definitions import LEAD_SCENARIO, LOAN_SCENARIO
from app.scenarios.registry import ScenarioNotFoundError, ScenarioRegistry


def test_registry_defaults_to_lead_and_loan() -> None:
    """Registry re-scans data/ independently, so scenarios are value-equal, not identical."""
    registry = ScenarioRegistry()
    assert set(registry.ids()) == {"lead_qualifier", "loan_qualifier"}
    assert registry.get("lead_qualifier") == LEAD_SCENARIO
    assert registry.get("loan_qualifier") == LOAN_SCENARIO


def test_unknown_scenario_id_raises() -> None:
    registry = ScenarioRegistry()
    with pytest.raises(ScenarioNotFoundError):
        registry.get("nonexistent")


def test_registry_accepts_explicit_scenario_set() -> None:
    """Tests/future callers can inject a bespoke catalogue without touching defaults."""
    registry = ScenarioRegistry([LEAD_SCENARIO])
    assert registry.ids() == ("lead_qualifier",)
    with pytest.raises(ScenarioNotFoundError):
        registry.get("loan_qualifier")


def test_lead_scenario_matches_assignment_spec() -> None:
    """Home Renovation Lead Qualifier: own home / budget>$10k / start<3mo."""
    assert LEAD_SCENARIO.question_count == 3
    keys = [q.key for q in LEAD_SCENARIO.questions]
    assert keys == ["owns_home", "budget_over_10k", "start_within_3_months"]
    assert all(q.disqualify_on_no for q in LEAD_SCENARIO.questions)
    assert LEAD_SCENARIO.qualified_label == "HOT_LEAD"


def test_loan_scenario_matches_assignment_spec() -> None:
    """QuickRupee Loan Qualifier: salaried / salary>25k / metro city."""
    assert LOAN_SCENARIO.question_count == 3
    keys = [q.key for q in LOAN_SCENARIO.questions]
    assert keys == ["salaried", "salary", "metro"]
    assert all(q.disqualify_on_no for q in LOAN_SCENARIO.questions)
    assert LOAN_SCENARIO.qualified_label == "ELIGIBLE"


@pytest.mark.parametrize(
    "scenario", [LEAD_SCENARIO, LOAN_SCENARIO], ids=["lead_qualifier", "loan_qualifier"]
)
def test_scenario_script_has_all_required_lines(scenario) -> None:
    script = scenario.script
    assert script.greeting and script.qualified and script.rejected
    assert script.reprompt_unclear and script.goodbye
