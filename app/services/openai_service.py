"""LLM intent-normalisation port and OpenAI adapter.

CRITICAL CONSTRAINT — the LLM is a *classifier only*. Its entire job is to map a
speech transcript to one of ``Intent.{YES, NO, REPEAT, UNCLEAR}``. It receives no
business rules, returns no free text, and makes no eligibility decision. Three
layers enforce this:

1. A tight system prompt (``prompts/normalization.py``) forbidding anything else.
2. JSON mode + ``temperature=0`` for a deterministic, structured answer.
3. Python validation of the returned label against the :class:`Intent` enum —
   anything unrecognised, empty, slow, or errored collapses to ``UNCLEAR``.

So even a misbehaving model cannot influence qualification: the decision is made
downstream in pure Python (``QualificationService`` + the state machine).
"""

from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod

from openai import AsyncOpenAI

from app.config.settings import Settings
from app.models.intent import Intent
from app.models.scenario import Question
from app.prompts.normalization import INTENT_NORMALIZATION_SYSTEM_PROMPT
from app.services.logger import get_logger


class IntentNormalizer(ABC):
    """Port: transcript + question context -> a single normalised Intent."""

    @abstractmethod
    async def normalize(self, transcript: str, question: Question) -> Intent:
        """Collapse a free-form transcript into one discrete intent.

        Args:
            transcript: Raw recognised speech for the current answer.
            question: The question being answered (light context only).

        Returns:
            Exactly one :class:`Intent`. Ambiguity resolves to ``UNCLEAR``.
        """
        raise NotImplementedError


class OpenAIIntentNormalizer(IntentNormalizer):
    """Adapter: OpenAI chat completion constrained to a 4-way classification."""

    def __init__(self, settings: Settings, *, client: AsyncOpenAI | None = None) -> None:
        """Store config; the client is built lazily (injectable for tests).

        Args:
            settings: Provides API key, model, and timeout.
            client: Optional pre-built async client (used by tests).
        """
        self._settings = settings
        self._client = client
        self._log = get_logger("openai")

    def _client_or_create(self) -> AsyncOpenAI:
        """Return the async client, constructing it on first use."""
        if self._client is None:
            key = self._settings.openai_api_key
            self._client = AsyncOpenAI(
                api_key=key.get_secret_value() if key else None,
                timeout=self._settings.openai_timeout_seconds,
            )
        return self._client

    async def normalize(self, transcript: str, question: Question) -> Intent:
        """Classify a transcript into one intent, never raising.

        An empty transcript short-circuits to ``UNCLEAR`` (no API round-trip).
        Any timeout or error also yields ``UNCLEAR`` so a flaky model degrades
        into a harmless re-prompt rather than a wrong decision.
        """
        cleaned = transcript.strip()
        if not cleaned:
            return Intent.UNCLEAR
        try:
            return await asyncio.wait_for(
                self._classify(cleaned, question),
                timeout=self._settings.openai_timeout_seconds,
            )
        except Exception as exc:  # deliberate catch-all: never let a vendor failure escape
            self._log.warning("openai.normalize_failed", error=str(exc))
            return Intent.UNCLEAR

    async def _classify(self, transcript: str, question: Question) -> Intent:
        """Perform the constrained OpenAI call and parse its label."""
        client = self._client_or_create()
        completion = await client.chat.completions.create(
            model=self._settings.openai_model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": INTENT_NORMALIZATION_SYSTEM_PROMPT},
                {"role": "user", "content": self._user_prompt(transcript, question)},
            ],
        )
        content = completion.choices[0].message.content or ""
        intent = self._parse_intent(content)
        self._log.debug("openai.normalized", intent=intent.value)
        return intent

    @staticmethod
    def _user_prompt(transcript: str, question: Question) -> str:
        """Render the minimal per-turn context for the classifier."""
        return (
            f'Question asked: "{question.prompt}"\n'
            f'Caller reply (transcribed): "{transcript}"\n'
            'Classify the reply. Respond as {"intent": "<LABEL>"}.'
        )

    @staticmethod
    def _parse_intent(content: str) -> Intent:
        """Map the model's JSON payload to a valid :class:`Intent`, else UNCLEAR.

        This is the final Python gate: any label outside the enum — however the
        model phrases it — becomes ``UNCLEAR``.
        """
        try:
            label = str(json.loads(content).get("intent", "")).strip().upper()
        except (json.JSONDecodeError, AttributeError, TypeError):
            return Intent.UNCLEAR
        try:
            return Intent(label)
        except ValueError:
            return Intent.UNCLEAR
