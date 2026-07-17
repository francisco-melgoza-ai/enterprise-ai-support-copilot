import logging
import warnings

import pytest

from app.core.resilience import (
    CircuitBreaker,
    CircuitBreakerConfig,
    ResiliencePolicy,
    RetryPolicy,
    TimeoutPolicy,
)
from app.schemas.tickets import TicketAnalysisRequest
from app.services.knowledge import (
    KnowledgeConfigurationError,
    KnowledgeResponseError,
    KnowledgeRetrievalError,
    VertexRagKnowledgeRetriever,
)


class FakeVertexRagAdapter:
    def __init__(self, response: object | Exception | list[object | Exception]) -> None:
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
        response = self.response
        if isinstance(response, list):
            response = response.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_installed_sdk_retrieve_contexts_response_shape() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        agentplatform = pytest.importorskip("agentplatform")
        agent_types = agentplatform.types

    response = agent_types.RetrieveContextsResponse(
        contexts=agent_types.RagContexts(
            contexts=[
                agent_types.RagContextsContext(
                    source_uri="",
                    source_display_name=None,
                    text="",
                    score=0.0,
                )
            ]
        )
    )

    dumped = response.model_dump()
    context = dumped["contexts"]["contexts"][0]

    assert type(response).__name__ == "RetrieveContextsResponse"
    assert list(type(response).model_fields.keys()) == ["contexts"]
    assert {"source_uri", "source_display_name", "text", "score"} <= set(context)


@pytest.mark.anyio
async def test_vertex_rag_retriever_maps_successful_response(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        agentplatform = pytest.importorskip("agentplatform")
        agent_types = agentplatform.types
    adapter = FakeVertexRagAdapter(
        agent_types.RetrieveContextsResponse(
            contexts=agent_types.RagContexts(
                contexts=[
                    agent_types.RagContextsContext(
                        text="Reset MFA through the account recovery procedure.",
                        source_display_name=None,
                        source_uri="gs://support-kb/account-access.md",
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
    assert passages[0].relevance_score == 0.549451
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
async def test_vertex_rag_retriever_maps_dictionary_response() -> None:
    retriever = _retriever(
        FakeVertexRagAdapter(
            {
                "contexts": {
                    "contexts": [
                        {
                            "text": "Escalate confirmed outages to incident command.",
                            "source_display_name": "outage.md",
                            "source_uri": "gs://support-kb/outage.md",
                            "score": 0.75,
                        }
                    ]
                }
            }
        )
    )

    passages = await retriever.retrieve(_ticket())

    assert passages[0].content == "Escalate confirmed outages to incident command."
    assert passages[0].source_name == "outage.md"
    assert passages[0].source_path == "gs://support-kb/outage.md"
    assert passages[0].relevance_score == 0.571429


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
async def test_vertex_rag_retriever_returns_empty_list_when_contexts_are_none(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        agentplatform = pytest.importorskip("agentplatform")
        agent_types = agentplatform.types
    retriever = _retriever(FakeVertexRagAdapter(agent_types.RetrieveContextsResponse()))

    passages = await retriever.retrieve(_ticket())

    assert passages == []
    telemetry = _telemetry_record(caplog)
    assert telemetry.provider == "vertex_rag"
    assert telemetry.retrieved_chunk_count == 0
    assert telemetry.outcome == "no_results"


@pytest.mark.anyio
async def test_vertex_rag_retriever_returns_empty_list_when_nested_contexts_are_none(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        agentplatform = pytest.importorskip("agentplatform")
        agent_types = agentplatform.types
    retriever = _retriever(
        FakeVertexRagAdapter(
            agent_types.RetrieveContextsResponse(contexts=agent_types.RagContexts())
        )
    )

    passages = await retriever.retrieve(_ticket())

    assert passages == []
    telemetry = _telemetry_record(caplog)
    assert telemetry.provider == "vertex_rag"
    assert telemetry.retrieved_chunk_count == 0
    assert telemetry.outcome == "no_results"


@pytest.mark.anyio
async def test_vertex_rag_retriever_returns_empty_list_for_dictionary_no_results(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    for response in (
        {"contexts": None},
        {"contexts": {"contexts": None}},
        {"contexts": {"contexts": []}},
    ):
        retriever = _retriever(FakeVertexRagAdapter(response))

        passages = await retriever.retrieve(_ticket())

        assert passages == []


@pytest.mark.anyio
async def test_vertex_rag_retriever_raises_for_completely_malformed_response(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    retriever = _retriever(FakeVertexRagAdapter({"not_contexts": []}))

    with pytest.raises(KnowledgeResponseError):
        await retriever.retrieve(_ticket())

    telemetry = _telemetry_record(caplog)
    assert telemetry.provider == "vertex_rag"
    assert telemetry.retrieved_chunk_count == 0
    assert telemetry.outcome == "error"


@pytest.mark.anyio
async def test_vertex_rag_retriever_raises_for_incompatible_contexts_structure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    retriever = _retriever(FakeVertexRagAdapter({"contexts": {"contexts": "bad"}}))

    with pytest.raises(KnowledgeResponseError):
        await retriever.retrieve(_ticket())

    telemetry = _telemetry_record(caplog)
    assert telemetry.provider == "vertex_rag"
    assert telemetry.retrieved_chunk_count == 0
    assert telemetry.outcome == "error"


@pytest.mark.anyio
async def test_vertex_rag_retriever_skips_malformed_contexts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    retriever = _retriever(
        FakeVertexRagAdapter(
            {
                "contexts": {
                    "contexts": [
                        {"source_display_name": "missing-text.md"},
                        {
                            "text": "Valid passage.",
                            "source_uri": "gs://support-kb/valid.md",
                            "source_display_name": "valid.md",
                            "score": 0.5,
                        },
                    ]
                }
            }
        )
    )

    passages = await retriever.retrieve(_ticket())

    assert len(passages) == 1
    assert passages[0].source_name == "valid.md"
    assert passages[0].relevance_score == 0.666667
    telemetry = _telemetry_record(caplog)
    assert telemetry.provider == "vertex_rag"
    assert telemetry.retrieved_chunk_count == 1
    assert telemetry.outcome == "success"


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


@pytest.mark.anyio
async def test_vertex_rag_retriever_retries_transient_failure() -> None:
    adapter = FakeVertexRagAdapter(
        [
            ConnectionError(),
            {"contexts": {"contexts": []}},
        ]
    )
    retriever = _retriever(adapter, resilience_policy=_resilience_policy())

    passages = await retriever.retrieve(_ticket())

    assert passages == []
    assert len(adapter.calls) == 2


@pytest.mark.anyio
async def test_vertex_rag_retriever_open_circuit_prevents_invocation() -> None:
    adapter = FakeVertexRagAdapter({"contexts": {"contexts": []}})
    circuit = CircuitBreaker(
        component="vertex_rag",
        config=CircuitBreakerConfig(
            enabled=True,
            failure_threshold=1,
            recovery_timeout_seconds=30,
            half_open_max_calls=1,
        ),
    )
    await circuit.record_failure()
    retriever = _retriever(
        adapter,
        circuit_breaker=circuit,
        resilience_policy=_resilience_policy(),
    )

    with pytest.raises(KnowledgeRetrievalError):
        await retriever.retrieve(_ticket())

    assert adapter.calls == []


@pytest.mark.anyio
async def test_vertex_rag_graceful_degradation_returns_empty_passages() -> None:
    adapter = FakeVertexRagAdapter(ConnectionError())
    retriever = _retriever(
        adapter,
        resilience_policy=_resilience_policy(max_attempts=1),
        graceful_degradation_enabled=True,
    )

    passages = await retriever.retrieve(_ticket())

    assert passages == []
    assert len(adapter.calls) == 1


@pytest.mark.anyio
async def test_vertex_rag_non_degradable_mapping_failure_propagates() -> None:
    retriever = _retriever(
        FakeVertexRagAdapter({"not_contexts": []}),
        graceful_degradation_enabled=True,
    )

    with pytest.raises(KnowledgeResponseError):
        await retriever.retrieve(_ticket())


def test_vertex_rag_retriever_requires_corpus_configuration() -> None:
    with pytest.raises(KnowledgeConfigurationError):
        VertexRagKnowledgeRetriever(
            corpus_resource_name="",
            project="test-project",
            location="us-central1",
            adapter=FakeVertexRagAdapter({"contexts": {"contexts": []}}),
        )


@pytest.mark.anyio
async def test_vertex_rag_retriever_normalizes_and_sorts_distances() -> None:
    retriever = _retriever(
        FakeVertexRagAdapter(
            {
                "contexts": {
                    "contexts": [
                        {
                            "text": "Farther match.",
                            "source_display_name": "far.md",
                            "source_uri": "gs://support-kb/far.md",
                            "score": 2.0,
                        },
                        {
                            "text": "Closer match.",
                            "source_display_name": "close.md",
                            "source_uri": "gs://support-kb/close.md",
                            "score": 0.25,
                        },
                    ]
                }
            }
        )
    )

    passages = await retriever.retrieve(_ticket())

    assert [passage.source_name for passage in passages] == ["close.md", "far.md"]
    assert passages[0].relevance_score == 0.8
    assert passages[1].relevance_score == 0.333333


@pytest.mark.anyio
async def test_vertex_rag_retriever_zero_distance_maps_to_one() -> None:
    retriever = _retriever(
        FakeVertexRagAdapter(
            {
                "contexts": {
                    "contexts": [
                        {
                            "text": "Exact match.",
                            "source_display_name": "exact.md",
                            "source_uri": "gs://support-kb/exact.md",
                            "score": 0.0,
                        }
                    ]
                }
            }
        )
    )

    passages = await retriever.retrieve(_ticket())

    assert passages[0].source_name == "exact.md"
    assert passages[0].relevance_score == 1.0


@pytest.mark.anyio
async def test_vertex_rag_retriever_skips_missing_or_invalid_distance() -> None:
    retriever = _retriever(
        FakeVertexRagAdapter(
            {
                "contexts": {
                    "contexts": [
                        {
                            "text": "Missing score.",
                            "source_uri": "gs://support-kb/missing.md",
                        },
                        {
                            "text": "Invalid score.",
                            "source_uri": "gs://support-kb/invalid.md",
                            "score": -0.1,
                        },
                        {
                            "text": "Valid score.",
                            "source_uri": "gs://support-kb/valid.md",
                            "score": 1.0,
                        },
                    ]
                }
            }
        )
    )

    passages = await retriever.retrieve(_ticket())

    assert len(passages) == 1
    assert passages[0].source_name == "valid.md"
    assert passages[0].relevance_score == 0.5


def _retriever(
    adapter: FakeVertexRagAdapter,
    *,
    resilience_policy: ResiliencePolicy | None = None,
    circuit_breaker: CircuitBreaker | None = None,
    graceful_degradation_enabled: bool = False,
) -> VertexRagKnowledgeRetriever:
    return VertexRagKnowledgeRetriever(
        corpus_resource_name=(
            "projects/test-project/locations/us-central1/ragCorpora/test-corpus"
        ),
        project="test-project",
        location="us-central1",
        top_k=3,
        distance_threshold=0.5,
        adapter=adapter,
        resilience_policy=resilience_policy,
        circuit_breaker=circuit_breaker,
        graceful_degradation_enabled=graceful_degradation_enabled,
    )


def _resilience_policy(max_attempts: int = 2) -> ResiliencePolicy:
    return ResiliencePolicy(
        timeout=TimeoutPolicy(timeout_seconds=1),
        retry=RetryPolicy(
            max_attempts=max_attempts,
            base_delay_seconds=0,
            max_delay_seconds=0,
            jitter_seconds=0,
        ),
        circuit_breaker=CircuitBreakerConfig(
            enabled=True,
            failure_threshold=2,
            recovery_timeout_seconds=30,
            half_open_max_calls=1,
        ),
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
