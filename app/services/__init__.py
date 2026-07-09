"""Service layer — ports (abstract interfaces) and adapters (implementations).

Every external capability the bot needs (telephony, STT, LLM, TTS) is defined
as an abstract *port* so the orchestration layer depends on interfaces, not
vendors. Concrete *adapters* (Twilio, Deepgram, OpenAI, ElevenLabs) implement
those ports and are swappable via the DI graph. The two pure-domain services —
``QualificationService`` (decisions) and ``ConversationService``
(orchestration) — contain no vendor code.
"""
