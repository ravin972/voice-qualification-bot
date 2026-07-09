"""Application entry point and FastAPI app factory.

Wires the app together: configures structured logging, mounts the HTTP and
WebSocket routers, and manages startup/shutdown via the lifespan context. This
is composition/wiring (architecture) and is implemented now; it contains no
business logic itself.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import api_router
from app.config.settings import Settings, get_settings
from app.services.logger import configure_logging, get_logger
from app.websocket import dashboard_router, media_stream_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: configure logging on startup, log shutdown.

    Args:
        app: The FastAPI application instance.

    Yields:
        Control for the duration the app is serving.
    """
    settings: Settings = app.state.settings
    configure_logging(settings)
    log = get_logger("lifespan")
    log.info("application.startup", version=__version__, environment=settings.environment)
    try:
        yield
    finally:
        log.info("application.shutdown")


def create_app() -> FastAPI:
    """Build and configure the FastAPI application.

    Returns:
        A fully-wired :class:`FastAPI` instance ready to serve.
    """
    settings = get_settings()
    app = FastAPI(
        title="Voice Qualification Bot",
        version=__version__,
        debug=settings.debug,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)
    app.include_router(media_stream_router)
    app.include_router(dashboard_router)
    return app


#: ASGI application object referenced by uvicorn (``app.main:app``).
app = create_app()
