"""Scenario registry.

Resolves a scenario id (e.g. from a Twilio stream parameter) to a concrete
:class:`~app.models.scenario.Scenario`. By default it scans
``app/scenarios/data/*.yaml`` and loads whatever it finds — adding a new bot
means dropping a new YAML file there; this registry (and every consumer of it)
needs no code change to pick it up.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from app.models.scenario import Scenario
from app.scenarios.loader import load_scenarios_from_dir

#: Directory scanned for scenario YAML files by the default constructor.
DEFAULT_SCENARIOS_DIR = Path(__file__).parent / "data"


class ScenarioNotFoundError(KeyError):
    """Raised when a requested scenario id is not registered."""


class ScenarioRegistry:
    """In-memory catalogue of available scenarios."""

    def __init__(
        self,
        scenarios: Iterable[Scenario] | None = None,
        *,
        scenarios_dir: Path | None = None,
    ) -> None:
        """Build the catalogue.

        Args:
            scenarios: Explicit scenario set (e.g. for tests). Takes priority
                over ``scenarios_dir`` when both are given.
            scenarios_dir: Directory to scan for ``*.yaml``/``*.yml`` scenario
                files. Defaults to ``app/scenarios/data/``. Ignored if
                ``scenarios`` is given.
        """
        if scenarios is not None:
            source: Iterable[Scenario] = scenarios
        else:
            source = load_scenarios_from_dir(scenarios_dir or DEFAULT_SCENARIOS_DIR)
        self._scenarios: dict[str, Scenario] = {s.id: s for s in source}

    def get(self, scenario_id: str) -> Scenario:
        """Resolve a scenario by id.

        Args:
            scenario_id: The scenario selector, e.g. ``'lead_qualifier'``.

        Returns:
            The matching :class:`Scenario`.

        Raises:
            ScenarioNotFoundError: If no scenario is registered under that id.
        """
        try:
            return self._scenarios[scenario_id]
        except KeyError:
            raise ScenarioNotFoundError(scenario_id) from None

    def ids(self) -> tuple[str, ...]:
        """Return all registered scenario ids."""
        return tuple(self._scenarios)
