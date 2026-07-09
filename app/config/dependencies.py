"""Composition root — the dependency-injection graph.

FastAPI's ``Depends`` is used as a lightweight IoC container. This module is the
*only* place concrete adapters are bound to their ports, so swapping a vendor
(or a fake in tests) is a one-line change here and nowhere else. Wiring is
architecture, so it is implemented now even though the adapters it wires are
still skeletons.

Dependency direction (outermost → innermost), never the reverse:

    api / websocket  →  ConversationService  →  {ports}  →  models
                                            →  QualificationService (pure)
                                            →  ConversationStateMachine (pure)
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from app.config.settings import Settings, get_settings
from app.models.events import ConversationUpdate
from app.models.scenario import Scenario
from app.scenarios.registry import ScenarioRegistry
from app.services.conversation_service import ConversationService
from app.services.conversation_store import InMemoryConversationStore
from app.services.event_bus import EventPublisher, InMemoryEventBus
from app.services.logger import BoundLogger, get_logger
from app.services.openai_service import IntentNormalizer, OpenAIIntentNormalizer
from app.services.qualification_service import QualificationService
from app.services.stt_service import DeepgramSTTService, SpeechToTextService
from app.services.tts_service import (
    CartesiaTTSService,
    ElevenLabsTTSService,
    FallbackTTSService,
    OpenAITTSService,
    SystemTTSService,
    TextToSpeechService,
)
from app.services.twilio_service import TelephonyService, TwilioService
from app.state_machine.machine import ConversationStateMachine

# --- Settings ----------------------------------------------------------------
SettingsDep = Annotated[Settings, Depends(get_settings)]


# --- Singleton, stateless collaborators --------------------------------------
@lru_cache(maxsize=1)
def get_scenario_registry() -> ScenarioRegistry:
    """Provide the process-wide scenario catalogue (stateless, cacheable)."""
    return ScenarioRegistry()


@lru_cache(maxsize=1)
def get_qualification_service() -> QualificationService:
    """Provide the pure-Python qualification decider (stateless, cacheable)."""
    return QualificationService()


@lru_cache(maxsize=1)
def get_conversation_store() -> InMemoryConversationStore:
    """Provide the process-wide local-test conversation store (stateful, singleton)."""
    return InMemoryConversationStore()


@lru_cache(maxsize=1)
def get_event_bus() -> InMemoryEventBus[ConversationUpdate]:
    """Provide the process-wide dashboard snapshot bus (stateful, singleton).

    Shared by the producer (``ConversationService.run()``) and every consumer
    (``/dashboard/stream`` sockets), so a live call's snapshots reach connected
    dashboards. Transport only — it carries snapshots, it does not build them.
    """
    return InMemoryEventBus()


# --- Port bindings (adapter selection lives here and only here) --------------
def get_telephony_service(settings: SettingsDep) -> TelephonyService:
    """Bind the telephony port to the Twilio adapter."""
    return TwilioService(settings)


def get_stt_service(settings: SettingsDep) -> SpeechToTextService:
    """Bind the STT port to the Deepgram adapter (per-call: new connection)."""
    return DeepgramSTTService(settings)


def get_intent_normalizer(settings: SettingsDep) -> IntentNormalizer:
    """Bind the intent-normalisation port to the OpenAI adapter."""
    return OpenAIIntentNormalizer(settings)


def get_tts_service(settings: SettingsDep) -> TextToSpeechService:
    """Bind the TTS port to a priority-ordered vendor fallback chain.

    ElevenLabs (voice naturalness) -> Cartesia -> OpenAI TTS, each tried in
    order; a vendor outage, billing lapse, or auth failure on one tier falls
    through to the next rather than the call going silent. Cartesia has no
    safe default voice id (they're account-specific), so that tier is only
    included when one is actually configured. A local OS voice is appended
    as a last resort in development only — see
    ``Settings.allow_system_tts_fallback``.
    """
    tiers: list[tuple[str, TextToSpeechService]] = [
        ("elevenlabs", ElevenLabsTTSService(settings)),
    ]
    if settings.cartesia_configured:
        tiers.append(("cartesia", CartesiaTTSService(settings)))
    tiers.append(("openai", OpenAITTSService(settings)))
    if settings.allow_system_tts_fallback:
        tiers.append(("system", SystemTTSService(settings)))
    return FallbackTTSService(tiers)


# --- Pure collaborators as injected factories --------------------------------
def build_state_machine(scenario: Scenario) -> ConversationStateMachine:
    """Factory: a fresh per-call state machine for a scenario.

    Uses the default :class:`LinearQualificationPolicy` with the reprompt budget
    from settings. To run a flow with different control semantics, a caller can
    construct the machine with a custom policy instead — no change here required.
    """
    settings = get_settings()
    return ConversationStateMachine(scenario, max_reprompts=settings.max_reprompts)


# --- Aggregate: the conversation orchestrator --------------------------------
def get_conversation_service(
    settings: SettingsDep,
    stt: Annotated[SpeechToTextService, Depends(get_stt_service)],
    normalizer: Annotated[IntentNormalizer, Depends(get_intent_normalizer)],
    tts: Annotated[TextToSpeechService, Depends(get_tts_service)],
    qualification: Annotated[QualificationService, Depends(get_qualification_service)],
    telephony: Annotated[TelephonyService, Depends(get_telephony_service)],
    events: Annotated[EventPublisher[ConversationUpdate], Depends(get_event_bus)],
) -> ConversationService:
    """Assemble a per-call orchestrator from its injected collaborators."""
    logger: BoundLogger = get_logger("conversation")
    return ConversationService(
        stt=stt,
        normalizer=normalizer,
        tts=tts,
        qualification=qualification,
        machine_factory=build_state_machine,
        settings=settings,
        logger=logger,
        telephony=telephony,
        events=events,
    )


# --- Convenience annotated aliases for route signatures ----------------------
TelephonyDep = Annotated[TelephonyService, Depends(get_telephony_service)]
ScenarioRegistryDep = Annotated[ScenarioRegistry, Depends(get_scenario_registry)]
ConversationServiceDep = Annotated[ConversationService, Depends(get_conversation_service)]
ConversationStoreDep = Annotated[InMemoryConversationStore, Depends(get_conversation_store)]
EventBusDep = Annotated[InMemoryEventBus[ConversationUpdate], Depends(get_event_bus)]
