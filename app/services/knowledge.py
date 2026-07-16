import logging
import re
import time
from collections import Counter
from pathlib import Path
from typing import Protocol

from app.schemas.retrieval import RetrievedPassage
from app.schemas.tickets import TicketAnalysisRequest

logger = logging.getLogger(__name__)

DEFAULT_KNOWLEDGE_DIRECTORY = Path("sample_data/knowledge")
SUPPORTED_EXTENSIONS = {".md", ".markdown", ".txt"}
CHUNK_MAX_WORDS = 120
CHUNK_OVERLAP_WORDS = 20
DEFAULT_TOP_K = 3
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "for",
    "from",
    "i",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "please",
    "the",
    "to",
    "with",
}


class KnowledgeRetriever(Protocol):
    async def retrieve(self, ticket: TicketAnalysisRequest) -> list[RetrievedPassage]:
        """Retrieve approved support passages relevant to a ticket."""


class LocalKnowledgeRetriever:
    def __init__(
        self,
        *,
        knowledge_directory: Path = DEFAULT_KNOWLEDGE_DIRECTORY,
        top_k: int = DEFAULT_TOP_K,
        chunk_max_words: int = CHUNK_MAX_WORDS,
        chunk_overlap_words: int = CHUNK_OVERLAP_WORDS,
    ) -> None:
        if top_k <= 0:
            raise ValueError("top_k must be positive.")
        if chunk_max_words <= 0:
            raise ValueError("chunk_max_words must be positive.")
        if chunk_overlap_words < 0 or chunk_overlap_words >= chunk_max_words:
            raise ValueError("chunk_overlap_words must be less than chunk_max_words.")

        self._knowledge_directory = knowledge_directory
        self._top_k = top_k
        self._chunk_max_words = chunk_max_words
        self._chunk_overlap_words = chunk_overlap_words

    async def retrieve(self, ticket: TicketAnalysisRequest) -> list[RetrievedPassage]:
        started_at = time.perf_counter()
        outcome = "success"
        passages: list[RetrievedPassage] = []

        try:
            passages = self._retrieve(ticket)
            if not passages:
                outcome = "no_results"
            return passages
        except Exception:
            outcome = "error"
            raise
        finally:
            logger.info(
                "knowledge_retrieval_completed",
                extra={
                    "provider": "local",
                    "retrieved_chunk_count": len(passages),
                    "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                    "outcome": outcome,
                },
            )

    def _retrieve(self, ticket: TicketAnalysisRequest) -> list[RetrievedPassage]:
        query_terms = self._query_terms(ticket)
        if not query_terms:
            return []

        scored: list[RetrievedPassage] = []
        for document in self._load_documents():
            for chunk in self._chunk_document(document.content):
                score = self._score_chunk(query_terms, chunk)
                if score <= 0:
                    continue
                scored.append(
                    RetrievedPassage(
                        content=chunk,
                        source_name=document.path.name,
                        source_path=document.path.as_posix(),
                        relevance_score=score,
                    )
                )

        return sorted(
            scored,
            key=lambda passage: (
                -passage.relevance_score,
                passage.source_path,
                passage.source_name,
                passage.content,
            ),
        )[: self._top_k]

    def _load_documents(self) -> list["_KnowledgeDocument"]:
        if not self._knowledge_directory.exists():
            return []

        documents: list[_KnowledgeDocument] = []
        for path in sorted(self._knowledge_directory.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            documents.append(_KnowledgeDocument(path=path, content=path.read_text()))
        return documents

    def _chunk_document(self, content: str) -> list[str]:
        normalized = " ".join(content.split())
        words = normalized.split()
        if not words:
            return []

        chunks: list[str] = []
        step = self._chunk_max_words - self._chunk_overlap_words
        for start in range(0, len(words), step):
            chunk = " ".join(words[start : start + self._chunk_max_words])
            if chunk:
                chunks.append(chunk)
            if start + self._chunk_max_words >= len(words):
                break
        return chunks

    def _query_terms(self, ticket: TicketAnalysisRequest) -> Counter[str]:
        subject_terms = self._tokens(ticket.subject)
        description_terms = self._tokens(ticket.description)
        weighted = Counter(description_terms)
        weighted.update(subject_terms)
        weighted.update(subject_terms)
        return weighted

    def _score_chunk(self, query_terms: Counter[str], chunk: str) -> float:
        chunk_terms = Counter(self._tokens(chunk))
        if not chunk_terms:
            return 0

        overlap = 0
        for term, query_count in query_terms.items():
            overlap += min(query_count, chunk_terms.get(term, 0))

        if overlap == 0:
            return 0
        return round(overlap / len(query_terms), 6)

    def _tokens(self, text: str) -> list[str]:
        return [
            token
            for token in re.findall(r"[a-z0-9]+", text.lower())
            if token not in STOPWORDS and len(token) > 1
        ]


class _KnowledgeDocument:
    def __init__(self, *, path: Path, content: str) -> None:
        self.path = path
        self.content = content
