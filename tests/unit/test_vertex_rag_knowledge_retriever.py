import logging
from types import SimpleNamespace

import pytest

from app.schemas.tickets import TicketAnalysisRequest
from app.services.knowledge import (
    KnowledgeConfigurationError,
    KnowledgeResponseError,
    KnowledgeRetrievalError,
    VertexRagKnowledgeRetriever,
)


class FakeVertexRagAdapter:
    def __init__(self, response: object | Exception) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    async def retrieve_contexts(
        self,
        *,
        corpus_resource_name: str,
        query_text: str,
        top_k: int,
        distance_threshold: float,
    ) -> object:
        self.calls.append(
            {
                "corpus_resource_name": corpus_resource_name,
                "query_text": query_text,
                "top_k": top_k,
                "distance_threshold": distance_threshold,
            }
        )
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


@pytest.mark.anyio
async def test_vertex_rag_retriever_maps_successful_response(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    adapter = FakeVertexRagAdapter(
        SimpleNamespace(
            contexts=SimpleNamespace(
                contexts=[
                    SimpleNamespace(
                        text="Reset MFA through the account recovery procedure.",
                        sourceDisplayName="account-access.md",
                        sourceUri="gs://support-kb/account-access.md",
                        score=0.82,
                    )
                ]
            )
        )
    )
    retriever = _retriever(adapter)

    passages = await retriever.retrieve(_ticket())

    assert passages[0].content == "Reset MFA through the account recovery procedure."
    assert passages[0].source_name == "account-access.md"
    assert passages[0].source_path == "gs://support-kb/account-access.md"
    assert passages[0].relevance_score == 0.82
    assert adapter.calls[0]["top_k"] == 3
    telemetry = _telemetry_record(caplog)
    assert telemetry.provider == "vertex_rag"
    assert telemetry.retrieved_chunk_count == 1
    assert telemetry.outcome == "success"
    assert telemetry.duration_ms >= 0
    assert "Cannot access account" not in caplog.text
    assert "Reset MFA" not in caplog.text
    assert "gs://support-kb" not in caplog.text


@pytest.mark.anyio
async def test_vertex_rag_retriever_returns_empty_list_for_no_results(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    retriever = _retriever(
        FakeVertexRagAdapter({"contexts": {"contexts": []}}),
    )

    passages = await retriever.retrieve(_ticket())

    assert passages == []
    telemetry = _telemetry_record(caplog)
    assert telemetry.provider == "vertex_rag"
    assert telemetry.retrieved_chunk_count == 0
    assert telemetry.outcome == "no_results"


@pytest.mark.anyio
async def test_vertex_rag_retriever_rejects_malformed_sdk_response(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    retriever = _retriever(
        FakeVertexRagAdapter(
            {"contexts": {"contexts": [{"sourceDisplayName": "missing-text.md"}]}}
        )
    )

    with pytest.raises(KnowledgeResponseError):
        await retriever.retrieve(_ticket())

    telemetry = _telemetry_record(caplog)
    assert telemetry.provider == "vertex_rag"
    assert telemetry.retrieved_chunk_count == 0
    assert telemetry.outcome == "error"


@pytest.mark.anyio
async def test_vertex_rag_retriever_reports_timeout(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    retriever = _retriever(FakeVertexRagAdapter(TimeoutError()))

    with pytest.raises(KnowledgeRetrievalError):
        await retriever.retrieve(_ticket())

    telemetry = _telemetry_record(caplog)
    assert telemetry.provider == "vertex_rag"
    assert telemetry.retrieved_chunk_count == 0
    assert telemetry.outcome == "timeout"


@pytest.mark.anyio
async def test_vertex_rag_retriever_reports_service_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    retriever = _retriever(FakeVertexRagAdapter(RuntimeError("service failed")))

    with pytest.raises(KnowledgeRetrievalError):
        await retriever.retrieve(_ticket())

    telemetry = _telemetry_record(caplog)
    assert telemetry.provider == "vertex_rag"
    assert telemetry.retrieved_chunk_count == 0
    assert telemetry.outcome == "error"
    assert "service failed" not in caplog.text


def test_vertex_rag_retriever_requires_corpus_configuration() -> None:
    with pytest.raises(KnowledgeConfigurationError):
        VertexRagKnowledgeRetriever(
            corpus_resource_name="",
            project="test-project",
            location="us-central1",
            adapter=FakeVertexRagAdapter({"contexts": {"contexts": []}}),
        )


@pytest.mark.anyio
async def test_vertex_rag_retriever_maps_distance_to_relevance_score() -> None:
    retriever = _retriever(
        FakeVertexRagAdapter(
            {
                "contexts": {
                    "contexts": [
                        {
                            "text": "Escalate confirmed outages to incident command.",
                            "source_display_name": "outage.md",
                            "source_uri": "gs://support-kb/outage.md",
                            "distance": 0.25,
                        }
                    ]
                }
            }
        )
    )

    passages = await retriever.retrieve(_ticket())

    assert passages[0].source_name == "outage.md"
    assert passages[0].source_path == "gs://support-kb/outage.md"
    assert passages[0].relevance_score == 0.75


def _retriever(adapter: FakeVertexRagAdapter) -> VertexRagKnowledgeRetriever:
    return VertexRagKnowledgeRetriever(
        corpus_resource_name=(
            "projects/test-project/locations/us-central1/ragCorpora/test-corpus"
        ),
        project="test-project",
        location="us-central1",
        top_k=3,
        distance_threshold=0.5,
        adapter=adapter,
    )


def _ticket() -> TicketAnalysisRequest:
    return TicketAnalysisRequest(
        ticket_id="TICKET-1",
        subject="Cannot access account",
        description="Customer cannot access account with MFA.",
        channel="email",
    )


def _telemetry_record(caplog: pytest.LogCaptureFixture) -> logging.LogRecord:
    records = [
        record
        for record in caplog.records
        if record.getMessage() == "knowledge_retrieval_completed"
    ]
    assert records
    return records[-1]
