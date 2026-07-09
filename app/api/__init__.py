"""HTTP API layer: health checks, Twilio voice webhooks, and local conversation testing."""

from fastapi import APIRouter

from app.api.conversation_testing import router as conversation_testing_router
from app.api.health import router as health_router
from app.api.twilio import router as twilio_router

#: Aggregate router mounted by the app factory.
api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(twilio_router)
api_router.include_router(conversation_testing_router)

__all__ = ["api_router"]
