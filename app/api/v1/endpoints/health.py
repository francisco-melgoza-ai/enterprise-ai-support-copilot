from fastapi import APIRouter, Response, status

from app.core.metrics import METRICS_CONTENT_TYPE, render_metrics
from app.core.settings import TicketAnalysisSettings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def readiness_check(response: Response) -> dict[str, str]:
    settings = TicketAnalysisSettings.from_env()
    provider = settings.provider.lower()
    knowledge_provider = settings.knowledge_provider.lower()
    provider_ready = provider in {"mock", "gemini"}
    knowledge_ready = knowledge_provider in {"none", "local", "vertex_rag"}

    if not provider_ready or not knowledge_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "not_ready",
            "provider": provider,
            "knowledge_provider": knowledge_provider,
        }

    return {
        "status": "ready",
        "provider": provider,
        "knowledge_provider": knowledge_provider,
    }


@router.get("/metrics")
async def metrics() -> Response:
    return Response(content=render_metrics(), media_type=METRICS_CONTENT_TYPE)
