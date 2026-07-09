"""Domain models — the pure data contracts shared across every layer.

Models depend on nothing but the standard library, ``pydantic``, and other
models. They never import services, state machines, or config. This keeps them
at the centre of the dependency graph (the "domain core").
"""

from app.models.audio import AudioChunk, AudioEncoding, Transcript
from app.models.intent import Intent
from app.models.scenario import Question, Scenario, ScenarioScript
from app.models.session import CallSession, QualificationResult, Turn

__all__ = [
    "AudioChunk",
    "AudioEncoding",
    "Transcript",
    "Intent",
    "Question",
    "Scenario",
    "ScenarioScript",
    "CallSession",
    "QualificationResult",
    "Turn",
]
