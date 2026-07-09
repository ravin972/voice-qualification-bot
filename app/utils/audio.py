"""Audio transcoding helpers.

Bridges telephony and provider encodings — Twilio streams 8 kHz μ-law while STT
and TTS providers often expect/emit 16 kHz PCM or MP3. Isolated here so codec
concerns never leak into the orchestration logic.

In this pipeline, Deepgram (STT) is configured for native μ-law/8kHz input and
ElevenLabs (TTS) is configured to emit native μ-law/8kHz output (see
``stt_service.py``/``tts_service.py``), so the only conversion actually needed
at the Twilio boundary is base64 <-> raw bytes framing, not a codec transcode.
"""

from __future__ import annotations

import base64

from app.models.audio import AudioChunk, AudioEncoding


def transcode(chunk: AudioChunk, target: AudioEncoding) -> AudioChunk:
    """Convert an audio chunk to the target encoding.

    Args:
        chunk: Source audio.
        target: Desired output encoding.

    Returns:
        A new :class:`AudioChunk` in the target encoding.
    """
    raise NotImplementedError("Transcoding pending (logic phase).")


def decode_twilio_media(payload_b64: str) -> AudioChunk:
    """Decode a base64 μ-law payload from a Twilio media message.

    Args:
        payload_b64: Base64 string from a Twilio ``media`` event.

    Returns:
        A decoded :class:`AudioChunk`.
    """
    return AudioChunk(payload=base64.b64decode(payload_b64), encoding=AudioEncoding.MULAW_8000)


def encode_twilio_media(chunk: AudioChunk) -> str:
    """Base64-encode a synthesised audio chunk for an outbound Twilio media frame.

    Args:
        chunk: Audio produced by the TTS adapter (already μ-law/8kHz).

    Returns:
        The base64 string a Twilio ``media`` frame payload expects.
    """
    return base64.b64encode(chunk.payload).decode("ascii")
