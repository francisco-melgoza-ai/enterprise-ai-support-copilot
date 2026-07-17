import logging
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies.auth import require_any_role
from app.api.dependencies.conversations import get_conversation_service
from app.api.dependencies.services import get_ticket_analysis_service
from app.core.auth import AuthenticatedPrincipal, SupportRole
from app.core.logging import get_request_id
from app.core.metrics import (
    record_ticket_analysis_failure,
    record_ticket_analysis_request,
    record_ticket_analysis_success,
)
from app.core.tracing import get_tracer, record_span_exception, set_span_attributes
from app.schemas.conversations import ConversationMemoryContext, ConversationRole
from app.schemas.tickets import TicketAnalysisRequest, TicketAnalysisResponse
from app.services.conversations import ConversationService
from app.services.ticket_analysis import TicketAnalysisService

router = APIRouter()
logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)
ticket_analysis_role_dependency = require_any_role(
    {
        SupportRole.SUPPORT_AGENT.value,
        SupportRole.SUPPORT_MANAGER.value,
        SupportRole.PLATFORM_ADMIN.value,
    }
)


@router.post("/analyze", response_model=TicketAnalysisResponse)
async def analyze_ticket(
    ticket: TicketAnalysisRequest,
    service: Annotated[TicketAnalysisService, Depends(get_ticket_analysis_service)],
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(ticket_analysis_role_dependency),
    ],
    conversation_service: Annotated[
        ConversationService,
        Depends(get_conversation_service),
    ],
) -> TicketAnalysisResponse:
    logger.info("ticket_analysis_requested")
    record_ticket_analysis_request()
    with tracer.start_as_current_span("ticket.analysis") as span:
        request_id = get_request_id()
        if request_id is not None:
            span.set_attribute("http.request_id", request_id)
        try:
            memory_context = await _memory_context(
                ticket,
                principal,
                conversation_service,
            )
            response = await service.analyze(ticket, memory_context)
            if ticket.conversation_id is not None:
                await _append_ticket_turns(
                    ticket=ticket,
                    response=response,
                    principal=principal,
                    conversation_service=conversation_service,
                )
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


async def _memory_context(
    ticket: TicketAnalysisRequest,
    principal: AuthenticatedPrincipal,
    conversation_service: ConversationService,
) -> ConversationMemoryContext | None:
    if ticket.conversation_id is None:
        return None
    return await conversation_service.memory_context(
        conversation_id=ticket.conversation_id,
        principal=principal,
    )


async def _append_ticket_turns(
    *,
    ticket: TicketAnalysisRequest,
    response: TicketAnalysisResponse,
    principal: AuthenticatedPrincipal,
    conversation_service: ConversationService,
) -> None:
    if ticket.conversation_id is None:
        return
    await conversation_service.append_message(
        conversation_id=ticket.conversation_id,
        principal=principal,
        role=ConversationRole.USER,
        content=f"{ticket.subject}\n\n{ticket.description}",
    )
    await conversation_service.append_message(
        conversation_id=ticket.conversation_id,
        principal=principal,
        role=ConversationRole.ASSISTANT,
        content=response.suggested_response,
    )
