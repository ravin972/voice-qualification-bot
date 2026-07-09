"""Scenario model — the config that turns one engine into many bots.

Assignment 1 (Lead Qualifier) and Assignment 2 (Loan Eligibility) are the same
shape: an ordered set of yes/no gates plus the lines the bot speaks. Modelling
a "scenario" as data means a new client bot is a new YAML file under
``app/scenarios/data/`` (parsed by ``app.scenarios.loader``), not new code.
Scenarios carry no behaviour — evaluation lives in the qualification service,
transitions in the state machine.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Question(BaseModel):
    """A single qualifying yes/no question within a scenario."""

    key: str = Field(description="Stable identifier for the answer, e.g. 'owns_home'.")
    prompt: str = Field(description="Exact wording the bot speaks to ask this question.")
    disqualify_on_no: bool = Field(
        default=True,
        description=(
            "Per both assignments a single NO disqualifies. Kept explicit and "
            "per-question so future scenarios can weight questions differently."
        ),
    )


class ScenarioScript(BaseModel):
    """The fixed lines the bot speaks around the questions."""

    greeting: str
    qualified: str = Field(description="Spoken when the caller passes every gate.")
    rejected: str = Field(description="Spoken on a polite decline.")
    reprompt_unclear: str = Field(description="Spoken when an answer could not be understood.")
    goodbye: str


class Scenario(BaseModel):
    """A fully-described qualification flow (one 'bot')."""

    id: str = Field(description="URL-safe identifier, e.g. 'lead_qualifier' or 'loan_qualifier'.")
    name: str
    questions: list[Question] = Field(min_length=1)
    script: ScenarioScript
    qualified_label: str = Field(
        default="QUALIFIED",
        description="QualificationResult.label when every gate passes, e.g. 'HOT_LEAD'.",
    )
    rejected_label: str = Field(
        default="REJECTED",
        description="QualificationResult.label when disqualified or incomplete.",
    )

    @property
    def question_count(self) -> int:
        """Number of gates in this scenario."""
        return len(self.questions)
