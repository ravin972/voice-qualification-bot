"""Tests for the OpenAI intent normaliser.

These tests are the proof of the project's core constraint: the LLM is a
classifier only, and Python is the final gate on its output. A fake OpenAI
client (no network) lets us assert that malformed, unexpected, slow, or
outright hostile model output always collapses to a safe ``Intent`` — never an
exception, and never anything outside the closed four-value enum.
"""

from __future__ import annotations

import asyncio

import pytest
from app.config.settings import Settings
from app.models.intent import Intent
from app.models.scenario import Question
from app.services.openai_service import OpenAIIntentNormalizer


class _FakeMessage:
    def __init__(self, content: str | None) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str | None) -> None:
        self.message = _FakeMessage(content)


class _FakeCompletion:
    def __init__(self, content: str | None) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    """Stands in for ``client.chat.completions``."""

    def __init__(
        self,
        content: str | None = None,
        exc: Exception | None = None,
        delay: float = 0.0,
    ) -> None:
        self.content = content
        self.exc = exc
        self.delay = delay
        self.call_count = 0

    async def create(self, **_kwargs: object) -> _FakeCompletion:
        self.call_count += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc is not None:
            raise self.exc
        return _FakeCompletion(self.content)


class _FakeChat:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions


class FakeAsyncOpenAI:
    """Minimal duck-typed stand-in for ``openai.AsyncOpenAI``."""

    def __init__(
        self, content: str | None = None, exc: Exception | None = None, delay: float = 0.0
    ) -> None:
        self.completions = _FakeCompletions(content, exc, delay)
        self.chat = _FakeChat(self.completions)


@pytest.fixture
def question() -> Question:
    return Question(key="owns_home", prompt="Do you own your home?")


@pytest.fixture
def settings() -> Settings:
    return Settings(openai_timeout_seconds=1.0)


def _normalizer(settings: Settings, fake_client: FakeAsyncOpenAI) -> OpenAIIntentNormalizer:
    return OpenAIIntentNormalizer(settings, client=fake_client)  # type: ignore[arg-type]


# --- Correct classification -------------------------------------------------
@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ('{"intent": "YES"}', Intent.YES),
        ('{"intent": "NO"}', Intent.NO),
        ('{"intent": "REPEAT"}', Intent.REPEAT),
        ('{"intent": "UNCLEAR"}', Intent.UNCLEAR),
    ],
)
async def test_valid_labels_map_to_matching_intent(
    settings: Settings, question: Question, content: str, expected: Intent
) -> None:
    fake = FakeAsyncOpenAI(content=content)
    result = await _normalizer(settings, fake).normalize("yes I do", question)
    assert result is expected


async def test_lowercase_label_is_normalized(settings: Settings, question: Question) -> None:
    """The model may not respect casing; Python normalises before validating."""
    fake = FakeAsyncOpenAI(content='{"intent": "yes"}')
    result = await _normalizer(settings, fake).normalize("yeah", question)
    assert result is Intent.YES


# --- Python is the final gate: never trust the model blindly ---------------
async def test_unknown_label_becomes_unclear(settings: Settings, question: Question) -> None:
    """A label outside {YES,NO,REPEAT,UNCLEAR} can never leak through."""
    fake = FakeAsyncOpenAI(content='{"intent": "MAYBE"}')
    result = await _normalizer(settings, fake).normalize("kind of", question)
    assert result is Intent.UNCLEAR


async def test_malformed_json_becomes_unclear(settings: Settings, question: Question) -> None:
    fake = FakeAsyncOpenAI(content="not json at all")
    result = await _normalizer(settings, fake).normalize("huh?", question)
    assert result is Intent.UNCLEAR


async def test_missing_intent_key_becomes_unclear(settings: Settings, question: Question) -> None:
    fake = FakeAsyncOpenAI(content='{"foo": "bar"}')
    result = await _normalizer(settings, fake).normalize("something", question)
    assert result is Intent.UNCLEAR


async def test_empty_completion_content_becomes_unclear(
    settings: Settings, question: Question
) -> None:
    fake = FakeAsyncOpenAI(content=None)
    result = await _normalizer(settings, fake).normalize("something", question)
    assert result is Intent.UNCLEAR


# --- Resilience: vendor failures never escape or hang -----------------------
async def test_empty_transcript_short_circuits_without_calling_api(
    settings: Settings, question: Question
) -> None:
    fake = FakeAsyncOpenAI(content='{"intent": "YES"}')
    result = await _normalizer(settings, fake).normalize("   ", question)
    assert result is Intent.UNCLEAR
    assert fake.completions.call_count == 0


async def test_provider_exception_becomes_unclear_not_raised(
    settings: Settings, question: Question
) -> None:
    fake = FakeAsyncOpenAI(exc=RuntimeError("provider is down"))
    result = await _normalizer(settings, fake).normalize("yes", question)
    assert result is Intent.UNCLEAR


async def test_slow_provider_times_out_to_unclear(question: Question) -> None:
    """A response slower than the configured timeout must not hang the call."""
    settings = Settings(openai_timeout_seconds=0.05)
    fake = FakeAsyncOpenAI(content='{"intent": "YES"}', delay=1.0)
    result = await _normalizer(settings, fake).normalize("yes", question)
    assert result is Intent.UNCLEAR


# --- Business-logic boundary: normalize() never decides eligibility --------
def test_intent_enum_is_closed_to_exactly_four_values() -> None:
    """The classifier's entire vocabulary is fixed; nothing else can appear."""
    assert Intent.choices() == ("YES", "NO", "REPEAT", "UNCLEAR")
