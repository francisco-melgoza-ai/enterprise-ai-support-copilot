import logging

import pytest

from app.schemas.tickets import TicketAnalysisRequest
from app.services.knowledge import LocalKnowledgeRetriever


@pytest.mark.anyio
async def test_local_retriever_loads_markdown_and_text_documents(tmp_path) -> None:
    (tmp_path / "account.md").write_text("Password reset account recovery procedure.")
    (tmp_path / "billing.txt").write_text("Invoice dispute billing procedure.")
    (tmp_path / "ignored.pdf").write_text("This unsupported file should be ignored.")
    retriever = LocalKnowledgeRetriever(knowledge_directory=tmp_path, top_k=5)

    passages = await retriever.retrieve(_ticket("password reset account"))

    assert [passage.source_name for passage in passages] == ["account.md"]


def test_local_retriever_chunking_is_deterministic(tmp_path) -> None:
    retriever = LocalKnowledgeRetriever(
        knowledge_directory=tmp_path,
        chunk_max_words=5,
        chunk_overlap_words=1,
    )
    content = "one two three four five six seven eight nine"

    first = retriever._chunk_document(content)
    second = retriever._chunk_document(content)

    assert first == second
    assert first == [
        "one two three four five",
        "five six seven eight nine",
    ]


@pytest.mark.anyio
async def test_local_retriever_ranks_by_lexical_relevance(tmp_path) -> None:
    (tmp_path / "account.md").write_text("Password reset invoice recovery.")
    (tmp_path / "billing.md").write_text("Billing invoice refund dispute charge.")
    retriever = LocalKnowledgeRetriever(knowledge_directory=tmp_path, top_k=2)

    passages = await retriever.retrieve(_ticket("refund invoice dispute"))

    assert passages[0].source_name == "billing.md"
    assert passages[0].relevance_score > passages[1].relevance_score


@pytest.mark.anyio
async def test_local_retriever_returns_empty_list_when_no_chunks_match(
    tmp_path,
) -> None:
    (tmp_path / "account.md").write_text("Password reset account recovery.")
    retriever = LocalKnowledgeRetriever(knowledge_directory=tmp_path)

    passages = await retriever.retrieve(_ticket("zzqv rrxn unmatched"))

    assert passages == []


@pytest.mark.anyio
async def test_local_retriever_telemetry_does_not_log_content_or_filenames(
    tmp_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    (tmp_path / "sensitive_filename.md").write_text("Password reset secret content.")
    retriever = LocalKnowledgeRetriever(knowledge_directory=tmp_path)

    await retriever.retrieve(_ticket("password reset"))

    assert "sensitive_filename" not in caplog.text
    assert "secret content" not in caplog.text
    telemetry = [
        record
        for record in caplog.records
        if record.getMessage() == "knowledge_retrieval_completed"
    ][-1]
    assert telemetry.provider == "local"
    assert telemetry.retrieved_chunk_count == 1
    assert telemetry.outcome == "success"
    assert telemetry.duration_ms >= 0


def _ticket(text: str) -> TicketAnalysisRequest:
    return TicketAnalysisRequest(
        ticket_id="TICKET-1",
        subject=text,
        description=text,
        channel="email",
    )
