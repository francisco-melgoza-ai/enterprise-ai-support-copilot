import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.services import get_ticket_analysis_service
from app.main import app
from app.schemas.tickets import TicketAnalysisRequest, TicketAnalysisResponse
from app.services.ticket_analysis import TicketAnalysisProviderError


@pytest.fixture(autouse=True)
def use_mock_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TICKET_ANALYSIS_PROVIDER", "mock")
    get_ticket_analysis_service.cache_clear()
    yield
    app.dependency_overrides.clear()
    get_ticket_analysis_service.cache_clear()


def test_analyze_ticket_endpoint() -> None:
    client = TestClient(app)
    payload: dict[str, Any] = {
        "ticket_id": "TICKET-100",
        "subject": "Payment failed",
        "description": "Invoice payment failed and the customer is frustrated.",
        "channel": "email",
    }

    response = client.post("/api/v1/tickets/analyze", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["ticket_id"] == "TICKET-100"
    assert body["summary"] == payload["description"]
    assert body["category"] == "billing"
    assert body["priority"] == "medium"
    assert body["sentiment"] == "frustrated"
    assert body["requires_escalation"] is False
    assert body["escalation_reason"] is None
    assert body["suggested_response"]
    assert 0 <= body["confidence"] <= 1


def test_analyze_ticket_response_includes_request_id_header() -> None:
    client = TestClient(app)
    payload: dict[str, Any] = {
        "ticket_id": "TICKET-REQUEST-ID",
        "subject": "Payment failed",
        "description": "Invoice payment failed.",
        "channel": "email",
    }

    response = client.post(
        "/api/v1/tickets/analyze",
        json=payload,
        headers={"X-Request-ID": "incoming-request-id"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "incoming-request-id"


def test_request_id_is_included_in_application_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    client = TestClient(app)
    payload: dict[str, Any] = {
        "ticket_id": "TICKET-LOGS",
        "subject": "Sensitive subject should not appear",
        "description": "Sensitive description should not appear",
        "channel": "email",
    }

    response = client.post(
        "/api/v1/tickets/analyze",
        json=payload,
        headers={"X-Request-ID": "log-request-id"},
    )

    assert response.status_code == 200
    app_records = [
        record for record in caplog.records if record.name.startswith("app.")
    ]
    assert app_records
    assert all(record.request_id == "log-request-id" for record in app_records)
    assert all(not hasattr(record, "ticket_id") for record in app_records)
    assert "TICKET-LOGS" not in caplog.text
    assert "Sensitive subject should not appear" not in caplog.text
    assert "Sensitive description should not appear" not in caplog.text


def test_analyze_ticket_defaults_customer_language() -> None:
    client = TestClient(app)
    payload: dict[str, Any] = {
        "ticket_id": "TICKET-101",
        "subject": "General question",
        "description": "How do I update my notification settings?",
        "channel": "web",
    }

    response = client.post("/api/v1/tickets/analyze", json=payload)

    assert response.status_code == 200
    assert response.json()["ticket_id"] == "TICKET-101"


def test_analyze_ticket_rejects_invalid_input() -> None:
    client = TestClient(app)
    payload: dict[str, Any] = {
        "ticket_id": "",
        "subject": "",
        "description": "",
        "channel": "email",
    }

    response = client.post("/api/v1/tickets/analyze", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["message"] == "Request validation failed."
    assert len(body["error"]["details"]) == 3
    assert "input" not in body["error"]["details"][0]


def test_analyze_ticket_rejects_whitespace_only_input() -> None:
    client = TestClient(app)
    payload: dict[str, Any] = {
        "ticket_id": " ",
        "subject": " ",
        "description": " ",
        "channel": "chat",
    }

    response = client.post("/api/v1/tickets/analyze", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert len(body["error"]["details"]) == 3


def test_analyze_ticket_rejects_max_length_violations() -> None:
    client = TestClient(app)
    payload: dict[str, Any] = {
        "ticket_id": "TICKET-103",
        "subject": "x" * 201,
        "description": "x" * 5001,
        "channel": "phone",
        "customer_language": "x" * 17,
    }

    response = client.post("/api/v1/tickets/analyze", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert len(body["error"]["details"]) == 3


def test_analyze_ticket_rejects_unsupported_channel() -> None:
    client = TestClient(app)
    payload: dict[str, Any] = {
        "ticket_id": "TICKET-102",
        "subject": "Need help",
        "description": "Please help me with my account.",
        "channel": "social",
    }

    response = client.post("/api/v1/tickets/analyze", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"][0]["loc"] == ["body", "channel"]


def test_analyze_ticket_returns_503_for_service_failure() -> None:
    class FailingTicketAnalysisService:
        async def analyze(
            self, ticket: TicketAnalysisRequest
        ) -> TicketAnalysisResponse:
            raise TicketAnalysisProviderError("provider failed")

    app.dependency_overrides[get_ticket_analysis_service] = lambda: (
        FailingTicketAnalysisService()
    )
    client = TestClient(app)
    payload: dict[str, Any] = {
        "ticket_id": "TICKET-104",
        "subject": "Need help",
        "description": "Please help me with my account.",
        "channel": "email",
    }

    try:
        response = client.post("/api/v1/tickets/analyze", json=payload)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "ticket_analysis_unavailable",
            "message": "Ticket analysis is temporarily unavailable.",
        }
    }
