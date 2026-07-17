from functools import lru_cache

from app.core.settings import TicketAnalysisSettings
from app.repositories.conversations import (
    ConversationRepository,
    InMemoryConversationRepository,
)
from app.services.conversations import (
    ConversationService,
    MemoryManager,
    MockConversationSummarizer,
)


@lru_cache
def get_conversation_repository() -> ConversationRepository:
    return InMemoryConversationRepository()


@lru_cache
def get_conversation_service() -> ConversationService:
    settings = TicketAnalysisSettings.from_env()
    return ConversationService(
        repository=get_conversation_repository(),
        memory_manager=MemoryManager(
            summarizer=MockConversationSummarizer(),
            summary_threshold=settings.conversation_summary_threshold,
            max_recent_messages=settings.conversation_max_recent_messages,
        ),
        ttl_seconds=settings.conversation_ttl_seconds,
    )
