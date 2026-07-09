"""Caller intent — the *only* thing the LLM is allowed to produce.

The language model's sole responsibility is to collapse a free-form speech
transcript into exactly one of these four discrete tokens. It never sees the
business rules and never decides qualification. All downstream logic branches
on this closed enum, which is what keeps decision-making deterministic and
fully owned by Python.
"""

from __future__ import annotations

from enum import Enum


class Intent(str, Enum):
    """Normalised caller intent for a single yes/no question.

    Members:
        YES: Caller affirmed.
        NO: Caller declined / answered negatively.
        REPEAT: Caller explicitly asked to hear the question again.
        UNCLEAR: Transcript was ambiguous, empty, off-topic, or low-confidence.
    """

    YES = "YES"
    NO = "NO"
    REPEAT = "REPEAT"
    UNCLEAR = "UNCLEAR"

    @classmethod
    def choices(cls) -> tuple[str, ...]:
        """Return the allowed string values (used to constrain the LLM output)."""
        return tuple(member.value for member in cls)
