from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.dependencies.auth import require_any_role
from app.api.dependencies.conversations import get_conversation_service
from app.core.auth import AuthenticatedPrincipal, SupportRole
from app.schemas.conversations import (
    ConversationCreateRequest,
    ConversationMessageCreateRequest,
    ConversationMessageResponse,
    ConversationResponse,
)
from app.services.conversations import ConversationService

router = APIRouter()
conversation_role_dependency = require_any_role(
    {
        SupportRole.SUPPORT_AGENT.value,
        SupportRole.SUPPORT_MANAGER.value,
        SupportRole.PLATFORM_ADMIN.value,
    }
)


@router.post(
    "", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED
)
async def create_conversation(
    request: ConversationCreateRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(conversation_role_dependency)],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> ConversationResponse:
    conversation = await service.create_conversation(
        principal=principal,
        metadata=request.metadata,
    )
    return ConversationResponse.from_domain(conversation)


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(conversation_role_dependency)],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> ConversationResponse:
    conversation = await service.load_conversation(conversation_id, principal)
    return ConversationResponse.from_domain(conversation)


@router.get(
    "/{conversation_id}/messages",
    response_model=list[ConversationMessageResponse],
)
async def list_messages(
    conversation_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(conversation_role_dependency)],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[ConversationMessageResponse]:
    messages = await service.list_messages(
        conversation_id=conversation_id,
        principal=principal,
        limit=limit,
    )
    return [ConversationMessageResponse.from_domain(message) for message in messages]


@router.post(
    "/{conversation_id}/messages",
    response_model=ConversationMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def append_message(
    conversation_id: str,
    request: ConversationMessageCreateRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(conversation_role_dependency)],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> ConversationMessageResponse:
    message = await service.append_message(
        conversation_id=conversation_id,
        principal=principal,
        role=request.role,
        content=request.content,
    )
    return ConversationMessageResponse.from_domain(message)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(conversation_role_dependency)],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> Response:
    await service.delete_conversation(
        conversation_id=conversation_id,
        principal=principal,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
