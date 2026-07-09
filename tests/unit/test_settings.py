"""Settings vendor-configuration-presence tests.

Every case explicitly overrides all four vendor credential fields — never
relying on the ambient environment or a real ``.env`` file — since this
machine's local ``.env`` may hold live credentials (see conftest/other test
files) and explicit constructor kwargs are the only reliable way to force a
"nothing configured" scenario regardless of what's on disk.
"""

from __future__ import annotations

from app.config.settings import Settings

_NONE_CONFIGURED: dict[str, object] = {
    "twilio_account_sid": None,
    "twilio_auth_token": None,
    "openai_api_key": None,
    "deepgram_api_key": None,
    "elevenlabs_api_key": None,
    "cartesia_api_key": None,
    "cartesia_voice_id": None,
}


def test_nothing_configured_reports_all_false() -> None:
    settings = Settings(**_NONE_CONFIGURED)
    assert settings.twilio_configured is False
    assert settings.openai_configured is False
    assert settings.deepgram_configured is False
    assert settings.elevenlabs_configured is False
    assert settings.cartesia_configured is False


def test_everything_configured_reports_all_true() -> None:
    settings = Settings(
        twilio_account_sid="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        twilio_auth_token="x" * 32,
        openai_api_key="sk-test",
        deepgram_api_key="dg-test",
        elevenlabs_api_key="el-test",
        cartesia_api_key="ck-test",
        cartesia_voice_id="voice-123",
    )
    assert settings.twilio_configured is True
    assert settings.openai_configured is True
    assert settings.deepgram_configured is True
    assert settings.elevenlabs_configured is True
    assert settings.cartesia_configured is True


def test_twilio_requires_both_sid_and_token() -> None:
    only_sid = Settings(**{**_NONE_CONFIGURED, "twilio_account_sid": "ACxxxx"})
    assert only_sid.twilio_configured is False

    only_token = Settings(**{**_NONE_CONFIGURED, "twilio_auth_token": "x" * 32})
    assert only_token.twilio_configured is False


def test_cartesia_requires_both_key_and_voice_id() -> None:
    only_key = Settings(**{**_NONE_CONFIGURED, "cartesia_api_key": "ck-test"})
    assert only_key.cartesia_configured is False

    only_voice = Settings(**{**_NONE_CONFIGURED, "cartesia_voice_id": "voice-123"})
    assert only_voice.cartesia_configured is False


def test_system_tts_fallback_allowed_only_in_local_environment() -> None:
    assert Settings(environment="local").allow_system_tts_fallback is True
    assert Settings(environment="staging").allow_system_tts_fallback is False
    assert Settings(environment="production").allow_system_tts_fallback is False
