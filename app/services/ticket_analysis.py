import asyncio
import json
import logging
from typing import Any, Protocol

from google import genai
from google.genai import types
from pydantic import ValidationError

from app.schemas.tickets import (
    TicketAnalysisRequest,
    TicketAnalysisResponse,
    TicketPriority,
    TicketSentiment,
)
from app.services.prompts import (
    TICKET_ANALYSIS_SYSTEM_PROMPT,
    build_ticket_analysis_prompt,
)

logger = logging.getLogger(__name__)


class TicketAnalysisServiceError(Exception):
    """Base class for safe ticket-analysis service failures."""


class TicketAnalysisConfigurationError(TicketAnalysisServiceError):
    """Raised when a provider is configured incorrectly."""


class TicketAnalysisProviderError(TicketAnalysisServiceError):
    """Raised when the configured provider cannot complete analysis."""


class TicketAnalysisModelResponseError(TicketAnalysisServiceError):
    """Raised when a model response does not match the API contract."""


class GeminiModelClient(Protocol):
    async def generate_content(
        self, *, model: str, contents: str, config: types.GenerateContentConfig
    ) -> Any:
        """Generate content with the async Gemini model client."""


class TicketAnalysisService(Protocol):
    async def analyze(self, ticket: TicketAnalysisRequest) -> TicketAnalysisResponse:
        """Analyze a support ticket without mutating external state."""


class MockTicketAnalysisService:
    async def analyze(self, ticket: TicketAnalysisRequest) -> TicketAnalysisResponse:
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
        if timeout_seconds <= 0:
            raise TicketAnalysisConfigurationError("Gemini timeout must be positive.")
        if max_attempts <= 0:
            raise TicketAnalysisConfigurationError(
                "Gemini retry attempts must be positive."
            )

        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._model_client = (
            model_client
            or genai.Client(
                vertexai=True,
                project=project,
                location=location,
                http_options=types.HttpOptions(api_version="v1"),
            ).aio.models
        )

    async def analyze(self, ticket: TicketAnalysisRequest) -> TicketAnalysisResponse:
        response = await self._generate_with_retries(ticket)
        return self._parse_response(response)

    async def _generate_with_retries(self, ticket: TicketAnalysisRequest) -> Any:
        prompt = build_ticket_analysis_prompt(ticket)
        config = types.GenerateContentConfig(
            system_instruction=TICKET_ANALYSIS_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=TicketAnalysisResponse,
            temperature=0,
            max_output_tokens=1024,
        )

        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                return await asyncio.wait_for(
                    self._model_client.generate_content(
                        model=self._model,
                        contents=prompt,
                        config=config,
                    ),
                    timeout=self._timeout_seconds,
                )
            except TimeoutError as exc:
                last_error = exc
                logger.warning(
                    "gemini_ticket_analysis_timeout",
                    extra={"ticket_id": ticket.ticket_id, "attempt": attempt},
                )
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "gemini_ticket_analysis_attempt_failed",
                    extra={"ticket_id": ticket.ticket_id, "attempt": attempt},
                )

        raise TicketAnalysisProviderError(
            "Gemini ticket analysis failed after retry attempts."
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
