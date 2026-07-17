from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

MessageContent = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)
]


class ConversationRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class Conversation(BaseModel):
    model_config = ConfigDict(frozen=True)

    conversation_id: str
    owner_subject: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConversationMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    message_id: str
    conversation_id: str
    role: ConversationRole
    content: str
    created_at: datetime


class ConversationCreateRequest(BaseModel):
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConversationResponse(BaseModel):
    conversation_id: str
    owner_subject: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    summary: str | None = None
    metadata: dict[str, Any]

    @classmethod
    def from_domain(cls, conversation: Conversation) -> "ConversationResponse":
        return cls.model_validate(conversation.model_dump())


class ConversationMessageCreateRequest(BaseModel):
    role: ConversationRole = ConversationRole.USER
    content: MessageContent


class ConversationMessageResponse(BaseModel):
    message_id: str
    conversation_id: str
    role: ConversationRole
    content: str
    created_at: datetime

    @classmethod
    def from_domain(cls, message: ConversationMessage) -> "ConversationMessageResponse":
        return cls.model_validate(message.model_dump())


class ConversationMemoryContext(BaseModel):
    summary: str | None = None
    recent_messages: list[ConversationMessage] = Field(default_factory=list)
