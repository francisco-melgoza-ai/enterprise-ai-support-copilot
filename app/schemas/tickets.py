from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
SubjectString = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
DescriptionString = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)
]
LanguageString = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=16)
]
ConversationIdString = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
]


class TicketChannel(StrEnum):
    WEB = "web"
    EMAIL = "email"
    CHAT = "chat"
    PHONE = "phone"


class TicketPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class TicketSentiment(StrEnum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    FRUSTRATED = "frustrated"
    ANGRY = "angry"


class TicketAnalysisRequest(BaseModel):
    ticket_id: NonEmptyString
    subject: SubjectString
    description: DescriptionString
    channel: TicketChannel
    customer_language: LanguageString = "en"
    conversation_id: ConversationIdString | None = None


class TicketAnalysisResponse(BaseModel):
    ticket_id: str
    summary: str
    category: str
    priority: TicketPriority
    sentiment: TicketSentiment
    requires_escalation: bool
    escalation_reason: str | None = None
    suggested_response: str
    confidence: float = Field(ge=0, le=1)
