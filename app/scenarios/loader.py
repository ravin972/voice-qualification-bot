"""YAML scenario loader — the architectural improvement over hardcoded Python data.

Scenarios were previously plain Python ``Scenario(...)`` literals. That still
works (a new bot was "add config, not code"), but it meant "config" lived
inside a ``.py`` file — anyone adding or tweaking a bot had to touch Python.
This loader makes scenarios *actual* external config: plain YAML files under
``app/scenarios/data/`` that a non-engineer (or a CI step, or an admin UI) can
add/edit without importing anything.

Minimal shape (every optional field has a sensible default)::

    bot: loan_qualifier
    questions:
      - id: salaried
        text: Are you a salaried employee?
      - id: salary
        text: Is your monthly salary above ₹25,000?
      - id: metro
        text: Do you live in a metro city?
    success:
      message: Congratulations. An agent will contact you shortly.
    failure:
      message: Unfortunately, you do not meet the current eligibility criteria.

Full shape adds optional ``name``, ``greeting``, ``success.label``,
``failure.label``, ``reprompt_unclear``, and ``goodbye`` — see the shipped
files in ``app/scenarios/data/`` for a complete example.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.models.scenario import Question, Scenario, ScenarioScript

_DEFAULT_GREETING = "Hi, thanks for calling. I just need to ask a few quick questions."
_DEFAULT_REPROMPT_UNCLEAR = "Sorry, I didn't quite catch that — could you say yes or no?"
_DEFAULT_GOODBYE = "Thank you for your time. Goodbye!"
_DEFAULT_QUALIFIED_LABEL = "QUALIFIED"
_DEFAULT_REJECTED_LABEL = "REJECTED"


class ScenarioDefinitionError(ValueError):
    """Raised when a scenario YAML file is missing or malformed."""


def _require(data: dict[str, Any], key: str, *, where: str) -> Any:
    """Fetch a required key or raise a clear, file-locatable error."""
    if key not in data or data[key] in (None, "", []):
        raise ScenarioDefinitionError(f"{where}: missing required field '{key}'")
    return data[key]


def _parse_questions(raw_questions: Any, *, where: str) -> list[Question]:
    """Parse the ``questions`` list, catching shape errors early with context."""
    if not isinstance(raw_questions, list) or not raw_questions:
        raise ScenarioDefinitionError(f"{where}: 'questions' must be a non-empty list")

    questions: list[Question] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_questions):
        if not isinstance(raw, dict):
            raise ScenarioDefinitionError(f"{where}: questions[{index}] must be a mapping")
        question_id = _require(raw, "id", where=f"{where}: questions[{index}]")
        text = _require(raw, "text", where=f"{where}: questions[{index}]")
        if question_id in seen_ids:
            raise ScenarioDefinitionError(f"{where}: duplicate question id '{question_id}'")
        seen_ids.add(question_id)
        questions.append(Question(key=str(question_id), prompt=str(text)))
    return questions


def parse_scenario(data: dict[str, Any], *, source: str = "<memory>") -> Scenario:
    """Convert a parsed YAML mapping into a validated :class:`Scenario`.

    Args:
        data: The mapping produced by ``yaml.safe_load``.
        source: Human-readable origin (typically the file path) used in errors.

    Returns:
        A fully-populated :class:`Scenario`.

    Raises:
        ScenarioDefinitionError: If a required field is missing or malformed.
    """
    if not isinstance(data, dict):
        raise ScenarioDefinitionError(f"{source}: top-level YAML must be a mapping")

    bot_id = str(_require(data, "bot", where=source))
    questions = _parse_questions(data.get("questions"), where=source)

    success = data.get("success") or {}
    failure = data.get("failure") or {}
    if not isinstance(success, dict) or not isinstance(failure, dict):
        raise ScenarioDefinitionError(f"{source}: 'success' and 'failure' must be mappings")

    qualified_message = _require(success, "message", where=f"{source}: success")
    rejected_message = _require(failure, "message", where=f"{source}: failure")

    name = data.get("name") or bot_id.replace("_", " ").title()

    return Scenario(
        id=bot_id,
        name=str(name),
        questions=questions,
        qualified_label=str(success.get("label") or _DEFAULT_QUALIFIED_LABEL),
        rejected_label=str(failure.get("label") or _DEFAULT_REJECTED_LABEL),
        script=ScenarioScript(
            greeting=str(data.get("greeting") or _DEFAULT_GREETING),
            qualified=str(qualified_message),
            rejected=str(rejected_message),
            reprompt_unclear=str(data.get("reprompt_unclear") or _DEFAULT_REPROMPT_UNCLEAR),
            goodbye=str(data.get("goodbye") or _DEFAULT_GOODBYE),
        ),
    )


def load_scenario_file(path: Path) -> Scenario:
    """Load and parse a single scenario YAML file.

    Args:
        path: Path to a ``.yaml``/``.yml`` scenario definition.

    Returns:
        The parsed :class:`Scenario`.

    Raises:
        ScenarioDefinitionError: If the file is malformed or missing fields.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return parse_scenario(raw or {}, source=str(path))


def load_scenarios_from_dir(directory: Path) -> tuple[Scenario, ...]:
    """Load every ``*.yaml``/``*.yml`` scenario file in a directory.

    Args:
        directory: Directory to scan (non-recursive).

    Returns:
        Parsed scenarios, ordered by filename for deterministic output.
    """
    paths = sorted({*directory.glob("*.yaml"), *directory.glob("*.yml")})
    return tuple(load_scenario_file(path) for path in paths)
