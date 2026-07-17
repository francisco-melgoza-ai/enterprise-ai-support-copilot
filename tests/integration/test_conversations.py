from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_authentication_provider
from app.api.dependencies.conversations import (
    get_conversation_repository,
    get_conversation_service,
)
from app.api.dependencies.services import get_ticket_analysis_service
from app.main import app
from app.schemas.conversations import ConversationMemoryContext
from app.schemas.tickets import TicketAnalysisRequest, TicketAnalysisResponse
from app.services.ticket_analysis import (
    TicketAnalysisService,
    TicketAnalysisServiceError,
)

AGENT_HEADERS = {"Authorization": "Bearer mock:agent-123:support_agent"}
OTHER_AGENT_HEADERS = {"Authorization": "Bearer mock:agent-999:support_agent"}
MANAGER_HEADERS = {"Authorization": "Bearer mock:manager-456:support_manager"}
ADMIN_HEADERS = {"Authorization": "Bearer mock:admin-789:platform_admin"}


@pytest.fixture(autouse=True)
def reset_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_PROVIDER", "mock")
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("TICKET_ANALYSIS_PROVIDER", "mock")
    monkeypatch.setenv("CONVERSATION_SUMMARY_THRESHOLD", "12")
    monkeypatch.setenv("CONVERSATION_MAX_RECENT_MESSAGES", "6")
    get_authentication_provider.cache_clear()
    get_conversation_repository.cache_clear()
    get_conversation_service.cache_clear()
    get_ticket_analysis_service.cache_clear()
    yield
    app.dependency_overrides.clear()
    get_authentication_provider.cache_clear()
    get_conversation_repository.cache_clear()
    get_conversation_service.cache_clear()
    get_ticket_analysis_service.cache_clear()


def test_conversation_lifecycle_endpoints() -> None:
    client = TestClient(app)

    created = client.post(
        "/api/v1/conversations",
        json={"metadata": {"source": "integration"}},
        headers=AGENT_HEADERS,
    )
    conversation_id = created.json()["conversation_id"]
    loaded = client.get(
        f"/api/v1/conversations/{conversation_id}", headers=AGENT_HEADERS
    )
    appended = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"role": "user", "content": "Need help with billing."},
        headers=AGENT_HEADERS,
    )
    messages = client.get(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=AGENT_HEADERS,
    )
    deleted = client.delete(
        f"/api/v1/conversations/{conversation_id}",
        headers=AGENT_HEADERS,
    )
    missing = client.get(
        f"/api/v1/conversations/{conversation_id}",
        headers=AGENT_HEADERS,
    )

    assert created.status_code == 201
    assert loaded.status_code == 200
    assert loaded.json()["metadata"] == {"source": "integration"}
    assert appended.status_code == 201
    assert messages.status_code == 200
    assert len(messages.json()) == 1
    assert deleted.status_code == 204
    assert missing.status_code == 404


def test_conversation_requires_authentication() -> None:
    client = TestClient(app)

    response = client.post("/api/v1/conversations", json={})

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_conversation_owner_is_enforced() -> None:
    client = TestClient(app)
    created = client.post("/api/v1/conversations", json={}, headers=AGENT_HEADERS)
    conversation_id = created.json()["conversation_id"]

    response = client.get(
        f"/api/v1/conversations/{conversation_id}",
        headers=OTHER_AGENT_HEADERS,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "conversation_not_found"


def test_append_message_requires_owner() -> None:
    client = TestClient(app)
    created = client.post("/api/v1/conversations", json={}, headers=AGENT_HEADERS)
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"role": "user", "content": "hello"},
        headers=OTHER_AGENT_HEADERS,
    )

    assert response.status_code == 404


def test_platform_admin_can_access_any_conversation() -> None:
    client = TestClient(app)
    created = client.post("/api/v1/conversations", json={}, headers=AGENT_HEADERS)
    conversation_id = created.json()["conversation_id"]

    response = client.get(
        f"/api/v1/conversations/{conversation_id}",
        headers=ADMIN_HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["conversation_id"] == conversation_id


def test_platform_admin_can_delete_any_conversation() -> None:
    client = TestClient(app)
    created = client.post("/api/v1/conversations", json={}, headers=AGENT_HEADERS)
    conversation_id = created.json()["conversation_id"]

    response = client.delete(
        f"/api/v1/conversations/{conversation_id}",
        headers=ADMIN_HEADERS,
    )

    assert response.status_code == 204


def test_ticket_analysis_with_conversation_appends_user_and_assistant_messages() -> (
    None
):
    client = TestClient(app)
    created = client.post("/api/v1/conversations", json={}, headers=AGENT_HEADERS)
    conversation_id = created.json()["conversation_id"]
    payload: dict[str, Any] = {
        "ticket_id": "TICKET-CONV-1",
        "subject": "Payment failed",
        "description": "Invoice payment failed and the customer is frustrated.",
        "channel": "email",
        "conversation_id": conversation_id,
    }

    response = client.post(
        "/api/v1/tickets/analyze",
        json=payload,
        headers=AGENT_HEADERS,
    )
    messages = client.get(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=AGENT_HEADERS,
    )

    assert response.status_code == 200
    assert messages.status_code == 200
    roles = [message["role"] for message in messages.json()]
    assert roles == ["user", "assistant"]


def test_ticket_analysis_rejects_conversation_owned_by_other_user() -> None:
    client = TestClient(app)
    created = client.post("/api/v1/conversations", json={}, headers=AGENT_HEADERS)
    conversation_id = created.json()["conversation_id"]
    payload: dict[str, Any] = {
        "ticket_id": "TICKET-CONV-403",
        "subject": "Payment failed",
        "description": "Invoice payment failed.",
        "channel": "email",
        "conversation_id": conversation_id,
    }

    response = client.post(
        "/api/v1/tickets/analyze",
        json=payload,
        headers=OTHER_AGENT_HEADERS,
    )

    assert response.status_code == 404


def test_append_message_rejects_empty_content() -> None:
    client = TestClient(app)
    created = client.post("/api/v1/conversations", json={}, headers=AGENT_HEADERS)
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"role": "user", "content": " "},
        headers=AGENT_HEADERS,
    )

    assert response.status_code == 422


def test_append_message_accepts_system_role_for_admin() -> None:
    client = TestClient(app)
    created = client.post("/api/v1/conversations", json={}, headers=AGENT_HEADERS)
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"role": "system", "content": "System note."},
        headers=ADMIN_HEADERS,
    )

    assert response.status_code == 201
    assert response.json()["role"] == "system"


def test_append_message_rejects_system_role_for_agent() -> None:
    client = TestClient(app)
    created = client.post("/api/v1/conversations", json={}, headers=AGENT_HEADERS)
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"role": "system", "content": "System note."},
        headers=AGENT_HEADERS,
    )

    assert response.status_code == 403


def test_expired_conversation_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONVERSATION_TTL_SECONDS", "1")
    get_conversation_repository.cache_clear()
    get_conversation_service.cache_clear()
    client = TestClient(app)
    created = client.post("/api/v1/conversations", json={}, headers=AGENT_HEADERS)
    conversation_id = created.json()["conversation_id"]
    service = get_conversation_service()
    conversation = service._repository._conversations[conversation_id]  # noqa: SLF001
    service._repository._conversations[conversation_id] = conversation.model_copy(  # noqa: SLF001
        update={"expires_at": conversation.created_at}
    )

    response = client.get(
        f"/api/v1/conversations/{conversation_id}",
        headers=AGENT_HEADERS,
    )

    assert response.status_code == 404


def test_expired_conversation_append_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONVERSATION_TTL_SECONDS", "1")
    get_conversation_repository.cache_clear()
    get_conversation_service.cache_clear()
    client = TestClient(app)
    created = client.post("/api/v1/conversations", json={}, headers=AGENT_HEADERS)
    conversation_id = created.json()["conversation_id"]
    service = get_conversation_service()
    conversation = service._repository._conversations[conversation_id]  # noqa: SLF001
    service._repository._conversations[conversation_id] = conversation.model_copy(  # noqa: SLF001
        update={"expires_at": conversation.created_at}
    )

    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"role": "user", "content": "hello"},
        headers=AGENT_HEADERS,
    )

    assert response.status_code == 404


def test_list_messages_applies_limit() -> None:
    client = TestClient(app)
    created = client.post("/api/v1/conversations", json={}, headers=AGENT_HEADERS)
    conversation_id = created.json()["conversation_id"]
    for index in range(3):
        client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"role": "user", "content": f"message {index}"},
            headers=AGENT_HEADERS,
        )

    response = client.get(
        f"/api/v1/conversations/{conversation_id}/messages?limit=2",
        headers=AGENT_HEADERS,
    )

    assert response.status_code == 200
    assert [message["content"] for message in response.json()] == [
        "message 1",
        "message 2",
    ]


def test_append_message_rejects_oversized_content() -> None:
    client = TestClient(app)
    created = client.post("/api/v1/conversations", json={}, headers=AGENT_HEADERS)
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"role": "user", "content": "x" * 5001},
        headers=AGENT_HEADERS,
    )

    assert response.status_code == 422


def test_ticket_analysis_failure_does_not_append_messages() -> None:
    client = TestClient(app)
    app.dependency_overrides[get_ticket_analysis_service] = _failing_ticket_service
    created = client.post("/api/v1/conversations", json={}, headers=AGENT_HEADERS)
    conversation_id = created.json()["conversation_id"]
    payload: dict[str, Any] = {
        "ticket_id": "TICKET-CONV-FAIL",
        "subject": "Payment failed",
        "description": "Invoice payment failed.",
        "channel": "email",
        "conversation_id": conversation_id,
    }

    response = client.post(
        "/api/v1/tickets/analyze",
        json=payload,
        headers=AGENT_HEADERS,
    )
    messages = client.get(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=AGENT_HEADERS,
    )

    assert response.status_code == 503
    assert messages.status_code == 200
    assert messages.json() == []


def test_ticket_analysis_rejects_empty_conversation_id() -> None:
    client = TestClient(app)
    payload: dict[str, Any] = {
        "ticket_id": "TICKET-CONV-EMPTY",
        "subject": "Payment failed",
        "description": "Invoice payment failed.",
        "channel": "email",
        "conversation_id": " ",
    }

    response = client.post(
        "/api/v1/tickets/analyze",
        json=payload,
        headers=AGENT_HEADERS,
    )

    assert response.status_code == 422


def test_conversation_api_does_not_log_message_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO")
    client = TestClient(app)
    created = client.post("/api/v1/conversations", json={}, headers=AGENT_HEADERS)
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"role": "user", "content": "Sensitive conversation marker"},
        headers=AGENT_HEADERS,
    )

    assert response.status_code == 201
    assert "Sensitive conversation marker" not in caplog.text


def test_conversation_metrics_are_recorded() -> None:
    client = TestClient(app)
    created = client.post("/api/v1/conversations", json={}, headers=AGENT_HEADERS)
    conversation_id = created.json()["conversation_id"]

    client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"role": "user", "content": "Need help."},
        headers=AGENT_HEADERS,
    )

    metrics = client.get("/metrics", headers=MANAGER_HEADERS).text
    assert "support_copilot_conversations_created_total" in metrics
    assert "support_copilot_active_conversations" in metrics
    assert "support_copilot_conversation_messages_added_total" in metrics
    assert "support_copilot_average_conversation_length" in metrics
    assert "Need help." not in metrics
    assert conversation_id not in metrics


class FailingTicketService(TicketAnalysisService):
    async def analyze(
        self,
        ticket: TicketAnalysisRequest,
        memory_context: ConversationMemoryContext | None = None,
    ) -> TicketAnalysisResponse:
        raise TicketAnalysisServiceError("provider unavailable")


def _failing_ticket_service() -> TicketAnalysisService:
    return FailingTicketService()
