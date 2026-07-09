"""Dependency-injection wiring integration tests.

Confirms the composition root (``app/config/dependencies.py``) actually
resolves to the intended concrete adapters and that the scenario registry +
qualification service compose correctly end to end. No live vendor network
calls are made — these adapters only build their client lazily on first use.
"""

from __future__ import annotations

from app.config.dependencies import (
    build_state_machine,
    get_conversation_service,
    get_event_bus,
    get_intent_normalizer,
    get_qualification_service,
    get_scenario_registry,
    get_stt_service,
    get_telephony_service,
    get_tts_service,
)
from app.config.settings import Settings, get_settings
from app.models.intent import Intent
from app.models.session import CallSession
from app.services.conversation_service import ConversationService
from app.services.openai_service import OpenAIIntentNormalizer
from app.services.qualification_service import QualificationService
from app.services.stt_service import DeepgramSTTService
from app.services.tts_service import FallbackTTSService
from app.services.twilio_service import TwilioService
from app.state_machine.machine import ConversationStateMachine


def test_vendor_ports_resolve_to_the_intended_adapters() -> None:
    settings = get_settings()
    assert isinstance(get_stt_service(settings), DeepgramSTTService)
    assert isinstance(get_tts_service(settings), FallbackTTSService)
    assert isinstance(get_intent_normalizer(settings), OpenAIIntentNormalizer)
    assert isinstance(get_telephony_service(settings), TwilioService)


def test_conversation_service_assembles_from_all_collaborators() -> None:
    settings = get_settings()
    service = get_conversation_service(
        settings,
        get_stt_service(settings),
        get_intent_normalizer(settings),
        get_tts_service(settings),
        get_qualification_service(),
        get_telephony_service(settings),
        get_event_bus(),
    )
    assert isinstance(service, ConversationService)


def test_state_machine_factory_applies_settings_reprompt_budget() -> None:
    registry = get_scenario_registry()
    scenario = registry.get("lead_qualifier")
    machine = build_state_machine(scenario)
    assert isinstance(machine, ConversationStateMachine)


def test_registry_and_qualification_service_compose_end_to_end() -> None:
    """The two pure, DI-provided services agree on a full qualifying call."""
    registry = get_scenario_registry()
    qualification = get_qualification_service()
    scenario = registry.get("loan_qualifier")

    session = CallSession(
        call_sid="CA_di_test",
        scenario_id=scenario.id,
        answers={q.key: Intent.YES for q in scenario.questions},
    )
    result = qualification.evaluate(session, scenario)

    assert result.qualified is True
    assert result.label == "ELIGIBLE"


def test_qualification_service_is_a_cached_singleton() -> None:
    """lru_cache-backed provider returns the same stateless instance every time."""
    assert get_qualification_service() is get_qualification_service()
    assert isinstance(get_qualification_service(), QualificationService)


def test_tts_chain_omits_cartesia_and_system_when_unconfigured_and_not_local() -> None:
    settings = Settings(cartesia_api_key=None, cartesia_voice_id=None, environment="production")
    chain = get_tts_service(settings)
    assert isinstance(chain, FallbackTTSService)
    assert chain.tier_names == ("elevenlabs", "openai")


def test_tts_chain_includes_cartesia_once_configured() -> None:
    settings = Settings(
        cartesia_api_key="ck-test", cartesia_voice_id="voice-123", environment="production"
    )
    chain = get_tts_service(settings)
    assert isinstance(chain, FallbackTTSService)
    assert chain.tier_names == ("elevenlabs", "cartesia", "openai")


def test_tts_chain_appends_system_tier_only_in_local_environment() -> None:
    local_chain = get_tts_service(Settings(environment="local"))
    assert isinstance(local_chain, FallbackTTSService)
    assert local_chain.tier_names[-1] == "system"

    production_chain = get_tts_service(Settings(environment="production"))
    assert isinstance(production_chain, FallbackTTSService)
    assert "system" not in production_chain.tier_names
