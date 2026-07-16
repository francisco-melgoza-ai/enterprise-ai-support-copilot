import logging
from types import SimpleNamespace
from typing import Any

import pytest

from app.schemas.tickets import TicketAnalysisRequest
from app.services.ticket_analysis import (
    GeminiTicketAnalysisService,
    TicketAnalysisModelResponseError,
    TicketAnalysisProviderError,
)


class FakeGeminiModelClient:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = responses
        self.calls = 0

    async def generate_content(self, **kwargs: Any) -> Any:
        self.calls += 1
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.mark.anyio
async def test_gemini_service_returns_valid_structured_response(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    client = FakeGeminiModelClient(
        [
            SimpleNamespace(
                parsed={
                    "ticket_id": "TICKET-1",
                    "summary": "Customer cannot access the account.",
                    "category": "account_access",
                    "priority": "high",
                    "sentiment": "frustrated",
                    "requires_escalation": True,
                    "escalation_reason": "High priority access issue.",
                    "suggested_response": "We are reviewing your access issue.",
                    "confidence": 0.89,
                }
            )
        ]
    )
    service = _service(client)

    result = await service.analyze(_ticket())

    assert result.ticket_id == "TICKET-1"
    assert result.category == "account_access"
    assert result.priority == "high"
    assert result.confidence == 0.89
    assert client.calls == 1
    telemetry = _telemetry_record(caplog)
    assert telemetry.provider == "gemini"
    assert telemetry.model == "gemini-test"
    assert telemetry.outcome == "success"
    assert telemetry.attempt_count == 1
    assert telemetry.duration_ms >= 0


@pytest.mark.anyio
async def test_gemini_service_rejects_invalid_model_response(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    client = FakeGeminiModelClient([SimpleNamespace(parsed={"ticket_id": "TICKET-1"})])
    service = _service(client)

    with pytest.raises(TicketAnalysisModelResponseError):
        await service.analyze(_ticket())
    telemetry = _telemetry_record(caplog)
    assert telemetry.outcome == "invalid_response"
    assert telemetry.attempt_count == 1


@pytest.mark.anyio
async def test_gemini_service_times_out(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    client = FakeGeminiModelClient([TimeoutError(), TimeoutError()])
    service = _service(client, max_attempts=2)

    with pytest.raises(TicketAnalysisProviderError):
        await service.analyze(_ticket())

    assert client.calls == 2
    telemetry = _telemetry_record(caplog)
    assert telemetry.outcome == "timeout"
    assert telemetry.attempt_count == 2


@pytest.mark.anyio
async def test_gemini_service_raises_after_exhausted_retries(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    client = FakeGeminiModelClient([RuntimeError("failed"), RuntimeError("failed")])
    service = _service(client, max_attempts=2)

    with pytest.raises(TicketAnalysisProviderError):
        await service.analyze(_ticket())

    assert client.calls == 2
    telemetry = _telemetry_record(caplog)
    assert telemetry.outcome == "error"
    assert telemetry.attempt_count == 2


@pytest.mark.anyio
async def test_gemini_service_does_not_log_ticket_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    client = FakeGeminiModelClient(
        [
            SimpleNamespace(
                parsed={
                    "ticket_id": "TICKET-SECRET",
                    "summary": "Safe summary.",
                    "category": "general_support",
                    "priority": "low",
                    "sentiment": "neutral",
                    "requires_escalation": False,
                    "escalation_reason": None,
                    "suggested_response": "Safe response.",
                    "confidence": 0.8,
                }
            )
        ]
    )
    service = _service(client)
    ticket = TicketAnalysisRequest(
        ticket_id="TICKET-SECRET",
        subject="TOP SECRET SUBJECT",
        description="TOP SECRET DESCRIPTION",
        channel="email",
    )

    await service.analyze(ticket)

    assert "TOP SECRET SUBJECT" not in caplog.text
    assert "TOP SECRET DESCRIPTION" not in caplog.text
    assert "Safe response." not in caplog.text


def _service(
    client: FakeGeminiModelClient, *, max_attempts: int = 3
) -> GeminiTicketAnalysisService:
    return GeminiTicketAnalysisService(
        project="test-project",
        location="us-central1",
        model="gemini-test",
        timeout_seconds=0.01,
        max_attempts=max_attempts,
        model_client=client,
    )


def _ticket() -> TicketAnalysisRequest:
    return TicketAnalysisRequest(
        ticket_id="TICKET-1",
        subject="Cannot access account",
        description="The customer cannot access the account and is frustrated.",
        channel="email",
    )


def _telemetry_record(caplog: pytest.LogCaptureFixture) -> logging.LogRecord:
    records = [
        record
        for record in caplog.records
        if record.getMessage() == "gemini_ticket_analysis_completed"
    ]
    assert records
    return records[-1]
