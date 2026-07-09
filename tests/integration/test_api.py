"""HTTP API integration tests.

Exercises the real FastAPI app (lifespan, DI, routing) via ``TestClient`` —
no mocks of our own code, only the absence of live vendor credentials (which
these endpoints never need to call out for).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from app.config.settings import Settings, get_settings
from app.main import app
from fastapi.testclient import TestClient

#: Explicit "nothing configured" override — never rely on this machine's real
#: .env (which may hold live vendor credentials) to prove the "false" case.
_NO_VENDOR_CREDENTIALS = Settings(
    twilio_account_sid=None,
    twilio_auth_token=None,
    openai_api_key=None,
    deepgram_api_key=None,
    elevenlabs_api_key=None,
)


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client_with_no_vendor_credentials() -> Iterator[TestClient]:
    app.dependency_overrides[get_settings] = lambda: _NO_VENDOR_CREDENTIALS
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "voice-qualification-bot"


def test_health_reports_scenario_loader_status(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["scenarios"]["ok"] is True
    assert set(body["scenarios"]["scenario_ids"]) == {"lead_qualifier", "loan_qualifier"}
    assert body["scenarios"]["error"] is None


def test_health_reports_vendor_config_absent(
    client_with_no_vendor_credentials: TestClient,
) -> None:
    body = client_with_no_vendor_credentials.get("/health").json()
    assert body["vendor_config"] == {
        "twilio": False,
        "openai": False,
        "deepgram": False,
        "elevenlabs": False,
    }
    # A missing vendor key is reported, not a failure — still 200.
    assert body["status"] == "ok"


def test_twilio_voice_returns_streaming_twiml_for_requested_scenario(
    client: TestClient,
) -> None:
    response = client.post("/twilio/voice?scenario=loan_qualifier")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert "<Stream" in response.text
    assert 'value="loan_qualifier"' in response.text


def test_twilio_voice_falls_back_to_default_scenario(client: TestClient) -> None:
    """No ?scenario= query param -> settings.default_scenario_id is used."""
    response = client.post("/twilio/voice")
    assert response.status_code == 200
    assert 'value="lead_qualifier"' in response.text


def test_twilio_voice_websocket_url_matches_public_base_url(client: TestClient) -> None:
    response = client.post("/twilio/voice")
    assert "wss://" in response.text or "ws://" in response.text
    assert "/media-stream" in response.text


def test_cors_allows_the_deployed_frontend_origin(client: TestClient) -> None:
    """The frontend (Vercel) and backend (Render) are on different domains —
    without CORS, the browser blocks every cross-origin fetch the dashboard makes."""
    response = client.get(
        "/health", headers={"Origin": "https://voice-qualification-bot.vercel.app"}
    )
    assert response.status_code == 200
    assert (
        response.headers["access-control-allow-origin"]
        == "https://voice-qualification-bot.vercel.app"
    )


def test_cors_rejects_an_unlisted_origin(client: TestClient) -> None:
    response = client.get("/health", headers={"Origin": "https://not-our-frontend.example"})
    assert response.status_code == 200  # request still succeeds...
    assert "access-control-allow-origin" not in response.headers  # ...but isn't CORS-allowed
