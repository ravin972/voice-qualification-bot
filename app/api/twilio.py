"""Twilio voice webhook.

Twilio hits ``POST /twilio/voice`` when a call arrives; we answer with TwiML
that opens a Media Stream back to our WebSocket. TwiML construction is delegated
to the telephony port. This is transport/wiring only — no conversation logic.
"""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, Response

from app.config.dependencies import SettingsDep, TelephonyDep
from app.services.logger import get_logger

router = APIRouter(prefix="/twilio", tags=["twilio"])

_MEDIA_STREAM_PATH = "/media-stream"


def _websocket_url(base_url: str, path: str) -> str:
    """Derive the public ``ws(s)://`` media-stream URL from the HTTP base URL.

    Args:
        base_url: Externally reachable HTTP(S) base URL (from settings).
        path: WebSocket route path to append.

    Returns:
        A ``wss://`` URL for HTTPS bases, otherwise ``ws://``.
    """
    parsed = urlparse(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    netloc = parsed.netloc or parsed.path  # tolerate a scheme-less base URL
    return f"{scheme}://{netloc}{path}"


@router.post("/voice", summary="Inbound call webhook → returns streaming TwiML")
async def inbound_voice(
    settings: SettingsDep,
    telephony: TelephonyDep,
    scenario: str | None = None,
) -> Response:
    """Answer an inbound call by returning media-stream TwiML.

    Args:
        settings: Injected settings (public base URL, default scenario).
        telephony: Telephony port used to build the TwiML.
        scenario: Optional scenario id override via query string.

    Returns:
        An ``application/xml`` TwiML response.
    """
    scenario_id = scenario or settings.default_scenario_id
    websocket_url = _websocket_url(settings.public_base_url, _MEDIA_STREAM_PATH)
    twiml = telephony.build_stream_twiml(websocket_url=websocket_url, scenario_id=scenario_id)
    get_logger("api.twilio").info(
        "twilio.inbound_voice", scenario=scenario_id, websocket_url=websocket_url
    )
    return Response(content=twiml, media_type="application/xml")
