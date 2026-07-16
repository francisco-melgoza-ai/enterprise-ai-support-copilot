from fastapi import FastAPI

from app.api.errors import register_exception_handlers
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.router import api_router
from app.core.logging import RequestLoggingMiddleware, configure_logging

configure_logging()

app = FastAPI(title="Enterprise AI Support Copilot API")
app.add_middleware(RequestLoggingMiddleware)
register_exception_handlers(app)
app.include_router(health_router)
app.include_router(api_router, prefix="/api/v1")
