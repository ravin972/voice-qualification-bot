"""YAML scenario loader tests.

Covers the architectural improvement: scenarios as external YAML config
instead of hardcoded Python. Verifies the exact minimal shape works standalone,
that optional fields get sensible defaults, that the shipped files parse
correctly, and that malformed YAML fails with a clear, locatable error.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from app.scenarios.definitions import DATA_DIR, LEAD_SCENARIO, LOAN_SCENARIO
from app.scenarios.loader import (
    ScenarioDefinitionError,
    load_scenario_file,
    load_scenarios_from_dir,
    parse_scenario,
)

# Exactly the minimal shape from the assignment spec — no optional fields.
MINIMAL_LOAN_YAML = """
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
"""


def test_minimal_spec_shape_parses_correctly() -> None:
    """The exact YAML shape from the assignment spec loads with no changes."""
    scenario = parse_scenario(yaml.safe_load(MINIMAL_LOAN_YAML), source="<minimal>")
    assert scenario.id == "loan_qualifier"
    assert [q.key for q in scenario.questions] == ["salaried", "salary", "metro"]
    assert scenario.questions[0].prompt == "Are you a salaried employee?"
    assert scenario.script.qualified == "Congratulations. An agent will contact you shortly."
    assert (
        scenario.script.rejected
        == "Unfortunately, you do not meet the current eligibility criteria."
    )


def test_missing_optional_fields_get_sensible_defaults() -> None:
    """Omitted name/greeting/labels/reprompt/goodbye fall back to generic defaults."""
    scenario = parse_scenario(yaml.safe_load(MINIMAL_LOAN_YAML), source="<minimal>")
    assert scenario.name == "Loan Qualifier"  # title-cased from 'bot'
    assert scenario.qualified_label == "QUALIFIED"
    assert scenario.rejected_label == "REJECTED"
    assert scenario.script.greeting  # non-empty generic default
    assert scenario.script.reprompt_unclear
    assert scenario.script.goodbye


def test_explicit_optional_fields_override_defaults() -> None:
    data = yaml.safe_load(MINIMAL_LOAN_YAML)
    data["name"] = "Custom Name"
    data["success"]["label"] = "ELIGIBLE"
    data["failure"]["label"] = "DECLINED"
    scenario = parse_scenario(data, source="<override>")
    assert scenario.name == "Custom Name"
    assert scenario.qualified_label == "ELIGIBLE"
    assert scenario.rejected_label == "DECLINED"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.pop("bot"),
        lambda d: d.pop("questions"),
        lambda d: d.__setitem__("questions", []),
        lambda d: d["success"].pop("message"),
        lambda d: d["failure"].pop("message"),
        lambda d: d["questions"][0].pop("id"),
        lambda d: d["questions"][0].pop("text"),
    ],
)
def test_missing_required_field_raises_clear_error(mutate) -> None:
    data = yaml.safe_load(MINIMAL_LOAN_YAML)
    mutate(data)
    with pytest.raises(ScenarioDefinitionError):
        parse_scenario(data, source="<broken>")


def test_duplicate_question_ids_raise() -> None:
    data = yaml.safe_load(MINIMAL_LOAN_YAML)
    data["questions"][1]["id"] = data["questions"][0]["id"]
    with pytest.raises(ScenarioDefinitionError, match="duplicate"):
        parse_scenario(data, source="<dup>")


def test_top_level_must_be_a_mapping() -> None:
    with pytest.raises(ScenarioDefinitionError):
        parse_scenario(["not", "a", "mapping"], source="<list>")  # type: ignore[arg-type]


def test_load_scenario_file_reads_from_disk(tmp_path: Path) -> None:
    yaml_path = tmp_path / "loan_qualifier.yaml"
    yaml_path.write_text(MINIMAL_LOAN_YAML, encoding="utf-8")
    scenario = load_scenario_file(yaml_path)
    assert scenario.id == "loan_qualifier"


def test_load_scenarios_from_dir_discovers_all_yaml_files(tmp_path: Path) -> None:
    """Dropping a new YAML file in is enough — no registry/engine code changes."""
    (tmp_path / "loan_qualifier.yaml").write_text(MINIMAL_LOAN_YAML, encoding="utf-8")
    (tmp_path / "another_bot.yml").write_text(
        MINIMAL_LOAN_YAML.replace("loan_qualifier", "another_bot"), encoding="utf-8"
    )
    (tmp_path / "not_a_scenario.txt").write_text("ignore me", encoding="utf-8")

    scenarios = load_scenarios_from_dir(tmp_path)

    assert {s.id for s in scenarios} == {"loan_qualifier", "another_bot"}


def test_shipped_lead_and_loan_files_parse_via_directory_scan() -> None:
    """The real files backing LEAD_SCENARIO/LOAN_SCENARIO parse without error."""
    scenarios = load_scenarios_from_dir(DATA_DIR)
    ids = {s.id for s in scenarios}
    assert ids == {"lead_qualifier", "loan_qualifier"}


def test_shipped_scenarios_match_their_yaml_source() -> None:
    """definitions.py's cached constants agree with a fresh parse of the same files."""
    fresh = {s.id: s for s in load_scenarios_from_dir(DATA_DIR)}
    assert fresh["lead_qualifier"] == LEAD_SCENARIO
    assert fresh["loan_qualifier"] == LOAN_SCENARIO
