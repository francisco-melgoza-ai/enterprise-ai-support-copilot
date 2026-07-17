import asyncio
import logging
import os
import re
import time
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

from app.core.metrics import record_retrieval_request
from app.schemas.retrieval import RetrievedPassage
from app.schemas.tickets import TicketAnalysisRequest

logger = logging.getLogger(__name__)

DEFAULT_KNOWLEDGE_DIRECTORY = Path("sample_data/knowledge")
SUPPORTED_EXTENSIONS = {".md", ".markdown", ".txt"}
CHUNK_MAX_WORDS = 120
CHUNK_OVERLAP_WORDS = 20
DEFAULT_TOP_K = 3
DEFAULT_LOCAL_RETRIEVAL_MIN_SCORE = 0.22
LOCAL_RETRIEVAL_MIN_OVERLAP = 2
DEFAULT_VERTEX_RAG_PROVIDER = "vertex_rag"
RAG_CORPUS_RESOURCE_PATTERN = re.compile(
    r"^projects/(?P<project>[^/]+)/locations/(?P<location>[^/]+)/ragCorpora/[^/]+$"
)
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
    "about",
    "after",
    "can",
    "could",
    "customer",
    "feature",
    "features",
    "find",
    "general",
    "help",
    "how",
    "issue",
    "me",
    "my",
    "new",
    "notes",
    "page",
    "preference",
    "preferences",
    "question",
    "release",
    "request",
    "support",
    "tell",
    "thanks",
    "understand",
    "update",
    "user",
    "users",
    "we",
    "what",
    "where",
    "workspace",
    "you",
    "your",
}


class KnowledgeRetriever(Protocol):
    async def retrieve(self, ticket: TicketAnalysisRequest) -> list[RetrievedPassage]:
        """Retrieve approved support passages relevant to a ticket."""


class VertexRagAdapter(Protocol):
    async def retrieve_contexts(
        self,
        *,
        corpus_resource_name: str,
        query_text: str,
        top_k: int,
        distance_threshold: float,
    ) -> object:
        """Retrieve raw contexts from a managed Vertex AI RAG corpus."""


class KnowledgeConfigurationError(ValueError):
    """Raised when knowledge retrieval is not configured correctly."""


class KnowledgeRetrievalError(RuntimeError):
    """Raised when managed knowledge retrieval fails."""


class KnowledgeResponseError(KnowledgeRetrievalError):
    """Raised when managed retrieval returns an unexpected response shape."""


class LocalKnowledgeRetriever:
    def __init__(
        self,
        *,
        knowledge_directory: Path = DEFAULT_KNOWLEDGE_DIRECTORY,
        top_k: int = DEFAULT_TOP_K,
        chunk_max_words: int = CHUNK_MAX_WORDS,
        chunk_overlap_words: int = CHUNK_OVERLAP_WORDS,
        min_score: float | None = None,
    ) -> None:
        if top_k <= 0:
            raise ValueError("top_k must be positive.")
        if chunk_max_words <= 0:
            raise ValueError("chunk_max_words must be positive.")
        if chunk_overlap_words < 0 or chunk_overlap_words >= chunk_max_words:
            raise ValueError("chunk_overlap_words must be less than chunk_max_words.")
        configured_min_score = (
            _local_retrieval_min_score_from_env() if min_score is None else min_score
        )
        if configured_min_score < 0:
            raise ValueError("min_score must be zero or greater.")

        self._knowledge_directory = knowledge_directory
        self._top_k = top_k
        self._chunk_max_words = chunk_max_words
        self._chunk_overlap_words = chunk_overlap_words
        self._min_score = configured_min_score

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
            duration_seconds = time.perf_counter() - started_at
            record_retrieval_request(
                provider="local",
                outcome=outcome,
                retrieved_chunk_count=len(passages),
                duration_seconds=duration_seconds,
            )
            logger.info(
                "knowledge_retrieval_completed",
                extra={
                    "provider": "local",
                    "retrieved_chunk_count": len(passages),
                    "duration_ms": round(duration_seconds * 1000, 2),
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
                if score < self._min_score:
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
        if overlap < LOCAL_RETRIEVAL_MIN_OVERLAP:
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


class VertexRagKnowledgeRetriever:
    def __init__(
        self,
        *,
        corpus_resource_name: str,
        project: str,
        location: str,
        top_k: int = DEFAULT_TOP_K,
        distance_threshold: float = 0.5,
        adapter: VertexRagAdapter | None = None,
    ) -> None:
        if not corpus_resource_name.strip():
            raise KnowledgeConfigurationError("RAG_CORPUS_RESOURCE_NAME is required.")
        if not project.strip():
            raise KnowledgeConfigurationError(
                "GOOGLE_CLOUD_PROJECT or a project in RAG_CORPUS_RESOURCE_NAME "
                "is required."
            )
        if not location.strip():
            raise KnowledgeConfigurationError("RAG_LOCATION is required.")
        if top_k <= 0:
            raise KnowledgeConfigurationError("RAG_TOP_K must be positive.")
        if distance_threshold < 0:
            raise KnowledgeConfigurationError(
                "RAG_DISTANCE_THRESHOLD must be zero or greater."
            )

        self._corpus_resource_name = corpus_resource_name
        self._top_k = top_k
        self._distance_threshold = distance_threshold
        self._adapter = adapter or AgentPlatformRagAdapter(
            project=project,
            location=location,
        )

    async def retrieve(self, ticket: TicketAnalysisRequest) -> list[RetrievedPassage]:
        started_at = time.perf_counter()
        outcome = "success"
        passages: list[RetrievedPassage] = []

        try:
            response = await self._adapter.retrieve_contexts(
                corpus_resource_name=self._corpus_resource_name,
                query_text=self._query_text(ticket),
                top_k=self._top_k,
                distance_threshold=self._distance_threshold,
            )
            passages = self._map_response(response)
            if not passages:
                outcome = "no_results"
            return passages
        except TimeoutError as exc:
            outcome = "timeout"
            raise KnowledgeRetrievalError("Vertex RAG retrieval timed out.") from exc
        except KnowledgeResponseError:
            outcome = "error"
            raise
        except Exception as exc:
            outcome = "error"
            raise KnowledgeRetrievalError("Vertex RAG retrieval failed.") from exc
        finally:
            duration_seconds = time.perf_counter() - started_at
            record_retrieval_request(
                provider=DEFAULT_VERTEX_RAG_PROVIDER,
                outcome=outcome,
                retrieved_chunk_count=len(passages),
                duration_seconds=duration_seconds,
            )
            logger.info(
                "knowledge_retrieval_completed",
                extra={
                    "provider": DEFAULT_VERTEX_RAG_PROVIDER,
                    "retrieved_chunk_count": len(passages),
                    "duration_ms": round(duration_seconds * 1000, 2),
                    "outcome": outcome,
                },
            )

    def _query_text(self, ticket: TicketAnalysisRequest) -> str:
        return f"{ticket.subject}\n\n{ticket.description}"

    def _map_response(self, response: object) -> list[RetrievedPassage]:
        has_contexts, contexts_container = _get_value_if_present(response, "contexts")
        if not has_contexts:
            raise KnowledgeResponseError("Vertex RAG response is missing contexts.")
        if contexts_container is None:
            return []

        has_context_results, contexts = _get_value_if_present(
            contexts_container,
            "contexts",
        )
        if not has_context_results:
            raise KnowledgeResponseError(
                "Vertex RAG response is missing context results."
            )
        if contexts is None:
            return []
        if not isinstance(contexts, Sequence) or isinstance(contexts, str):
            raise KnowledgeResponseError("Vertex RAG response contexts must be a list.")

        passages: list[RetrievedPassage] = []
        for context in contexts:
            content = _optional_string(_get_value(context, "text"))
            source_path = _optional_string(_get_value(context, "source_uri"))
            if not content or not source_path:
                continue

            source_name = _optional_string(
                _get_value(context, "source_display_name")
            ) or _source_name_from_uri(source_path)
            distance = _optional_float(_get_value(context, "score"))
            if distance is None or distance < 0:
                continue

            relevance_score = _normalized_relevance_score(distance)
            passages.append(
                RetrievedPassage(
                    content=content,
                    source_name=source_name,
                    source_path=source_path,
                    relevance_score=relevance_score,
                )
            )

        return sorted(
            passages,
            key=lambda passage: (
                -passage.relevance_score,
                passage.source_path,
                passage.source_name,
                passage.content,
            ),
        )


class AgentPlatformRagAdapter:
    def __init__(self, *, project: str, location: str) -> None:
        self._project = project
        self._location = location
        self._client: Any | None = None
        self._agent_types: Any | None = None
        self._genai_types: Any | None = None

    async def retrieve_contexts(
        self,
        *,
        corpus_resource_name: str,
        query_text: str,
        top_k: int,
        distance_threshold: float,
    ) -> object:
        return await asyncio.to_thread(
            self._retrieve_contexts,
            corpus_resource_name=corpus_resource_name,
            query_text=query_text,
            top_k=top_k,
            distance_threshold=distance_threshold,
        )

    async def list_corpora(self) -> object:
        return await asyncio.to_thread(self._client_instance().rag.list_corpora)

    async def create_corpus(self, *, display_name: str) -> object:
        agent_types = self._agent_types_module()
        return await asyncio.to_thread(
            self._client_instance().rag.create_corpus,
            rag_corpus=agent_types.RagCorpus(displayName=display_name),
        )

    async def import_files(self, *, corpus_resource_name: str, gcs_uri: str) -> object:
        agent_types = self._agent_types_module()
        genai_types = self._genai_types_module()
        import_config = agent_types.ImportRagFilesConfig(
            gcsSource=genai_types.GcsSource(uris=[gcs_uri])
        )
        return await asyncio.to_thread(
            self._client_instance().rag.import_files,
            name=corpus_resource_name,
            import_config=import_config,
        )

    def _retrieve_contexts(
        self,
        *,
        corpus_resource_name: str,
        query_text: str,
        top_k: int,
        distance_threshold: float,
    ) -> object:
        agent_types = self._agent_types_module()
        genai_types = self._genai_types_module()
        retrieval_config = genai_types.RagRetrievalConfig(
            topK=top_k,
            filter=genai_types.RagRetrievalConfigFilter(
                vectorDistanceThreshold=distance_threshold
            ),
        )
        vertex_rag_store = genai_types.VertexRagStore(
            ragResources=[
                genai_types.VertexRagStoreRagResource(
                    ragCorpus=corpus_resource_name,
                )
            ],
        )
        query = agent_types.RagQuery(
            text=query_text,
            ragRetrievalConfig=retrieval_config,
        )
        return self._client_instance().rag.retrieve_contexts(
            vertex_rag_store=vertex_rag_store,
            query=query,
        )

    def _client_instance(self) -> Any:
        if self._client is None:
            import agentplatform  # type: ignore[import-untyped]

            self._client = agentplatform.Client(
                project=self._project,
                location=self._location,
            )
        return self._client

    def _agent_types_module(self) -> Any:
        if self._agent_types is None:
            from agentplatform import types as agent_types

            self._agent_types = agent_types
        return self._agent_types

    def _genai_types_module(self) -> Any:
        if self._genai_types is None:
            from google.genai import types as genai_types

            self._genai_types = genai_types
        return self._genai_types


def parse_rag_corpus_resource_name(resource_name: str) -> tuple[str, str]:
    match = RAG_CORPUS_RESOURCE_PATTERN.match(resource_name)
    if match is None:
        raise KnowledgeConfigurationError(
            "RAG_CORPUS_RESOURCE_NAME must use format "
            "'projects/{project}/locations/{location}/ragCorpora/{corpus_id}'."
        )
    return match.group("project"), match.group("location")


def _get_value(value: object, key: str) -> object:
    _present, field_value = _get_value_if_present(value, key)
    return field_value


def _get_value_if_present(value: object, key: str) -> tuple[bool, object]:
    if isinstance(value, dict):
        for candidate in _field_name_candidates(key):
            if candidate in value:
                return True, value[candidate]
        return False, None

    for candidate in _field_name_candidates(key):
        if hasattr(value, candidate):
            return True, getattr(value, candidate)
    return False, None


def _field_name_candidates(key: str) -> tuple[str, ...]:
    snake_key = _camel_to_snake(key)
    camel_key = _snake_to_camel(key)
    return tuple(dict.fromkeys((key, snake_key, camel_key)))


def _camel_to_snake(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()


def _snake_to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


def _source_name_from_uri(source_uri: str) -> str:
    stripped = source_uri.rstrip("/")
    final_segment = stripped.rsplit("/", maxsplit=1)[-1]
    return final_segment or "vertex-rag-source"


def _normalized_relevance_score(distance: float) -> float:
    # Vertex RAG currently returns a vector distance in the SDK's score field.
    # RetrievedPassage.relevance_score is higher-is-better, so normalize distance
    # into the existing contract while preserving the ordering semantics.
    return round(1 / (1 + distance), 6)


def _optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _local_retrieval_min_score_from_env() -> float:
    value = os.getenv("LOCAL_RETRIEVAL_MIN_SCORE")
    if value is None or not value.strip():
        return DEFAULT_LOCAL_RETRIEVAL_MIN_SCORE
    return float(value.strip())
