import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import register_exception_handlers
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.router import api_router
from app.core.logging import RequestLoggingMiddleware, configure_logging
from app.core.settings import TicketAnalysisSettings

configure_logging()


def log_startup_configuration() -> None:
    settings = TicketAnalysisSettings.from_env()
    logging.getLogger(__name__).info(
        "application_startup",
        extra={
            "app_env": settings.app_env,
            "provider": settings.provider.lower(),
            "model": settings.gemini_model,
            "cloud_region": settings.google_cloud_location,
        },
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    log_startup_configuration()
    yield


app = FastAPI(title="Enterprise AI Support Copilot API", lifespan=lifespan)
app.add_middleware(RequestLoggingMiddleware)
register_exception_handlers(app)
app.include_router(health_router)
app.include_router(api_router, prefix="/api/v1")
