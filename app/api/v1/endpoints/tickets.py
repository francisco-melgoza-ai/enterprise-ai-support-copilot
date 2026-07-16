import logging
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies.services import get_ticket_analysis_service
from app.schemas.tickets import TicketAnalysisRequest, TicketAnalysisResponse
from app.services.ticket_analysis import TicketAnalysisService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/analyze", response_model=TicketAnalysisResponse)
async def analyze_ticket(
    ticket: TicketAnalysisRequest,
    service: Annotated[TicketAnalysisService, Depends(get_ticket_analysis_service)],
) -> TicketAnalysisResponse:
    logger.info("ticket_analysis_requested", extra={"ticket_id": ticket.ticket_id})
    return await service.analyze(ticket)
