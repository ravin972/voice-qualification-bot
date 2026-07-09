"""Shared pytest fixtures.

Provides reusable domain objects for the deterministic-core tests (state machine
and qualification service). The actual test bodies are written alongside the
logic phase; these fixtures define the shared setup contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.models.scenario import Question, Scenario, ScenarioScript


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Auto-tag tests with the ``unit``/``integration`` marker by directory.

    Lets ``pytest -m unit`` / ``pytest -m integration`` filter runs without
    every test file needing its own explicit marker.
    """
    for item in items:
        path = Path(str(item.fspath))
        if "integration" in path.parts:
            item.add_marker(pytest.mark.integration)
        elif "unit" in path.parts:
            item.add_marker(pytest.mark.unit)


@pytest.fixture
def sample_scenario() -> Scenario:
    """A minimal three-gate scenario usable by state-machine and rules tests."""
    return Scenario(
        id="test",
        name="Test Scenario",
        questions=[
            Question(key="q1", prompt="Question one?"),
            Question(key="q2", prompt="Question two?"),
            Question(key="q3", prompt="Question three?"),
        ],
        script=ScenarioScript(
            greeting="Hello.",
            qualified="You qualify.",
            rejected="Sorry, not this time.",
            reprompt_unclear="Sorry, I didn't catch that.",
            goodbye="Goodbye.",
        ),
    )
