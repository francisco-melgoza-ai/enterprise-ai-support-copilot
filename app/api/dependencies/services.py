from functools import lru_cache

from app.core.settings import TicketAnalysisSettings
from app.services.knowledge import KnowledgeRetriever, LocalKnowledgeRetriever
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
    knowledge_retriever = _get_knowledge_retriever(settings)

    if provider == "mock":
        return MockTicketAnalysisService()
    if provider == "gemini":
        return GeminiTicketAnalysisService(
            project=settings.google_cloud_project or "",
            location=settings.google_cloud_location,
            model=settings.gemini_model,
            knowledge_retriever=knowledge_retriever,
        )

    raise TicketAnalysisConfigurationError(
        "Unsupported TICKET_ANALYSIS_PROVIDER. Expected 'mock' or 'gemini'."
    )


def _get_knowledge_retriever(
    settings: TicketAnalysisSettings,
) -> KnowledgeRetriever | None:
    provider = settings.knowledge_provider.lower()

    if provider == "none":
        return None
    if provider == "local":
        return LocalKnowledgeRetriever()

    raise TicketAnalysisConfigurationError(
        "Unsupported KNOWLEDGE_PROVIDER. Expected 'none' or 'local'."
    )
