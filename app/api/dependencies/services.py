from functools import lru_cache

from app.services.ticket_analysis import (
    MockTicketAnalysisService,
    TicketAnalysisService,
)


@lru_cache
def get_ticket_analysis_service() -> TicketAnalysisService:
    return MockTicketAnalysisService()
