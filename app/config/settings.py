"""Application settings.

All configuration is sourced from environment variables (or a local ``.env``
file) and validated once at startup via ``pydantic-settings``. Nothing in the
codebase reads ``os.environ`` directly, and no secret is ever hardcoded — the
single ``Settings`` instance is the only gateway to configuration and is
injected wherever it is needed.

This module is pure infrastructure (no business logic) and is therefore fully
implemented at the scaffolding stage.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed, validated application configuration.

    Grouped by concern. Secrets use ``SecretStr`` so they are never
    accidentally serialised into logs or error messages.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---------------------------------------------------------
    app_name: str = "voice-qualification-bot"
    environment: Literal["local", "staging", "production"] = "local"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000
    public_base_url: str = Field(
        default="http://localhost:8000",
        description="Externally reachable base URL Twilio uses for webhooks/streams.",
    )
    cors_allowed_origins: str = Field(
        default="http://localhost:5173,http://localhost:5174,"
        "https://voice-qualification-bot.vercel.app",
        description=(
            "Comma-separated origins allowed to call this API cross-origin — "
            "the deployed frontend's URL(s) plus local Vite dev ports. The API "
            "and frontend are served from different domains in production "
            "(Render + Vercel), so this is required, not optional."
        ),
    )

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        """Parse ``cors_allowed_origins`` into the list ``CORSMiddleware`` expects."""
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    # --- Logging -------------------------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = Field(
        default=True,
        description="Emit structured JSON logs (True) or human-friendly console logs (False).",
    )

    # --- Conversation defaults ----------------------------------------------
    default_scenario_id: str = Field(
        default="lead_qualifier",
        description=(
            "Scenario served when a call does not specify one "
            "(e.g. 'lead_qualifier' or 'loan_qualifier')."
        ),
    )
    max_reprompts: int = Field(
        default=2,
        ge=0,
        description="How many times a single question may be re-asked on UNCLEAR before giving up.",
    )
    agent_transfer_number: str | None = Field(
        default=None,
        description=(
            "Destination phone number (E.164) ConversationService dials via "
            "TelephonyService.transfer_to_agent() on a qualified outcome. "
            "Unset skips the transfer attempt."
        ),
    )

    # --- Telephony (Twilio) --------------------------------------------------
    twilio_account_sid: SecretStr | None = None
    twilio_auth_token: SecretStr | None = None
    twilio_phone_number: str | None = None

    # --- Speech-to-Text (Deepgram) ------------------------------------------
    deepgram_api_key: SecretStr | None = None
    deepgram_model: str = "nova-2-phonecall"
    deepgram_language: str = "en"

    # --- LLM intent normalisation (OpenAI) ----------------------------------
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o-mini"
    openai_timeout_seconds: float = Field(default=3.0, gt=0)

    # --- Text-to-Speech (ElevenLabs) -----------------------------------------
    # Primary TTS provider, chosen over Deepgram Aura for voice naturalness;
    # STT stays on Deepgram. First tier of the TTS fallback chain — see
    # app/services/tts_service.py:FallbackTTSService.
    elevenlabs_api_key: SecretStr | None = None
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"  # premade voice "Rachel"
    elevenlabs_model: str = "eleven_flash_v2_5"
    elevenlabs_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        description="Max time to wait for one utterance's audio before giving up.",
    )

    # --- Text-to-Speech (Cartesia) -- fallback tier 2 -------------------------
    # Tried when ElevenLabs errors (billing/auth or otherwise). No default
    # voice id is provided: Cartesia voices are account-specific, so an unset
    # id means this tier is skipped rather than guessing a voice that may not
    # exist on the caller's account.
    cartesia_api_key: SecretStr | None = None
    cartesia_voice_id: str | None = None
    cartesia_model: str = "sonic-3"
    cartesia_timeout_seconds: float = Field(default=10.0, gt=0)

    # --- Text-to-Speech (OpenAI) -- fallback tier 3 ---------------------------
    # Reuses openai_api_key (already required for the intent classifier).
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "coral"
    openai_tts_timeout_seconds: float = Field(default=10.0, gt=0)

    @property
    def is_production(self) -> bool:
        """Return ``True`` when running in the production environment."""
        return self.environment == "production"

    @property
    def twilio_configured(self) -> bool:
        """Whether real Twilio credentials (account SID + auth token) are configured."""
        return bool(self.twilio_account_sid and self.twilio_auth_token)

    @property
    def openai_configured(self) -> bool:
        """Whether an OpenAI API key is configured."""
        return bool(self.openai_api_key)

    @property
    def deepgram_configured(self) -> bool:
        """Whether a Deepgram API key is configured."""
        return bool(self.deepgram_api_key)

    @property
    def elevenlabs_configured(self) -> bool:
        """Whether an ElevenLabs API key is configured."""
        return bool(self.elevenlabs_api_key)

    @property
    def cartesia_configured(self) -> bool:
        """Whether Cartesia is usable: both an API key and a voice id are set."""
        return bool(self.cartesia_api_key and self.cartesia_voice_id)

    @property
    def allow_system_tts_fallback(self) -> bool:
        """Whether the last-resort local OS TTS fallback may run.

        Development only — this must never be reachable in staging/production,
        since it speaks with the host machine's local voice, not a real vendor.
        """
        return self.environment == "local"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide, lazily-instantiated ``Settings`` singleton.

    Cached so environment parsing and validation happen exactly once. This is
    the composition-root entry point consumed by the DI graph in
    ``app.config.dependencies``.
    """
    return Settings()
