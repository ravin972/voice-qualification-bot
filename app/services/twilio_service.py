"""Telephony port and Twilio adapter.

Owns the two Twilio touch-points: producing the TwiML that opens a Media Stream
for an inbound call, and any REST call-control (e.g. transferring a hot lead to
a human agent). No audio flows here — that is the WebSocket layer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from twilio.http.async_http_client import AsyncTwilioHttpClient
from twilio.rest import Client
from twilio.twiml.voice_response import Connect, Stream, VoiceResponse

from app.config.settings import Settings
from app.services.logger import get_logger


class TelephonyService(ABC):
    """Port: call control and stream provisioning."""

    @abstractmethod
    def build_stream_twiml(self, *, websocket_url: str, scenario_id: str) -> str:
        """Return TwiML that connects the inbound call to our media WebSocket.

        Args:
            websocket_url: The ``wss://`` endpoint Twilio should stream audio to.
            scenario_id: Scenario selector passed through as a stream parameter.

        Returns:
            A TwiML XML document as a string.
        """
        raise NotImplementedError

    @abstractmethod
    async def transfer_to_agent(self, call_sid: str, agent_number: str) -> None:
        """Warm-transfer a qualified call to a human agent.

        Args:
            call_sid: The live Twilio call identifier.
            agent_number: Destination phone number in E.164 format.
        """
        raise NotImplementedError


class TwilioService(TelephonyService):
    """Adapter: Twilio Programmable Voice.

    ``transfer_to_agent`` updates the live call to ``<Dial>`` a human agent via
    Twilio's REST API. When ``TWILIO_ACCOUNT_SID``/``TWILIO_AUTH_TOKEN`` aren't
    configured (e.g. local dev, demos, CI), it degrades to a logged simulation
    instead of raising — the interface and call site never need to know which
    mode is active.
    """

    def __init__(self, settings: Settings, *, client: Client | None = None) -> None:
        """Store credentials/config.

        Args:
            settings: Provides Twilio SID, auth token, and numbers.
            client: Optional pre-built REST client (used by tests). When given,
                it is used as-is and its lifecycle is the caller's
                responsibility. When omitted, a real transfer builds and tears
                down its own async client per call.
        """
        self._settings = settings
        self._client = client
        self._log = get_logger("twilio.telephony")

    def build_stream_twiml(self, *, websocket_url: str, scenario_id: str) -> str:
        """Build ``<Connect><Stream>`` TwiML pointing at our media WebSocket."""
        response = VoiceResponse()
        connect = Connect()
        stream = Stream(url=websocket_url)
        # Passed through to the media WebSocket as start.customParameters.
        stream.parameter(name="scenario", value=scenario_id)
        connect.append(stream)
        response.append(connect)
        return str(response)

    def _has_real_credentials(self) -> bool:
        """Whether real Twilio credentials are configured."""
        return self._settings.twilio_configured

    async def transfer_to_agent(self, call_sid: str, agent_number: str) -> None:
        """Warm-transfer a live call by updating it to ``<Dial>`` the agent.

        Simulates (logs and returns) instead of calling out when no test
        client was injected and no real Twilio credentials are configured.
        Never raises: a failed or simulated transfer must not crash the call.
        """
        twiml = str(VoiceResponse().dial(agent_number))

        if self._client is not None:
            await self._update_call(self._client, call_sid, agent_number, twiml)
            return

        if not self._has_real_credentials():
            self._log.info(
                "twilio.transfer_simulated",
                call_sid=call_sid,
                agent_number=agent_number,
                reason="TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN not configured",
            )
            return

        http_client = AsyncTwilioHttpClient()
        client = Client(
            self._settings.twilio_account_sid.get_secret_value(),  # type: ignore[union-attr]
            self._settings.twilio_auth_token.get_secret_value(),  # type: ignore[union-attr]
            http_client=http_client,
        )
        try:
            await self._update_call(client, call_sid, agent_number, twiml)
        finally:
            await http_client.close()

    async def _update_call(
        self, client: Client, call_sid: str, agent_number: str, twiml: str
    ) -> None:
        """Issue the REST update, logging success or a non-fatal failure."""
        try:
            await client.calls(call_sid).update_async(twiml=twiml)
            self._log.info(
                "twilio.transfer_completed", call_sid=call_sid, agent_number=agent_number
            )
        except Exception as exc:  # deliberate catch-all: a failed transfer must not crash the call
            self._log.warning(
                "twilio.transfer_failed",
                call_sid=call_sid,
                agent_number=agent_number,
                error=str(exc),
            )
