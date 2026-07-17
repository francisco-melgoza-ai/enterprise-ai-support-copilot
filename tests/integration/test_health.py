from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_authentication_provider
from app.api.dependencies.services import get_ticket_analysis_service
from app.main import app
from app.schemas.tickets import TicketAnalysisRequest, TicketAnalysisResponse
from app.services.ticket_analysis import TicketAnalysisProviderError

AGENT_HEADERS = {"Authorization": "Bearer mock:agent-123:support_agent"}
MANAGER_HEADERS = {"Authorization": "Bearer mock:manager-456:support_manager"}
ADMIN_HEADERS = {"Authorization": "Bearer mock:admin-789:platform_admin"}


@pytest.fixture(autouse=True)
def use_mock_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_PROVIDER", "mock")
    monkeypatch.setenv("APP_ENV", "local")
    get_authentication_provider.cache_clear()
    yield
    get_authentication_provider.cache_clear()


def test_health_endpoint() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_endpoint_returns_generated_request_id() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    request_id = response.headers["X-Request-ID"]
    assert str(UUID(request_id)) == request_id


def test_health_endpoint_preserves_incoming_request_id() -> None:
    client = TestClient(app)

    response = client.get("/health", headers={"X-Request-ID": "request-123"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "request-123"


def test_ready_endpoint_returns_structured_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TICKET_ANALYSIS_PROVIDER", "mock")
    monkeypatch.setenv("KNOWLEDGE_PROVIDER", "none")
    client = TestClient(app)

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "provider": "mock",
        "knowledge_provider": "none",
    }


def test_metrics_endpoint_returns_prometheus_metrics() -> None:
    client = TestClient(app)

    response = client.get("/metrics", headers=MANAGER_HEADERS)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert "support_copilot_http_requests_total" in body
    assert "support_copilot_http_request_duration_seconds" in body
    assert "support_copilot_ticket_analysis_requests_total" in body
    assert "support_copilot_provider_request_duration_seconds" in body
    assert "support_copilot_retrieval_duration_seconds" in body


def test_metrics_count_http_requests_by_route_template() -> None:
    client = TestClient(app)
    before = _metric_value(
        client.get("/metrics", headers=MANAGER_HEADERS).text,
        "support_copilot_http_requests_total",
        {"endpoint": "/health", "method": "GET", "status_code": "200"},
    )

    response = client.get("/health", headers={"X-Request-ID": "metric-request-id"})

    after = _metric_value(
        client.get("/metrics", headers=MANAGER_HEADERS).text,
        "support_copilot_http_requests_total",
        {"endpoint": "/health", "method": "GET", "status_code": "200"},
    )
    assert response.status_code == 200
    assert after == before + 1


def test_metrics_count_failed_http_requests() -> None:
    client = TestClient(app)
    before = _metric_value(
        client.get("/metrics", headers=MANAGER_HEADERS).text,
        "support_copilot_http_requests_total",
        {"endpoint": "unmatched", "method": "GET", "status_code": "404"},
    )

    response = client.get("/does-not-exist")

    after = _metric_value(
        client.get("/metrics", headers=MANAGER_HEADERS).text,
        "support_copilot_http_requests_total",
        {"endpoint": "unmatched", "method": "GET", "status_code": "404"},
    )
    assert response.status_code == 404
    assert after == before + 1


def test_ticket_analysis_metrics_increment_and_avoid_sensitive_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TICKET_ANALYSIS_PROVIDER", "mock")
    get_ticket_analysis_service.cache_clear()
    client = TestClient(app)
    payload = {
        "ticket_id": "TICKET-METRICS-SECRET",
        "subject": "Sensitive metrics subject",
        "description": "Sensitive metrics description",
        "channel": "email",
    }
    before = _metric_value(
        client.get("/metrics", headers=MANAGER_HEADERS).text,
        "support_copilot_ticket_analysis_requests_total",
        {},
    )

    response = client.post(
        "/api/v1/tickets/analyze",
        json=payload,
        headers={**AGENT_HEADERS, "X-Request-ID": "metrics-secret-request-id"},
    )

    metrics = client.get("/metrics", headers=MANAGER_HEADERS).text
    after = _metric_value(
        metrics,
        "support_copilot_ticket_analysis_requests_total",
        {},
    )
    assert response.status_code == 200
    assert after == before + 1
    assert "metrics-secret-request-id" not in metrics
    assert "TICKET-METRICS-SECRET" not in metrics
    assert "Sensitive metrics subject" not in metrics
    assert "Sensitive metrics description" not in metrics


def test_ticket_analysis_failure_metric_increments() -> None:
    class FailingTicketAnalysisService:
        async def analyze(
            self, ticket: TicketAnalysisRequest, memory_context: object | None = None
        ) -> TicketAnalysisResponse:
            raise TicketAnalysisProviderError("provider failed")

    app.dependency_overrides[get_ticket_analysis_service] = lambda: (
        FailingTicketAnalysisService()
    )
    client = TestClient(app)
    before = _metric_value(
        client.get("/metrics", headers=MANAGER_HEADERS).text,
        "support_copilot_ticket_analysis_failure_total",
        {},
    )
    payload = {
        "ticket_id": "TICKET-FAILURE-METRICS",
        "subject": "Need help",
        "description": "Please help me with my account.",
        "channel": "email",
    }

    try:
        response = client.post(
            "/api/v1/tickets/analyze", json=payload, headers=AGENT_HEADERS
        )
    finally:
        app.dependency_overrides.clear()

    after = _metric_value(
        client.get("/metrics", headers=MANAGER_HEADERS).text,
        "support_copilot_ticket_analysis_failure_total",
        {},
    )
    assert response.status_code == 503
    assert after == before + 1


def test_metrics_endpoint_requires_authentication() -> None:
    client = TestClient(app)

    response = client.get("/metrics")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "authentication_failed"


def test_metrics_endpoint_rejects_insufficient_role() -> None:
    client = TestClient(app)

    response = client.get("/metrics", headers=AGENT_HEADERS)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "authorization_failed"


def test_metrics_endpoint_accepts_admin_token() -> None:
    client = TestClient(app)

    response = client.get("/metrics", headers=ADMIN_HEADERS)

    assert response.status_code == 200


def test_authentication_and_authorization_metrics_increment() -> None:
    client = TestClient(app)
    before_auth = _metric_value(
        client.get("/metrics", headers=MANAGER_HEADERS).text,
        "support_copilot_authentication_requests_total",
        {"provider": "mock", "outcome": "success"},
    )
    before_authz = _metric_value(
        client.get("/metrics", headers=MANAGER_HEADERS).text,
        "support_copilot_authorization_requests_total",
        {"outcome": "success"},
    )

    response = client.get("/metrics", headers=ADMIN_HEADERS)

    metrics = client.get("/metrics", headers=MANAGER_HEADERS).text
    assert response.status_code == 200
    assert (
        _metric_value(
            metrics,
            "support_copilot_authentication_requests_total",
            {"provider": "mock", "outcome": "success"},
        )
        > before_auth
    )
    assert (
        _metric_value(
            metrics,
            "support_copilot_authorization_requests_total",
            {"outcome": "success"},
        )
        > before_authz
    )
    assert "mock:manager-456:support_manager" not in metrics
    assert "manager-456" not in metrics
    assert "admin-789" not in metrics


def _metric_value(
    metrics_text: str,
    metric_name: str,
    labels: dict[str, str],
) -> float:
    for line in metrics_text.splitlines():
        if line.startswith("#"):
            continue
        if not _metric_line_matches(line, metric_name, labels):
            continue
        return float(line.rsplit(" ", maxsplit=1)[-1])
    return 0.0


def _metric_line_matches(
    line: str,
    metric_name: str,
    labels: dict[str, str],
) -> bool:
    if labels:
        if not line.startswith(f"{metric_name}{{"):
            return False
        return all(f'{key}="{value}"' in line for key, value in labels.items())
    return line.startswith(f"{metric_name} ")
