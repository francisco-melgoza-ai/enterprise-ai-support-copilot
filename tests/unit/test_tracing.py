import logging
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.genai import types
from opentelemetry.trace import StatusCode

from app.api.dependencies.auth import get_authentication_provider
from app.api.dependencies.services import get_ticket_analysis_service
from app.core.auth import MockAuthenticationProvider
from app.core.settings import TicketAnalysisSettings
from app.core.tracing import (
    TracingSettings,
    clear_finished_spans,
    configure_tracing,
    get_finished_spans,
    get_tracer,
)
from app.main import app
from app.schemas.tickets import TicketAnalysisRequest, TicketAnalysisResponse
from app.services.knowledge import LocalKnowledgeRetriever
from app.services.ticket_analysis import (
    GeminiTicketAnalysisService,
    TicketAnalysisProviderError,
)


@pytest.fixture(autouse=True)
def clear_spans() -> None:
    _enable_memory_tracing()
    clear_finished_spans()
    yield
    app.dependency_overrides.clear()
    get_authentication_provider.cache_clear()
    get_ticket_analysis_service.cache_clear()
    clear_finished_spans()


def test_tracing_disabled_mode() -> None:
    state = configure_tracing(
        FastAPI(),
        TracingSettings(enabled=False, exporter="memory"),
    )

    assert not state.enabled
    assert state.exporter == "none"


def test_tracing_initialization_is_idempotent() -> None:
    first = _enable_memory_tracing()
    second = _enable_memory_tracing()

    assert first.enabled
    assert second.enabled
    assert first == second


def test_request_and_ticket_analysis_spans_are_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TICKET_ANALYSIS_PROVIDER", "mock")
    monkeypatch.setenv("AUTH_PROVIDER", "mock")
    get_authentication_provider.cache_clear()
    get_ticket_analysis_service.cache_clear()
    client = TestClient(app)

    response = client.post(
        "/api/v1/tickets/analyze",
        json=_ticket_payload(),
        headers={
            "Authorization": "Bearer mock:agent-123:support_agent",
            "X-Request-ID": "trace-request-id",
        },
    )

    spans = get_finished_spans()
    assert response.status_code == 200
    assert _span_named(spans, "ticket.analysis") is not None
    assert any(
        span.attributes.get("http.request_id") == "trace-request-id" for span in spans
    )


@pytest.mark.anyio
async def test_custom_retrieval_span_is_created(tmp_path: Path) -> None:
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "account.md").write_text("Account access reset procedure.")
    retriever = LocalKnowledgeRetriever(knowledge_directory=knowledge_dir, min_score=0)

    await retriever.retrieve(_ticket_request())

    span = _span_named(get_finished_spans(), "knowledge.retrieve")
    assert span is not None
    assert span.attributes["knowledge.provider"] == "local"
    assert span.attributes["knowledge.outcome"] == "success"
    assert span.attributes["knowledge.retrieved_chunk_count"] == 1


@pytest.mark.anyio
async def test_custom_provider_span_is_created() -> None:
    service = GeminiTicketAnalysisService(
        project="test-project",
        location="us-central1",
        model="gemini-2.5-flash",
        model_client=_SuccessfulGeminiClient(),
    )

    await service.analyze(_ticket_request())

    span = _span_named(get_finished_spans(), "provider.generate")
    assert span is not None
    assert span.attributes["ai.provider"] == "gemini"
    assert span.attributes["ai.model"] == "gemini-2.5-flash"
    assert span.attributes["ai.outcome"] == "success"
    assert span.attributes["retry.attempt_count"] == 1


@pytest.mark.anyio
async def test_authentication_span_is_created() -> None:
    provider = MockAuthenticationProvider(settings=TicketAnalysisSettings.from_env())

    await provider.authenticate("mock:agent-123:support_agent")

    span = _span_named(get_finished_spans(), "auth.authenticate")
    assert span is not None
    assert span.attributes["auth.provider"] == "mock"
    assert span.attributes["auth.outcome"] == "success"
    assert span.attributes["auth.role_count"] == 1
    serialized_attributes = " ".join(str(value) for value in span.attributes.values())
    assert "agent-123" not in serialized_attributes
    assert "mock:agent-123:support_agent" not in serialized_attributes


@pytest.mark.anyio
async def test_failed_provider_span_records_exception() -> None:
    service = GeminiTicketAnalysisService(
        project="test-project",
        location="us-central1",
        model="gemini-2.5-flash",
        max_attempts=1,
        model_client=_FailingGeminiClient(),
    )

    with pytest.raises(TicketAnalysisProviderError):
        await service.analyze(_ticket_request())

    span = _span_named(get_finished_spans(), "provider.generate")
    assert span is not None
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["ai.outcome"] == "error"
    assert any(event.name == "exception" for event in span.events)


def test_trace_and_span_ids_are_added_to_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    tracer = get_tracer(__name__)

    with tracer.start_as_current_span("log.correlation"):
        logging.getLogger("app.test").info("trace_log_test")

    record = next(record for record in caplog.records if record.name == "app.test")
    assert isinstance(record.trace_id, str)
    assert isinstance(record.span_id, str)
    assert len(record.trace_id) == 32
    assert len(record.span_id) == 16


@pytest.mark.anyio
async def test_span_attributes_do_not_include_sensitive_content(
    tmp_path: Path,
) -> None:
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "policy.md").write_text("Sensitive retrieved content marker.")
    retriever = LocalKnowledgeRetriever(knowledge_directory=knowledge_dir, min_score=0)
    service = GeminiTicketAnalysisService(
        project="test-project",
        location="us-central1",
        model="gemini-2.5-flash",
        model_client=_SuccessfulGeminiClient(),
        knowledge_retriever=retriever,
    )

    await service.analyze(
        TicketAnalysisRequest(
            ticket_id="SENSITIVE-TICKET-ID",
            subject="Sensitive ticket subject marker",
            description="Sensitive ticket description marker",
            channel="email",
        )
    )

    serialized_attributes = " ".join(
        str(value)
        for span in get_finished_spans()
        for value in span.attributes.values()
    )
    assert "SENSITIVE-TICKET-ID" not in serialized_attributes
    assert "Sensitive ticket subject marker" not in serialized_attributes
    assert "Sensitive ticket description marker" not in serialized_attributes
    assert "Sensitive retrieved content marker" not in serialized_attributes
    assert "safe generated response marker" not in serialized_attributes


def _enable_memory_tracing() -> Any:
    return configure_tracing(
        app,
        TracingSettings(enabled=True, exporter="memory"),
    )


def _span_named(spans: list[Any], name: str) -> Any | None:
    return next((span for span in spans if span.name == name), None)


def _ticket_payload() -> dict[str, str]:
    return {
        "ticket_id": "TICKET-TRACE",
        "subject": "Payment failed",
        "description": "Invoice payment failed.",
        "channel": "email",
    }


def _ticket_request() -> TicketAnalysisRequest:
    return TicketAnalysisRequest(
        ticket_id="TICKET-TRACE",
        subject="Payment failed",
        description="Invoice payment failed.",
        channel="email",
    )


def _ticket_response() -> TicketAnalysisResponse:
    return TicketAnalysisResponse(
        ticket_id="TICKET-TRACE",
        summary="Invoice payment failed.",
        category="billing",
        priority="medium",
        sentiment="neutral",
        requires_escalation=False,
        escalation_reason=None,
        suggested_response="safe generated response marker",
        confidence=0.84,
    )


class _GeminiResponse:
    parsed = _ticket_response()


class _SuccessfulGeminiClient:
    async def generate_content(
        self,
        *,
        model: str,
        contents: str,
        config: types.GenerateContentConfig,
    ) -> _GeminiResponse:
        return _GeminiResponse()


class _FailingGeminiClient:
    async def generate_content(
        self,
        *,
        model: str,
        contents: str,
        config: types.GenerateContentConfig,
    ) -> _GeminiResponse:
        raise RuntimeError("provider unavailable")
