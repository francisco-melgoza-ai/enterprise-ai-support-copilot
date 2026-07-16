from app.schemas.tickets import (
    TicketAnalysisRequest,
    TicketPriority,
    TicketSentiment,
)
from app.services.ticket_analysis import MockTicketAnalysisService


def test_mock_service_returns_deterministic_analysis() -> None:
    service = MockTicketAnalysisService()
    ticket = TicketAnalysisRequest(
        ticket_id="TICKET-1",
        subject="Login error",
        description="User cannot access the account after password reset failed.",
        channel="email",
    )

    first = service.analyze(ticket)
    second = service.analyze(ticket)

    assert first == second
    assert first.ticket_id == "TICKET-1"
    assert first.category == "account_access"
    assert first.priority == TicketPriority.HIGH
    assert first.sentiment == TicketSentiment.NEUTRAL
    assert first.requires_escalation is False
    assert first.escalation_reason is None
    assert 0 <= first.confidence <= 1


def test_mock_service_escalates_urgent_tickets() -> None:
    service = MockTicketAnalysisService()
    ticket = TicketAnalysisRequest(
        ticket_id="TICKET-2",
        subject="Production outage",
        description="The service is down for all users.",
        channel="web",
    )

    result = service.analyze(ticket)

    assert result.priority == TicketPriority.URGENT
    assert result.requires_escalation is True
    assert result.escalation_reason == "Urgent priority requires immediate escalation."


def test_mock_service_escalates_angry_sentiment() -> None:
    service = MockTicketAnalysisService()
    ticket = TicketAnalysisRequest(
        ticket_id="TICKET-3",
        subject="Billing issue",
        description="This charge is unacceptable and I need help.",
        channel="chat",
    )

    result = service.analyze(ticket)

    assert result.category == "billing"
    assert result.sentiment == TicketSentiment.ANGRY
    assert result.requires_escalation is True
    assert (
        result.escalation_reason
        == "Angry customer sentiment requires supervisor review."
    )
