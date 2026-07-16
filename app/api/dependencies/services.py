from functools import lru_cache

from app.core.settings import TicketAnalysisSettings
from app.services.knowledge import (
    KnowledgeRetriever,
    LocalKnowledgeRetriever,
    VertexRagKnowledgeRetriever,
    parse_rag_corpus_resource_name,
)
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
    if provider == "vertex_rag":
        if settings.rag_corpus_resource_name is None:
            raise TicketAnalysisConfigurationError(
                "RAG_CORPUS_RESOURCE_NAME is required when "
                "KNOWLEDGE_PROVIDER='vertex_rag'."
            )
        parsed_project, parsed_location = parse_rag_corpus_resource_name(
            settings.rag_corpus_resource_name
        )
        return VertexRagKnowledgeRetriever(
            corpus_resource_name=settings.rag_corpus_resource_name,
            project=settings.google_cloud_project or parsed_project,
            location=settings.rag_location or parsed_location,
            top_k=settings.rag_top_k,
            distance_threshold=settings.rag_distance_threshold,
        )

    raise TicketAnalysisConfigurationError(
        "Unsupported KNOWLEDGE_PROVIDER. Expected 'none', 'local', or 'vertex_rag'."
    )
