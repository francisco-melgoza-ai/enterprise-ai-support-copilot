import logging
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies.services import get_ticket_analysis_service
from app.core.logging import get_request_id
from app.core.metrics import (
    record_ticket_analysis_failure,
    record_ticket_analysis_request,
    record_ticket_analysis_success,
)
from app.core.tracing import get_tracer, record_span_exception, set_span_attributes
from app.schemas.tickets import TicketAnalysisRequest, TicketAnalysisResponse
from app.services.ticket_analysis import TicketAnalysisService

router = APIRouter()
logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)


@router.post("/analyze", response_model=TicketAnalysisResponse)
async def analyze_ticket(
    ticket: TicketAnalysisRequest,
    service: Annotated[TicketAnalysisService, Depends(get_ticket_analysis_service)],
) -> TicketAnalysisResponse:
    logger.info("ticket_analysis_requested")
    record_ticket_analysis_request()
    with tracer.start_as_current_span("ticket.analysis") as span:
        request_id = get_request_id()
        if request_id is not None:
            span.set_attribute("http.request_id", request_id)
        try:
            response = await service.analyze(ticket)
        except Exception as exc:
            record_ticket_analysis_failure()
            record_span_exception(span, exc)
            raise
        set_span_attributes(
            span,
            {
                "ticket.analysis.category": response.category,
                "ticket.analysis.priority": response.priority.value,
                "ticket.analysis.requires_escalation": response.requires_escalation,
            },
        )
        record_ticket_analysis_success(
            requires_escalation=response.requires_escalation,
        )
        return response
