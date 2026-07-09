"""Conversation orchestrator — wires the pipeline together.

This is the async heart of a call. For one media stream it coordinates:

    inbound audio ──▶ STT ──▶ IntentNormalizer ──▶ StateMachine
                                                        │
    outbound audio ◀── TTS ◀── next line ◀── QualificationService

It depends only on *ports* (interfaces) plus the pure state machine and
qualification service — never on a concrete vendor. No business rule lives
here: the state machine owns control flow, ``QualificationService`` owns the
verdict; this class only sequences calls to them and to STT/TTS.

The per-turn decision logic (normalize → fire the state machine → decide what
to say next) is audio-agnostic and lives in ``_process_transcript``/``_conclude``/
``_advance_question``/``_end_call``, all of which return plain text. ``run()``
is a thin wrapper that speaks those lines over TTS for a live call; the
``start_test_conversation``/``submit_test_message`` methods reuse the exact
same core to drive a conversation over plain HTTP text, for local testing
without Twilio, WebSockets, Deepgram, or a TTS vendor.

``run()`` also publishes an immutable ``ConversationUpdate`` snapshot after
every meaningful turn to an injected ``EventPublisher`` (default: a no-op), for
a dashboard to observe a live call — pure side-observation, never a dependency
of the call itself. See ``app/services/event_bus.py`` and ``app/models/events.py``.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from typing import cast

from app.config.settings import Settings
from app.models.audio import AudioChunk, Transcript
from app.models.events import ConversationUpdate, Speaker, TranscriptLine, build_conversation_update
from app.models.scenario import Scenario
from app.models.session import CallSession, Turn, TurnLatency
from app.services.event_bus import EventPublisher, NullEventPublisher
from app.services.logger import BoundLogger
from app.services.openai_service import IntentNormalizer
from app.services.qualification_service import QualificationService
from app.services.stt_service import SpeechToTextService
from app.services.tts_service import TextToSpeechService
from app.services.twilio_service import TelephonyService
from app.state_machine.events import Trigger
from app.state_machine.machine import ConversationStateMachine
from app.state_machine.states import State
from app.utils.timing import measure

#: Factory that builds a fresh state machine per call (injected for testability).
StateMachineFactory = Callable[[Scenario], ConversationStateMachine]

#: Sink the orchestrator pushes outbound audio chunks to (e.g. the media WebSocket).
AudioSink = Callable[[AudioChunk], Awaitable[None]]

#: FSM states where the caller has reached a final qualify/reject decision.
_DECISION_STATES = (State.QUALIFIED, State.REJECTED)

#: Shared no-op publisher used when no dashboard bus is injected (stateless).
_NULL_EVENT_PUBLISHER: EventPublisher[ConversationUpdate] = NullEventPublisher()


class ConversationService:
    """Orchestrates a single call end-to-end, over either a media stream or plain text."""

    def __init__(
        self,
        *,
        stt: SpeechToTextService,
        normalizer: IntentNormalizer,
        tts: TextToSpeechService,
        qualification: QualificationService,
        machine_factory: StateMachineFactory,
        settings: Settings,
        logger: BoundLogger,
        telephony: TelephonyService | None = None,
        events: EventPublisher[ConversationUpdate] | None = None,
    ) -> None:
        """Inject every collaborator as an interface (dependency inversion).

        Args:
            stt: Speech-to-text port.
            normalizer: LLM intent-normalisation port.
            tts: Text-to-speech port.
            qualification: Pure-Python decision service.
            machine_factory: Builds a per-call state machine.
            settings: Runtime configuration (reprompt limits, defaults).
            logger: Structured logger, typically pre-bound with the call SID.
            telephony: Optional telephony port. When provided and
                ``settings.agent_transfer_number`` is set, a qualified outcome
                triggers a warm transfer.
            events: Optional dashboard snapshot publisher. When omitted, a no-op
                publisher is used and ``run()`` behaves exactly as before —
                observation is purely additive and never affects the call.
        """
        self._stt = stt
        self._normalizer = normalizer
        self._tts = tts
        self._qualification = qualification
        self._machine_factory = machine_factory
        self._settings = settings
        self._log = logger
        self._telephony = telephony
        self._events = events or _NULL_EVENT_PUBLISHER

    # --- Live call: audio in, audio out ------------------------------------

    async def run(
        self,
        session: CallSession,
        scenario: Scenario,
        audio_in: AsyncIterator[AudioChunk],
        audio_out: AudioSink,
    ) -> CallSession:
        """Drive the full conversation for one call until a terminal state.

        Args:
            session: The freshly-created call session (state ``START``).
            scenario: The flow to run.
            audio_in: Inbound caller audio, forwarded to the STT port.
            audio_out: Sink for outbound synthesised audio (e.g. the media
                WebSocket). Called once per audio chunk as TTS produces it.

        Returns:
            The same session, mutated with answers, turns, and final result.
        """
        machine = self._machine_factory(scenario)
        transcript_lines: list[TranscriptLine] = []
        sequence = 0

        async def emit(speaker: Speaker, message: str) -> None:
            """Publish one immutable dashboard snapshot for a spoken/heard line."""
            nonlocal sequence
            sequence += 1
            transcript_lines.append(TranscriptLine(speaker=speaker, message=message))
            await self._publish_snapshot(
                session, scenario, speaker, message, sequence, transcript_lines
            )

        await self._speak(session, scenario.script.greeting, audio_out)
        await emit("bot", scenario.script.greeting)
        machine.fire(Trigger.CALL_STARTED)
        session.state = machine.current_state
        question = self._advance_question(session, machine, scenario)
        if question is not None:
            await self._speak(session, question, audio_out)
            await emit("bot", question)

        # Ports declare `AsyncIterator` (the abstract protocol); every concrete
        # adapter is a real async generator with `.aclose()`, which `aclosing()`
        # needs for prompt cleanup on early exit (see stt_service.py's docstring).
        transcript_stream = cast(AsyncGenerator[Transcript, None], self._stt.stream(audio_in))
        async with contextlib.aclosing(transcript_stream) as transcripts:
            while True:
                async with measure(self._log, "stt", **self._log_context(session)) as stt_m:
                    transcript = await self._next_final_transcript(transcripts)
                if transcript is None:
                    break  # audio ended without another final transcript (e.g. hangup)

                tts_ms: float | None = None
                turn_ctx = self._log_context(session)
                async with measure(self._log, "turn_total", **turn_ctx) as total_m:
                    lines, decided, llm_ms = await self._process_transcript(
                        session, scenario, machine, transcript
                    )
                    await emit("caller", transcript.text)
                    for line in lines:
                        tts_ms = await self._speak(session, line, audio_out)
                session.last_turn_latency = TurnLatency(
                    stt_ms=stt_m.latency_ms,
                    llm_ms=llm_ms,
                    tts_ms=tts_ms,
                    total_ms=total_m.latency_ms,
                )
                for line in lines:
                    await emit("bot", line)
                if decided:
                    break

        goodbye = self._end_call(session, machine, scenario)
        await self._speak(session, goodbye, audio_out)
        await emit("bot", goodbye)
        return session

    @staticmethod
    async def _next_final_transcript(
        transcripts: AsyncIterator[Transcript],
    ) -> Transcript | None:
        """Pull from the STT stream until a final transcript arrives, or it ends."""
        async for transcript in transcripts:
            if transcript.is_final:
                return transcript
        return None

    @staticmethod
    def _log_context(session: CallSession) -> dict[str, str]:
        """Identifiers attached to every latency log line for this call.

        ``conversation_id`` and ``call_sid`` are the same value today —
        ``CallSession`` has no separate conversation identifier — but both keys
        are logged since callers may reasonably expect either name.
        """
        return {"conversation_id": session.call_sid, "call_sid": session.call_sid}

    async def _publish_snapshot(
        self,
        session: CallSession,
        scenario: Scenario,
        speaker: Speaker,
        message: str,
        sequence: int,
        transcript: list[TranscriptLine],
    ) -> None:
        """Build and publish one dashboard snapshot; observation must never break the call.

        Pure side-observation: reads already-computed state off ``session`` and
        hands an immutable snapshot to the injected publisher. Any failure here
        (a misbehaving bus, a serialisation slip) is swallowed and logged so it
        can never affect the live call. A no-op publisher makes this a cheap
        object construction that goes nowhere.
        """
        try:
            update = build_conversation_update(
                session=session,
                scenario=scenario,
                speaker=speaker,
                message=message,
                sequence=sequence,
                transcript=transcript,
            )
            await self._events.publish(update)
        except Exception:  # deliberate catch-all: observing a call must never crash it
            self._log.warning("conversation.snapshot_publish_failed", exc_info=True)

    # --- Local testing: plain text in, plain text out ----------------------

    async def start_test_conversation(
        self, session: CallSession, scenario: Scenario
    ) -> tuple[ConversationStateMachine, list[str]]:
        """Begin a conversation without any audio, STT, or TTS.

        Args:
            session: The freshly-created call session (state ``START``).
            scenario: The flow to run.

        Returns:
            The state machine (the caller must retain it and pass it back into
            :meth:`submit_test_message` for every subsequent turn of this
            conversation) and the lines the bot "says" — greeting then the
            first question.
        """
        machine = self._machine_factory(scenario)
        lines = [scenario.script.greeting]
        machine.fire(Trigger.CALL_STARTED)
        session.state = machine.current_state
        question = self._advance_question(session, machine, scenario)
        if question is not None:
            lines.append(question)
        return machine, lines

    async def submit_test_message(
        self,
        session: CallSession,
        scenario: Scenario,
        machine: ConversationStateMachine,
        text: str,
    ) -> tuple[list[str], bool]:
        """Process one turn of plain text, as if it were a finalised STT transcript.

        Runs through the exact same decision core as a live call (normalise via
        the real LLM classifier, advance the real state machine, decide the
        verdict via the real qualification service) — only the audio in/out is
        skipped.

        Args:
            session: The in-progress call session.
            scenario: The flow being run (must match what ``session``/``machine``
                were started with).
            machine: The state machine returned by :meth:`start_test_conversation`.
            text: The simulated caller utterance.

        Returns:
            The line(s) the bot says in response, and whether the conversation
            has now ended (no further messages will be accepted).
        """
        transcript = Transcript(text=text, is_final=True)
        async with measure(self._log, "turn_total", **self._log_context(session)) as total_m:
            lines, decided, llm_ms = await self._process_transcript(
                session, scenario, machine, transcript
            )
        session.last_turn_latency = TurnLatency(llm_ms=llm_ms, total_ms=total_m.latency_ms)
        if decided:
            lines = [*lines, self._end_call(session, machine, scenario)]
        return lines, decided

    # --- Shared decision core (audio-agnostic) ------------------------------

    async def _process_transcript(
        self,
        session: CallSession,
        scenario: Scenario,
        machine: ConversationStateMachine,
        transcript: Transcript,
    ) -> tuple[list[str], bool, float | None]:
        """Process one final transcript against the current question.

        Returns the line(s) to say next, whether a decision (``QUALIFIED``/
        ``REJECTED``) was reached this turn, and the LLM classification latency
        in milliseconds. Never touches audio — callers decide how to deliver
        the returned lines.
        """
        question_index = machine.current_question_index
        if question_index is None:
            self._log.warning("conversation.stray_transcript", state=machine.current_state.value)
            return [], False, None
        question = scenario.questions[question_index]

        async with measure(self._log, "llm", **self._log_context(session)) as llm_m:
            intent = await self._normalizer.normalize(transcript.text, question)
        trigger = Trigger.from_intent(intent)
        if trigger in (Trigger.ANSWER_YES, Trigger.ANSWER_NO):
            session.answers[question.key] = intent

        if not machine.can_fire(trigger):
            self._log.warning(
                "conversation.illegal_trigger",
                state=machine.current_state.value,
                trigger=trigger.value,
            )
            return [], False, llm_m.latency_ms

        previous_state = machine.current_state
        new_state = machine.fire(trigger)
        session.turns.append(
            Turn(
                question_key=question.key,
                transcript=transcript,
                intent=intent,
                reprompts=machine.reprompts,
            )
        )
        session.state = new_state

        if new_state == previous_state:
            return [scenario.script.reprompt_unclear], False, llm_m.latency_ms
        if new_state in _DECISION_STATES:
            return [await self._conclude(session, scenario)], True, llm_m.latency_ms
        question_line = self._advance_question(session, machine, scenario)
        return (
            [question_line] if question_line is not None else [],
            False,
            llm_m.latency_ms,
        )

    async def _conclude(self, session: CallSession, scenario: Scenario) -> str:
        """Evaluate the qualification verdict (pure Python) and return the outcome line."""
        session.result = self._qualification.evaluate(session, scenario)
        if session.result.qualified:
            await self._maybe_transfer(session)
            return scenario.script.qualified
        return scenario.script.rejected

    async def _maybe_transfer(self, session: CallSession) -> None:
        """Warm-transfer a qualified call when telephony + a destination are configured."""
        agent_number = self._settings.agent_transfer_number
        if self._telephony is None or not agent_number:
            return
        await self._telephony.transfer_to_agent(session.call_sid, agent_number)

    def _end_call(
        self, session: CallSession, machine: ConversationStateMachine, scenario: Scenario
    ) -> str:
        """Reach ``ENDED`` (firing ``HANGUP`` if not already terminal) and return the goodbye."""
        if not machine.is_terminal and machine.can_fire(Trigger.HANGUP):
            machine.fire(Trigger.HANGUP)
        session.state = machine.current_state
        return scenario.script.goodbye

    def _advance_question(
        self, session: CallSession, machine: ConversationStateMachine, scenario: Scenario
    ) -> str | None:
        """Record the machine's current question index and return that question's prompt."""
        index = machine.current_question_index
        if index is None:
            return None
        session.current_question_index = index
        return scenario.questions[index].prompt

    # --- Audio delivery (live call only) ------------------------------------

    async def _speak(self, session: CallSession, text: str, audio_out: AudioSink) -> float | None:
        """Synthesise ``text`` (TTS), forward every chunk to ``audio_out``, and return latency."""
        async with measure(self._log, "tts", **self._log_context(session)) as tts_m:
            audio_stream = cast(AsyncGenerator[AudioChunk, None], self._tts.synthesize(text))
            async with contextlib.aclosing(audio_stream) as chunks:
                async for chunk in chunks:
                    await audio_out(chunk)
        return tts_m.latency_ms
