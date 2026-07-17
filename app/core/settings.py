import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from app.core.resilience import (
    CircuitBreakerConfig,
    ResiliencePolicy,
    RetryPolicy,
    TimeoutPolicy,
)

DEFAULT_TICKET_ANALYSIS_PROVIDER = "mock"
DEFAULT_KNOWLEDGE_PROVIDER = "none"
DEFAULT_GOOGLE_CLOUD_LOCATION = "us-central1"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_APP_ENV = "local"
DEFAULT_RAG_TOP_K = 3
DEFAULT_RAG_DISTANCE_THRESHOLD = 0.5
DEFAULT_GEMINI_TIMEOUT_SECONDS = 20.0
DEFAULT_GEMINI_MAX_ATTEMPTS = 3
DEFAULT_GEMINI_RETRY_BASE_DELAY_SECONDS = 0.25
DEFAULT_GEMINI_RETRY_MAX_DELAY_SECONDS = 4.0
DEFAULT_GEMINI_RETRY_JITTER_SECONDS = 0.25
DEFAULT_GEMINI_CIRCUIT_BREAKER_ENABLED = True
DEFAULT_GEMINI_CIRCUIT_FAILURE_THRESHOLD = 5
DEFAULT_GEMINI_CIRCUIT_RECOVERY_SECONDS = 30.0
DEFAULT_GEMINI_CIRCUIT_HALF_OPEN_MAX_CALLS = 1
DEFAULT_RAG_TIMEOUT_SECONDS = 10.0
DEFAULT_RAG_MAX_ATTEMPTS = 2
DEFAULT_RAG_RETRY_BASE_DELAY_SECONDS = 0.2
DEFAULT_RAG_RETRY_MAX_DELAY_SECONDS = 2.0
DEFAULT_RAG_RETRY_JITTER_SECONDS = 0.2
DEFAULT_RAG_CIRCUIT_BREAKER_ENABLED = True
DEFAULT_RAG_CIRCUIT_FAILURE_THRESHOLD = 5
DEFAULT_RAG_CIRCUIT_RECOVERY_SECONDS = 30.0
DEFAULT_RAG_CIRCUIT_HALF_OPEN_MAX_CALLS = 1
DEFAULT_RAG_GRACEFUL_DEGRADATION_ENABLED = True
DEFAULT_AUTH_PROVIDER = "mock"
DEFAULT_AUTH_MOCK_ALLOW_IN_PRODUCTION = False
SUPPORTED_AUTH_PROVIDERS = {"mock", "google"}
DEFAULT_CONVERSATION_TTL_SECONDS = 86_400
DEFAULT_CONVERSATION_SUMMARY_THRESHOLD = 12
DEFAULT_CONVERSATION_MAX_RECENT_MESSAGES = 6


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
    gemini_resilience: ResiliencePolicy
    rag_resilience: ResiliencePolicy
    rag_graceful_degradation_enabled: bool
    auth_provider: str
    auth_google_audience: str | None
    auth_mock_allow_in_production: bool
    conversation_ttl_seconds: int
    conversation_summary_threshold: int
    conversation_max_recent_messages: int

    @classmethod
    def from_env(
        cls, dotenv_path: str | Path | None = None
    ) -> "TicketAnalysisSettings":
        load_dotenv(dotenv_path=dotenv_path, override=False)

        settings = cls(
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
            gemini_resilience=_resilience_policy_from_env(
                prefix="GEMINI",
                timeout_default=DEFAULT_GEMINI_TIMEOUT_SECONDS,
                max_attempts_default=DEFAULT_GEMINI_MAX_ATTEMPTS,
                base_delay_default=DEFAULT_GEMINI_RETRY_BASE_DELAY_SECONDS,
                max_delay_default=DEFAULT_GEMINI_RETRY_MAX_DELAY_SECONDS,
                jitter_default=DEFAULT_GEMINI_RETRY_JITTER_SECONDS,
                circuit_enabled_default=DEFAULT_GEMINI_CIRCUIT_BREAKER_ENABLED,
                failure_threshold_default=DEFAULT_GEMINI_CIRCUIT_FAILURE_THRESHOLD,
                recovery_default=DEFAULT_GEMINI_CIRCUIT_RECOVERY_SECONDS,
                half_open_default=DEFAULT_GEMINI_CIRCUIT_HALF_OPEN_MAX_CALLS,
            ),
            rag_resilience=_resilience_policy_from_env(
                prefix="RAG",
                timeout_default=DEFAULT_RAG_TIMEOUT_SECONDS,
                max_attempts_default=DEFAULT_RAG_MAX_ATTEMPTS,
                base_delay_default=DEFAULT_RAG_RETRY_BASE_DELAY_SECONDS,
                max_delay_default=DEFAULT_RAG_RETRY_MAX_DELAY_SECONDS,
                jitter_default=DEFAULT_RAG_RETRY_JITTER_SECONDS,
                circuit_enabled_default=DEFAULT_RAG_CIRCUIT_BREAKER_ENABLED,
                failure_threshold_default=DEFAULT_RAG_CIRCUIT_FAILURE_THRESHOLD,
                recovery_default=DEFAULT_RAG_CIRCUIT_RECOVERY_SECONDS,
                half_open_default=DEFAULT_RAG_CIRCUIT_HALF_OPEN_MAX_CALLS,
            ),
            rag_graceful_degradation_enabled=_bool_env(
                "RAG_GRACEFUL_DEGRADATION_ENABLED",
                DEFAULT_RAG_GRACEFUL_DEGRADATION_ENABLED,
            ),
            auth_provider=_auth_provider_env(),
            auth_google_audience=_optional_env("AUTH_GOOGLE_AUDIENCE"),
            auth_mock_allow_in_production=_bool_env(
                "AUTH_MOCK_ALLOW_IN_PRODUCTION",
                DEFAULT_AUTH_MOCK_ALLOW_IN_PRODUCTION,
            ),
            conversation_ttl_seconds=_positive_int_env(
                "CONVERSATION_TTL_SECONDS",
                DEFAULT_CONVERSATION_TTL_SECONDS,
            ),
            conversation_summary_threshold=_positive_int_env(
                "CONVERSATION_SUMMARY_THRESHOLD",
                DEFAULT_CONVERSATION_SUMMARY_THRESHOLD,
            ),
            conversation_max_recent_messages=_positive_int_env(
                "CONVERSATION_MAX_RECENT_MESSAGES",
                DEFAULT_CONVERSATION_MAX_RECENT_MESSAGES,
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.conversation_summary_threshold <= self.conversation_max_recent_messages:
            raise ValueError(
                "CONVERSATION_SUMMARY_THRESHOLD must be greater than "
                "CONVERSATION_MAX_RECENT_MESSAGES."
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


def _positive_int_env(name: str, default: int) -> int:
    value = _int_env(name, default)
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero.")
    return value


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return float(value.strip())


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _auth_provider_env() -> str:
    provider = os.getenv("AUTH_PROVIDER", DEFAULT_AUTH_PROVIDER).strip().lower()
    normalized = provider or DEFAULT_AUTH_PROVIDER
    if normalized not in SUPPORTED_AUTH_PROVIDERS:
        raise ValueError("AUTH_PROVIDER must be one of: mock, google.")
    return normalized


def _resilience_policy_from_env(
    *,
    prefix: str,
    timeout_default: float,
    max_attempts_default: int,
    base_delay_default: float,
    max_delay_default: float,
    jitter_default: float,
    circuit_enabled_default: bool,
    failure_threshold_default: int,
    recovery_default: float,
    half_open_default: int,
) -> ResiliencePolicy:
    return ResiliencePolicy(
        timeout=TimeoutPolicy(
            timeout_seconds=_float_env(f"{prefix}_TIMEOUT_SECONDS", timeout_default)
        ),
        retry=RetryPolicy(
            max_attempts=_int_env(f"{prefix}_MAX_ATTEMPTS", max_attempts_default),
            base_delay_seconds=_float_env(
                f"{prefix}_RETRY_BASE_DELAY_SECONDS", base_delay_default
            ),
            max_delay_seconds=_float_env(
                f"{prefix}_RETRY_MAX_DELAY_SECONDS", max_delay_default
            ),
            jitter_seconds=_float_env(f"{prefix}_RETRY_JITTER_SECONDS", jitter_default),
        ),
        circuit_breaker=CircuitBreakerConfig(
            enabled=_bool_env(
                f"{prefix}_CIRCUIT_BREAKER_ENABLED", circuit_enabled_default
            ),
            failure_threshold=_int_env(
                f"{prefix}_CIRCUIT_FAILURE_THRESHOLD", failure_threshold_default
            ),
            recovery_timeout_seconds=_float_env(
                f"{prefix}_CIRCUIT_RECOVERY_SECONDS", recovery_default
            ),
            half_open_max_calls=_int_env(
                f"{prefix}_CIRCUIT_HALF_OPEN_MAX_CALLS", half_open_default
            ),
        ),
    )
