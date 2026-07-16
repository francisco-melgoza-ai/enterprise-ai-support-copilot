from functools import lru_cache

from app.core.settings import TicketAnalysisSettings
from app.services.ticket_analysis import (
    GeminiTicketAnalysisService,
    MockTicketAnalysisService,
    TicketAnalysisConfigurationError,
    TicketAnalysisService,
)


@lru_cache
def get_ticket_analysis_service() -> TicketAnalysisService:
    settings = TicketAnalysisSettings.from_env()
    provider = settings.provider.lower()

    if provider == "mock":
        return MockTicketAnalysisService()
    if provider == "gemini":
        return GeminiTicketAnalysisService(
            project=settings.google_cloud_project or "",
            location=settings.google_cloud_location,
            model=settings.gemini_model,
        )

    raise TicketAnalysisConfigurationError(
        "Unsupported TICKET_ANALYSIS_PROVIDER. Expected 'mock' or 'gemini'."
    )
