"""TwilioService.transfer_to_agent tests.

Covers both operating modes: the logged simulation used when no real Twilio
credentials are configured, and the real REST-update path (exercised via a
duck-typed fake client — no network, no real Twilio account needed).
``build_stream_twiml`` is unchanged by this phase and already covered by the
API integration tests.
"""

from __future__ import annotations

from app.config.settings import Settings
from app.services.twilio_service import TwilioService


class _FakeCallContext:
    def __init__(self, log: list[str], exc: Exception | None) -> None:
        self._log = log
        self._exc = exc

    async def update_async(self, *, twiml: str) -> None:
        if self._exc is not None:
            raise self._exc
        self._log.append(twiml)


class FakeTwilioClient:
    """Duck-typed stand-in for ``twilio.rest.Client``'s ``.calls(sid).update_async(...)``."""

    def __init__(self, exc: Exception | None = None) -> None:
        self.updated_twiml: list[str] = []
        self.requested_sids: list[str] = []
        self._exc = exc

    def calls(self, call_sid: str) -> _FakeCallContext:
        self.requested_sids.append(call_sid)
        return _FakeCallContext(self.updated_twiml, self._exc)


def _settings(*, with_credentials: bool) -> Settings:
    # Explicit kwargs take priority over a real .env file's values (verified),
    # which matters here: this repo's local .env may hold live Twilio
    # credentials, and these tests must never depend on or contact them.
    if with_credentials:
        return Settings(
            twilio_account_sid="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            twilio_auth_token="x" * 32,
        )
    return Settings(twilio_account_sid=None, twilio_auth_token=None)


def _service(settings: Settings, fake_client: FakeTwilioClient | None = None) -> TwilioService:
    return TwilioService(settings, client=fake_client)  # type: ignore[arg-type]


# --- Simulation mode: no credentials, no injected client ---------------------
async def test_simulates_when_no_credentials_configured() -> None:
    """Must not raise, and must not attempt any real client construction."""
    service = _service(_settings(with_credentials=False))
    await service.transfer_to_agent("CA123", "+15550001111")


# --- Real path: fake client injected -----------------------------------------
async def test_real_path_updates_the_call_with_dial_twiml() -> None:
    fake = FakeTwilioClient()
    service = _service(_settings(with_credentials=False), fake)

    await service.transfer_to_agent("CA123", "+15550001111")

    assert fake.requested_sids == ["CA123"]
    assert len(fake.updated_twiml) == 1
    assert "<Dial>+15550001111</Dial>" in fake.updated_twiml[0]


async def test_injected_client_is_used_even_without_settings_credentials() -> None:
    """An injected client takes priority over the credential-based simulation gate."""
    fake = FakeTwilioClient()
    service = _service(_settings(with_credentials=False), fake)

    await service.transfer_to_agent("CA999", "+15550002222")

    assert fake.requested_sids == ["CA999"]
    assert "<Dial>+15550002222</Dial>" in fake.updated_twiml[0]


async def test_failed_transfer_is_swallowed_not_raised() -> None:
    fake = FakeTwilioClient(exc=RuntimeError("Twilio is down"))
    service = _service(_settings(with_credentials=True), fake)

    await service.transfer_to_agent("CA123", "+15550001111")  # must not raise

    assert fake.requested_sids == ["CA123"]  # the attempt was made
