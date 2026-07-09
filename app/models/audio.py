"""Audio and transcription value objects.

These describe the bytes flowing over the Twilio Media Stream and the text
coming back from the STT adapter. They are transport-agnostic so alternative
telephony or STT providers can be dropped in without touching the domain.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class AudioEncoding(str, Enum):
    """Wire encodings the pipeline understands.

    Twilio Media Streams deliver 8 kHz mono ``audio/x-mulaw``; TTS providers
    typically return PCM or MP3 which the adapters transcode as needed.
    """

    MULAW_8000 = "audio/x-mulaw;rate=8000"
    PCM_16000 = "audio/l16;rate=16000"
    MP3 = "audio/mpeg"


class AudioChunk(BaseModel):
    """A single frame of audio flowing in either direction."""

    payload: bytes = Field(description="Raw audio bytes (already base64-decoded).")
    encoding: AudioEncoding = AudioEncoding.MULAW_8000
    sequence: int | None = Field(
        default=None, description="Monotonic frame index from the media stream, if known."
    )


class Transcript(BaseModel):
    """A recognised utterance emitted by the STT adapter."""

    text: str
    is_final: bool = Field(
        default=False,
        description="True once the STT provider marks the utterance complete (endpointing).",
    )
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
