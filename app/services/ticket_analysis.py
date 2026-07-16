from typing import Protocol

from app.schemas.tickets import (
    TicketAnalysisRequest,
    TicketAnalysisResponse,
    TicketPriority,
    TicketSentiment,
)


class TicketAnalysisService(Protocol):
    async def analyze(self, ticket: TicketAnalysisRequest) -> TicketAnalysisResponse:
        """Analyze a support ticket without mutating external state."""


class MockTicketAnalysisService:
    async def analyze(self, ticket: TicketAnalysisRequest) -> TicketAnalysisResponse:
        text = f"{ticket.subject} {ticket.description}".lower()
        priority = self._priority(text)
        sentiment = self._sentiment(text)
        category = self._category(text)
        requires_escalation, escalation_reason = self._escalation(priority, sentiment)

        return TicketAnalysisResponse(
            ticket_id=ticket.ticket_id,
            summary=self._summary(ticket.description),
            category=category,
            priority=priority,
            sentiment=sentiment,
            requires_escalation=requires_escalation,
            escalation_reason=escalation_reason,
            suggested_response=self._suggested_response(category, priority),
            confidence=self._confidence(priority, sentiment),
        )

    def _priority(self, text: str) -> TicketPriority:
        if self._contains_any(text, ("outage", "down", "security", "breach")):
            return TicketPriority.URGENT
        if self._contains_any(text, ("blocked", "production", "cannot access")):
            return TicketPriority.HIGH
        if self._contains_any(text, ("slow", "error", "failed", "issue")):
            return TicketPriority.MEDIUM
        return TicketPriority.LOW

    def _sentiment(self, text: str) -> TicketSentiment:
        if self._contains_any(text, ("angry", "furious", "unacceptable")):
            return TicketSentiment.ANGRY
        if self._contains_any(text, ("frustrated", "annoyed", "upset")):
            return TicketSentiment.FRUSTRATED
        if self._contains_any(text, ("thanks", "great", "appreciate")):
            return TicketSentiment.POSITIVE
        return TicketSentiment.NEUTRAL

    def _category(self, text: str) -> str:
        if self._contains_any(text, ("billing", "invoice", "payment", "charge")):
            return "billing"
        if self._contains_any(text, ("login", "password", "access", "account")):
            return "account_access"
        if self._contains_any(text, ("bug", "error", "failed", "broken")):
            return "technical_support"
        if self._contains_any(text, ("how do i", "question", "help")):
            return "general_question"
        return "general_support"

    def _escalation(
        self, priority: TicketPriority, sentiment: TicketSentiment
    ) -> tuple[bool, str | None]:
        if priority == TicketPriority.URGENT:
            return True, "Urgent priority requires immediate escalation."
        if sentiment == TicketSentiment.ANGRY:
            return True, "Angry customer sentiment requires supervisor review."
        return False, None

    def _summary(self, description: str) -> str:
        normalized = " ".join(description.split())
        if len(normalized) <= 160:
            return normalized
        return f"{normalized[:157].rstrip()}..."

    def _suggested_response(self, category: str, priority: TicketPriority) -> str:
        if priority == TicketPriority.URGENT:
            return (
                "Acknowledge the impact, confirm immediate investigation, and "
                "share the next update window."
            )
        if category == "billing":
            return (
                "Acknowledge the billing concern and ask for the invoice or "
                "transaction reference needed to investigate."
            )
        if category == "account_access":
            return (
                "Acknowledge the access issue and guide the customer through "
                "secure account recovery steps."
            )
        return (
            "Acknowledge the request, summarize the issue, and provide the next "
            "support step."
        )

    def _confidence(
        self, priority: TicketPriority, sentiment: TicketSentiment
    ) -> float:
        if priority == TicketPriority.URGENT or sentiment == TicketSentiment.ANGRY:
            return 0.91
        if priority == TicketPriority.LOW and sentiment == TicketSentiment.NEUTRAL:
            return 0.72
        return 0.84

    def _contains_any(self, text: str, keywords: tuple[str, ...]) -> bool:
        return any(keyword in text for keyword in keywords)
