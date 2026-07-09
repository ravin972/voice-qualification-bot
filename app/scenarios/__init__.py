"""Scenario definitions and registry.

Every supported bot is a plain YAML file under ``app/scenarios/data/``,
parsed into a :class:`~app.models.scenario.Scenario` by
:mod:`app.scenarios.loader`. Adding a bot means adding a YAML file there — no
engine or registry code changes required.
"""

from app.scenarios.definitions import LEAD_SCENARIO, LOAN_SCENARIO
from app.scenarios.loader import ScenarioDefinitionError
from app.scenarios.registry import ScenarioNotFoundError, ScenarioRegistry

__all__ = [
    "ScenarioRegistry",
    "ScenarioNotFoundError",
    "ScenarioDefinitionError",
    "LEAD_SCENARIO",
    "LOAN_SCENARIO",
]
