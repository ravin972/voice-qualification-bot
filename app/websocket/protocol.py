"""Twilio Media Streams wire protocol.

Typed models for the JSON frames Twilio sends over the media WebSocket, plus
builders for the frames we send back. Keeping the vendor-specific wire format
here (at the edge) keeps the domain models in ``app.models`` transport-agnostic.

Reference: https://www.twilio.com/docs/voice/media-streams/websocket-messages
This module is pure transport (no conversation logic).
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TwilioEvent(str, Enum):
    """The ``event`` discriminator on every inbound Twilio frame."""

    CONNECTED = "connected"
    START = "start"
    MEDIA = "media"
    MARK = "mark"
    DTMF = "dtmf"
    STOP = "stop"


class _WireModel(BaseModel):
    """Base for wire models: accept Twilio's camelCase, ignore unknown keys."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class MediaFormat(_WireModel):
    """Audio format announced in the ``start`` frame (typically 8 kHz μ-law)."""

    encoding: str
    sample_rate: int = Field(alias="sampleRate")
    channels: int


class StartMetadata(_WireModel):
    """Payload of the ``start`` frame: identifiers and stream parameters."""

    stream_sid: str = Field(alias="streamSid")
    call_sid: str = Field(alias="callSid")
    account_sid: str | None = Field(default=None, alias="accountSid")
    tracks: list[str] = Field(default_factory=list)
    custom_parameters: dict[str, str] = Field(default_factory=dict, alias="customParameters")
    media_format: MediaFormat | None = Field(default=None, alias="mediaFormat")


class MediaPayload(_WireModel):
    """Payload of a ``media`` frame: one base64-encoded μ-law audio chunk."""

    track: str | None = None
    chunk: str | None = None
    timestamp: str | None = None
    payload: str


class MarkPayload(_WireModel):
    """Payload of a ``mark`` frame: an echo label for playback checkpoints."""

    name: str


class StopMetadata(_WireModel):
    """Payload of the ``stop`` frame: emitted when the stream ends."""

    account_sid: str | None = Field(default=None, alias="accountSid")
    call_sid: str | None = Field(default=None, alias="callSid")


class InboundFrame(_WireModel):
    """A single decoded inbound frame. Only the sub-field for ``event`` is set."""

    event: TwilioEvent
    sequence_number: str | None = Field(default=None, alias="sequenceNumber")
    stream_sid: str | None = Field(default=None, alias="streamSid")
    start: StartMetadata | None = None
    media: MediaPayload | None = None
    mark: MarkPayload | None = None
    stop: StopMetadata | None = None


# --- Outbound frame builders (used by the conversation phase to talk back) ---
def outbound_media(stream_sid: str, payload_b64: str) -> dict[str, Any]:
    """Build a ``media`` frame that plays base64 μ-law audio to the caller."""
    return {"event": "media", "streamSid": stream_sid, "media": {"payload": payload_b64}}


def outbound_mark(stream_sid: str, name: str) -> dict[str, Any]:
    """Build a ``mark`` frame to checkpoint playback (echoed back by Twilio)."""
    return {"event": "mark", "streamSid": stream_sid, "mark": {"name": name}}


def outbound_clear(stream_sid: str) -> dict[str, Any]:
    """Build a ``clear`` frame to flush buffered outbound audio (barge-in)."""
    return {"event": "clear", "streamSid": stream_sid}
