"""The two shipped assignment flows, loaded from their YAML definitions.

The scenario *content* (questions, spoken lines, labels) lives in
``app/scenarios/data/*.yaml`` — plain config, not Python. This module just
loads the two shipped files once at import time and re-exports them as
constants, so existing call sites (``from app.scenarios.definitions import
LEAD_SCENARIO``) keep working unchanged. Adding a third bot means dropping a
third YAML file into ``data/`` — :class:`~app.scenarios.registry.ScenarioRegistry`
picks it up automatically; nothing here needs to change.
"""

from __future__ import annotations

from pathlib import Path

from app.scenarios.loader import load_scenario_file

DATA_DIR = Path(__file__).parent / "data"

LEAD_SCENARIO = load_scenario_file(DATA_DIR / "lead_qualifier.yaml")
LOAN_SCENARIO = load_scenario_file(DATA_DIR / "loan_qualifier.yaml")
