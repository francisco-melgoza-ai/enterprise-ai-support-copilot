from typing import Any

from fastapi.testclient import TestClient

from app.main import app


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
