"""Health and readiness endpoints.

``GET /health`` always returns ``200`` as long as the process is up and can
compute a response — it never fails just because a vendor key is missing or a
scenario file is malformed. Those conditions are instead *reported* in the
body (``scenarios``, ``vendor_config``), so a caller can distinguish "the
process is alive" from "the process is fully configured" without the
liveness probe itself flapping.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.config.dependencies import SettingsDep
from app.scenarios.registry import ScenarioRegistry

router = APIRouter(tags=["health"])


class ScenarioLoaderStatus(BaseModel):
    """Result of re-scanning ``app/scenarios/data/`` for scenario YAML files."""

    ok: bool = Field(description="True if at least one scenario loaded without error.")
    scenario_ids: list[str] = Field(default_factory=list, description="Scenario ids found.")
    error: str | None = Field(default=None, description="Set if loading failed.")


class VendorConfigStatus(BaseModel):
    """Whether each vendor's credentials are configured (not whether they're valid)."""

    twilio: bool = Field(description="TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN are both set.")
    openai: bool = Field(description="OPENAI_API_KEY is set.")
    deepgram: bool = Field(description="DEEPGRAM_API_KEY is set.")
    elevenlabs: bool = Field(description="ELEVENLABS_API_KEY is set.")


class HealthResponse(BaseModel):
    """Liveness + readiness snapshot."""

    status: str
    service: str
    environment: str
    scenarios: ScenarioLoaderStatus
    vendor_config: VendorConfigStatus


def _check_scenarios() -> ScenarioLoaderStatus:
    """Re-scan the scenario data directory now, rather than trusting a cached result.

    Uses the real :class:`ScenarioRegistry` (not the ``lru_cache``-backed DI
    singleton) so a genuinely broken YAML file is caught here instead of only
    surfacing the first time some other request happens to need it.
    """
    try:
        ids = sorted(ScenarioRegistry().ids())
    except Exception as exc:  # deliberate catch-all: health check must never itself crash
        return ScenarioLoaderStatus(ok=False, scenario_ids=[], error=str(exc))
    if not ids:
        return ScenarioLoaderStatus(
            ok=False, scenario_ids=[], error="No scenarios found in app/scenarios/data/"
        )
    return ScenarioLoaderStatus(ok=True, scenario_ids=ids)


@router.get("/health", summary="Liveness + readiness probe", response_model=HealthResponse)
async def health(settings: SettingsDep) -> HealthResponse:
    """Return liveness plus scenario-loader and vendor-configuration status.

    Args:
        settings: Injected application settings.

    Returns:
        Service identity, whether scenarios loaded, and which vendor
        credentials are present.
    """
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        environment=settings.environment,
        scenarios=_check_scenarios(),
        vendor_config=VendorConfigStatus(
            twilio=settings.twilio_configured,
            openai=settings.openai_configured,
            deepgram=settings.deepgram_configured,
            elevenlabs=settings.elevenlabs_configured,
        ),
    )
