"""Qualification service — the pure-Python decision authority.

This is the one place a caller is judged qualified or rejected. It is
intentionally free of I/O, vendors, and the LLM: it reads the answers recorded
on a :class:`~app.models.session.CallSession` against a
:class:`~app.models.scenario.Scenario` and returns a
:class:`~app.models.session.QualificationResult`.

Business rule (both assignments): a caller qualifies only if *every*
disqualifying gate is ``Intent.YES``; a single ``NO`` rejects. This single
implementation drives every scenario — the *label* it reports
(``scenario.qualified_label`` / ``scenario.rejected_label``) is scenario data,
not a code branch, so a new flow never requires a code change here.
"""

from __future__ import annotations

from app.models.intent import Intent
from app.models.scenario import Scenario
from app.models.session import CallSession, QualificationResult


class QualificationService:
    """Evaluates recorded answers into a final verdict. Stateless and pure."""

    def evaluate(self, session: CallSession, scenario: Scenario) -> QualificationResult:
        """Decide whether the caller qualifies.

        Walks the scenario's gates in order and rejects at the first one that
        is unanswered or answered anything other than ``YES`` (for questions
        where ``disqualify_on_no`` is set — true for both shipped flows).
        Only when every gate passes does the caller qualify.

        Args:
            session: The call whose ``answers`` are being judged.
            scenario: The scenario supplying the gates and result labels.

        Returns:
            A :class:`QualificationResult` with the verdict, label, and reason.
        """
        for question in scenario.questions:
            answer = session.answers.get(question.key)
            if answer is None:
                return QualificationResult(
                    qualified=False,
                    label=scenario.rejected_label,
                    reason=f"incomplete: '{question.key}' not yet answered",
                )
            if question.disqualify_on_no and answer is not Intent.YES:
                return QualificationResult(
                    qualified=False,
                    label=scenario.rejected_label,
                    reason=f"disqualified at '{question.key}': answered {answer.value}",
                )
        return QualificationResult(
            qualified=True,
            label=scenario.qualified_label,
            reason="all gates answered YES",
        )

    def all_questions_answered(self, session: CallSession, scenario: Scenario) -> bool:
        """Whether every gate in the scenario has a recorded answer.

        Args:
            session: The call to inspect.
            scenario: The scenario defining the required gates.

        Returns:
            True once all questions have an answer.
        """
        return all(question.key in session.answers for question in scenario.questions)
