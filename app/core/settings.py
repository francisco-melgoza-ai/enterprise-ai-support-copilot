import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_TICKET_ANALYSIS_PROVIDER = "mock"
DEFAULT_KNOWLEDGE_PROVIDER = "none"
DEFAULT_GOOGLE_CLOUD_LOCATION = "us-central1"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_APP_ENV = "local"
DEFAULT_RAG_TOP_K = 3
DEFAULT_RAG_DISTANCE_THRESHOLD = 0.5


@dataclass(frozen=True)
class TicketAnalysisSettings:
    app_env: str
    provider: str
    knowledge_provider: str
    google_cloud_project: str | None
    google_cloud_location: str
    gemini_model: str
    rag_corpus_resource_name: str | None
    rag_location: str
    rag_top_k: int
    rag_distance_threshold: float

    @classmethod
    def from_env(
        cls, dotenv_path: str | Path | None = None
    ) -> "TicketAnalysisSettings":
        load_dotenv(dotenv_path=dotenv_path, override=False)

        return cls(
            app_env=os.getenv("APP_ENV", DEFAULT_APP_ENV).strip() or DEFAULT_APP_ENV,
            provider=os.getenv(
                "TICKET_ANALYSIS_PROVIDER", DEFAULT_TICKET_ANALYSIS_PROVIDER
            ).strip()
            or DEFAULT_TICKET_ANALYSIS_PROVIDER,
            knowledge_provider=os.getenv(
                "KNOWLEDGE_PROVIDER", DEFAULT_KNOWLEDGE_PROVIDER
            ).strip()
            or DEFAULT_KNOWLEDGE_PROVIDER,
            google_cloud_project=_optional_env("GOOGLE_CLOUD_PROJECT"),
            google_cloud_location=os.getenv(
                "GOOGLE_CLOUD_LOCATION", DEFAULT_GOOGLE_CLOUD_LOCATION
            ).strip()
            or DEFAULT_GOOGLE_CLOUD_LOCATION,
            gemini_model=os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip()
            or DEFAULT_GEMINI_MODEL,
            rag_corpus_resource_name=_optional_env("RAG_CORPUS_RESOURCE_NAME"),
            rag_location=os.getenv(
                "RAG_LOCATION",
                os.getenv("GOOGLE_CLOUD_LOCATION", DEFAULT_GOOGLE_CLOUD_LOCATION),
            ).strip()
            or DEFAULT_GOOGLE_CLOUD_LOCATION,
            rag_top_k=_int_env("RAG_TOP_K", DEFAULT_RAG_TOP_K),
            rag_distance_threshold=_float_env(
                "RAG_DISTANCE_THRESHOLD", DEFAULT_RAG_DISTANCE_THRESHOLD
            ),
        )


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return int(value.strip())


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return float(value.strip())
