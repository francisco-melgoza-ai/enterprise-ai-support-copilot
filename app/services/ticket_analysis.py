import asyncio
import json
import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from google import genai
from google.genai import types
from pydantic import ValidationError

from app.core.metrics import record_provider_request
from app.core.resilience import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitOpenError,
    ResiliencePolicy,
    RetryPolicy,
    TimeoutPolicy,
    failure_reason,
    is_transient_exception,
    run_with_resilience,
)
from app.core.tracing import get_tracer, record_span_exception, set_span_attributes
from app.schemas.conversations import ConversationMemoryContext
from app.schemas.tickets import (
    TicketAnalysisRequest,
    TicketAnalysisResponse,
    TicketPriority,
    TicketSentiment,
)
from app.services.knowledge import KnowledgeRetriever
from app.services.prompts import (
    TICKET_ANALYSIS_SYSTEM_PROMPT,
    build_ticket_analysis_prompt,
)

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)


class TicketAnalysisServiceError(Exception):
    """Base class for safe ticket-analysis service failures."""


class TicketAnalysisConfigurationError(TicketAnalysisServiceError):
    """Raised when a provider is configured incorrectly."""


class TicketAnalysisProviderError(TicketAnalysisServiceError):
    """Raised when the configured provider cannot complete analysis."""

    def __init__(self, message: str, *, is_timeout: bool = False) -> None:
        super().__init__(message)
        self.is_timeout = is_timeout
        self.retry_after_seconds: float | None = None


class TicketAnalysisModelResponseError(TicketAnalysisServiceError):
    """Raised when a model response does not match the API contract."""


class GeminiModelClient(Protocol):
    async def generate_content(
        self, *, model: str, contents: str, config: types.GenerateContentConfig
    ) -> Any:
        """Generate content with the async Gemini model client."""


class TicketAnalysisService(Protocol):
    async def analyze(
        self,
        ticket: TicketAnalysisRequest,
        memory_context: ConversationMemoryContext | None = None,
    ) -> TicketAnalysisResponse:
        """Analyze a support ticket without mutating external state."""


class MockTicketAnalysisService:
    async def analyze(
        self,
        ticket: TicketAnalysisRequest,
        memory_context: ConversationMemoryContext | None = None,
    ) -> TicketAnalysisResponse:
        text = f"{ticket.subject} {ticket.description}".lower()
        priority = self._priority(text)
        sentiment = self._sentiment(text)
        category = self._category(text)
        requires_escalation, escalation_reason = self._escalation(priority, sentiment)

        return TicketAnalysisResponse(
            ticket_id=ticket.ticket_id,
            summary=self._summary(ticket.description),
            category=category,
            priority=priority,
            sentiment=sentiment,
            requires_escalation=requires_escalation,
            escalation_reason=escalation_reason,
            suggested_response=self._suggested_response(category, priority),
            confidence=self._confidence(priority, sentiment),
        )

    def _priority(self, text: str) -> TicketPriority:
        if self._contains_any(text, ("outage", "down", "security", "breach")):
            return TicketPriority.URGENT
        if self._contains_any(text, ("blocked", "production", "cannot access")):
            return TicketPriority.HIGH
        if self._contains_any(text, ("slow", "error", "failed", "issue")):
            return TicketPriority.MEDIUM
        return TicketPriority.LOW

    def _sentiment(self, text: str) -> TicketSentiment:
        if self._contains_any(text, ("angry", "furious", "unacceptable")):
            return TicketSentiment.ANGRY
        if self._contains_any(text, ("frustrated", "annoyed", "upset")):
            return TicketSentiment.FRUSTRATED
        if self._contains_any(text, ("thanks", "great", "appreciate")):
            return TicketSentiment.POSITIVE
        return TicketSentiment.NEUTRAL

    def _category(self, text: str) -> str:
        if self._contains_any(text, ("billing", "invoice", "payment", "charge")):
            return "billing"
        if self._contains_any(text, ("login", "password", "access", "account")):
            return "account_access"
        if self._contains_any(text, ("bug", "error", "failed", "broken")):
            return "technical_support"
        if self._contains_any(text, ("how do i", "question", "help")):
            return "general_question"
        return "general_support"

    def _escalation(
        self, priority: TicketPriority, sentiment: TicketSentiment
    ) -> tuple[bool, str | None]:
        if priority == TicketPriority.URGENT:
            return True, "Urgent priority requires immediate escalation."
        if sentiment == TicketSentiment.ANGRY:
            return True, "Angry customer sentiment requires supervisor review."
        return False, None

    def _summary(self, description: str) -> str:
        normalized = " ".join(description.split())
        if len(normalized) <= 160:
            return normalized
        return f"{normalized[:157].rstrip()}..."

    def _suggested_response(self, category: str, priority: TicketPriority) -> str:
        if priority == TicketPriority.URGENT:
            return (
                "Acknowledge the impact, confirm immediate investigation, and "
                "share the next update window."
            )
        if category == "billing":
            return (
                "Acknowledge the billing concern and ask for the invoice or "
                "transaction reference needed to investigate."
            )
        if category == "account_access":
            return (
                "Acknowledge the access issue and guide the customer through "
                "secure account recovery steps."
            )
        return (
            "Acknowledge the request, summarize the issue, and provide the next "
            "support step."
        )

    def _confidence(
        self, priority: TicketPriority, sentiment: TicketSentiment
    ) -> float:
        if priority == TicketPriority.URGENT or sentiment == TicketSentiment.ANGRY:
            return 0.91
        if priority == TicketPriority.LOW and sentiment == TicketSentiment.NEUTRAL:
            return 0.72
        return 0.84

    def _contains_any(self, text: str, keywords: tuple[str, ...]) -> bool:
        return any(keyword in text for keyword in keywords)


class GeminiTicketAnalysisService:
    def __init__(
        self,
        *,
        project: str,
        location: str,
        model: str,
        timeout_seconds: float = 20.0,
        max_attempts: int = 3,
        model_client: GeminiModelClient | None = None,
        knowledge_retriever: KnowledgeRetriever | None = None,
        resilience_policy: ResiliencePolicy | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        random_source: Callable[[], float] | None = None,
    ) -> None:
        if not project:
            raise TicketAnalysisConfigurationError(
                "GOOGLE_CLOUD_PROJECT is required when TICKET_ANALYSIS_PROVIDER=gemini."
            )
        if not location:
            raise TicketAnalysisConfigurationError(
                "GOOGLE_CLOUD_LOCATION is required when "
                "TICKET_ANALYSIS_PROVIDER=gemini."
            )
        if not model:
            raise TicketAnalysisConfigurationError(
                "GEMINI_MODEL is required when TICKET_ANALYSIS_PROVIDER=gemini."
            )
        self._model = model
        self._resilience_policy = resilience_policy or ResiliencePolicy(
            timeout=TimeoutPolicy(timeout_seconds=timeout_seconds),
            retry=RetryPolicy(
                max_attempts=max_attempts,
                base_delay_seconds=0,
                max_delay_seconds=0,
                jitter_seconds=0,
            ),
            circuit_breaker=(
                CircuitBreakerConfig(
                    enabled=False,
                    failure_threshold=1,
                    recovery_timeout_seconds=1,
                    half_open_max_calls=1,
                )
            ),
        )
        self._circuit_breaker = circuit_breaker
        self._sleep = sleep
        self._random_source = random_source
        self._knowledge_retriever = knowledge_retriever
        self._model_client = (
            model_client
            or genai.Client(
                vertexai=True,
                project=project,
                location=location,
                http_options=types.HttpOptions(api_version="v1"),
            ).aio.models
        )

    async def analyze(
        self,
        ticket: TicketAnalysisRequest,
        memory_context: ConversationMemoryContext | None = None,
    ) -> TicketAnalysisResponse:
        started_at = time.perf_counter()
        attempt_count = 0
        outcome = "error"

        try:
            prompt, config = await self._build_generation_request(
                ticket,
                memory_context,
            )
            with tracer.start_as_current_span("provider.generate") as span:
                set_span_attributes(
                    span,
                    {
                        "ai.provider": "gemini",
                        "ai.model": self._model,
                    },
                )
                try:
                    response, attempt_count = await self._generate_with_retries(
                        prompt,
                        config,
                    )
                    result = self._parse_response(response)
                    outcome = "success"
                    return result
                except TicketAnalysisModelResponseError as exc:
                    outcome = "invalid_response"
                    attempt_count = max(attempt_count, 1)
                    record_span_exception(span, exc)
                    raise
                except TicketAnalysisProviderError as exc:
                    outcome = "timeout" if exc.is_timeout else "error"
                    attempt_count = max(
                        attempt_count,
                        self._resilience_policy.retry.max_attempts,
                    )
                    record_span_exception(span, exc)
                    raise
                except CircuitOpenError as exc:
                    outcome = "error"
                    provider_error = TicketAnalysisProviderError(
                        "Gemini circuit is open."
                    )
                    provider_error.retry_after_seconds = exc.retry_after_seconds
                    record_span_exception(span, provider_error)
                    raise provider_error from exc
                finally:
                    set_span_attributes(
                        span,
                        {
                            "ai.outcome": outcome,
                            "retry.attempt_count": attempt_count,
                            "resilience.component": "gemini",
                            "resilience.retry_count": max(0, attempt_count - 1),
                            "resilience.circuit_state": (
                                self.provider_health().state.value
                            ),
                            "resilience.failure_reason": (
                                outcome if outcome != "success" else None
                            ),
                        },
                    )
        finally:
            duration_seconds = time.perf_counter() - started_at
            duration_ms = round(duration_seconds * 1000, 2)
            record_provider_request(
                provider="gemini",
                model=self._model,
                outcome=outcome,
                duration_seconds=duration_seconds,
            )
            logger.info(
                "gemini_ticket_analysis_completed",
                extra={
                    "provider": "gemini",
                    "model": self._model,
                    "outcome": outcome,
                    "attempt_count": attempt_count,
                    "duration_ms": duration_ms,
                },
            )

    async def _build_generation_request(
        self,
        ticket: TicketAnalysisRequest,
        memory_context: ConversationMemoryContext | None,
    ) -> tuple[str, types.GenerateContentConfig]:
        retrieved_passages = None
        if self._knowledge_retriever is not None:
            retrieved_passages = await self._knowledge_retriever.retrieve(ticket)
        prompt = build_ticket_analysis_prompt(
            ticket,
            retrieved_passages,
            memory_context,
        )
        config = types.GenerateContentConfig(
            system_instruction=TICKET_ANALYSIS_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=TicketAnalysisResponse,
            temperature=0,
            max_output_tokens=1024,
        )
        return prompt, config

    async def _generate_with_retries(
        self,
        prompt: str,
        config: types.GenerateContentConfig,
    ) -> tuple[Any, int]:
        last_error: Exception | None = None
        try:
            return await run_with_resilience(
                lambda: self._model_client.generate_content(
                    model=self._model,
                    contents=prompt,
                    config=config,
                ),
                component="gemini",
                policy=self._resilience_policy,
                circuit_breaker=self._circuit_breaker,
                is_retryable=_is_retryable_gemini_error,
                sleep=self._sleep or asyncio.sleep,
                random_source=self._random_source or random.random,
            )
        except CircuitOpenError:
            raise
        except Exception as exc:
            last_error = exc
            logger.warning(
                "gemini_ticket_analysis_attempt_failed",
                extra={"outcome": failure_reason(exc)},
            )
            raise TicketAnalysisProviderError(
                "Gemini ticket analysis failed after retry attempts.",
                is_timeout=isinstance(exc, TimeoutError),
            ) from last_error

    def _parse_response(self, response: Any) -> TicketAnalysisResponse:
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, TicketAnalysisResponse):
            return parsed
        if parsed is not None:
            return self._validate_model_payload(parsed)

        text = getattr(response, "text", None)
        if not isinstance(text, str) or not text.strip():
            raise TicketAnalysisModelResponseError(
                "Gemini response did not include structured output."
            )

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise TicketAnalysisModelResponseError(
                "Gemini response was not valid JSON."
            ) from exc
        return self._validate_model_payload(payload)

    def _validate_model_payload(self, payload: Any) -> TicketAnalysisResponse:
        try:
            return TicketAnalysisResponse.model_validate(payload)
        except ValidationError as exc:
            raise TicketAnalysisModelResponseError(
                "Gemini response did not match the ticket analysis schema."
            ) from exc

    def provider_health(self) -> Any:
        if self._circuit_breaker is None:
            from app.core.resilience import CircuitBreakerSnapshot, CircuitState

            return CircuitBreakerSnapshot(
                state=CircuitState.CLOSED,
                consecutive_failure_count=0,
                seconds_until_next_probe=0.0,
            )
        return self._circuit_breaker.snapshot()


def _is_retryable_gemini_error(exc: BaseException) -> bool:
    if isinstance(
        exc,
        (
            TicketAnalysisModelResponseError,
            TicketAnalysisConfigurationError,
        ),
    ):
        return False
    return is_transient_exception(exc)
