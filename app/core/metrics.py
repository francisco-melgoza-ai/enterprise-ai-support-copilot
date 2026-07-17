from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)

METRICS_CONTENT_TYPE = CONTENT_TYPE_LATEST
REGISTRY = CollectorRegistry()

HTTP_REQUESTS = Counter(
    "support_copilot_http_requests_total",
    "Total HTTP requests handled by the API.",
    ("endpoint", "method", "status_code"),
    registry=REGISTRY,
)
HTTP_REQUEST_DURATION = Histogram(
    "support_copilot_http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ("endpoint", "method"),
    registry=REGISTRY,
)
TICKET_ANALYSIS_REQUESTS = Counter(
    "support_copilot_ticket_analysis_requests_total",
    "Ticket analysis requests received by the API.",
    registry=REGISTRY,
)
TICKET_ANALYSIS_SUCCESSES = Counter(
    "support_copilot_ticket_analysis_success_total",
    "Successful ticket analysis responses returned by the API.",
    registry=REGISTRY,
)
TICKET_ANALYSIS_FAILURES = Counter(
    "support_copilot_ticket_analysis_failure_total",
    "Failed ticket analysis attempts.",
    registry=REGISTRY,
)
PROVIDER_REQUESTS = Counter(
    "support_copilot_provider_requests_total",
    "AI provider requests by provider, model, and outcome.",
    ("provider", "model", "outcome"),
    registry=REGISTRY,
)
PROVIDER_FAILURES = Counter(
    "support_copilot_provider_failures_total",
    "AI provider failures by provider, model, and outcome.",
    ("provider", "model", "outcome"),
    registry=REGISTRY,
)
PROVIDER_REQUEST_DURATION = Histogram(
    "support_copilot_provider_request_duration_seconds",
    "AI provider request duration in seconds.",
    ("provider", "model", "outcome"),
    registry=REGISTRY,
)
RETRIEVAL_REQUESTS = Counter(
    "support_copilot_retrieval_requests_total",
    "Knowledge retrieval requests by provider and outcome.",
    ("provider", "outcome"),
    registry=REGISTRY,
)
RETRIEVAL_FAILURES = Counter(
    "support_copilot_retrieval_failures_total",
    "Knowledge retrieval failures by provider and outcome.",
    ("provider", "outcome"),
    registry=REGISTRY,
)
RETRIEVAL_DURATION = Histogram(
    "support_copilot_retrieval_duration_seconds",
    "Knowledge retrieval duration in seconds.",
    ("provider", "outcome"),
    registry=REGISTRY,
)
RETRIEVED_CHUNK_COUNT = Histogram(
    "support_copilot_retrieved_chunk_count",
    "Retrieved support passage count per retrieval request.",
    ("provider",),
    buckets=(0, 1, 2, 3, 5, 10, float("inf")),
    registry=REGISTRY,
)
ANALYSIS_ESCALATIONS = Counter(
    "support_copilot_analysis_escalations_total",
    "Ticket analyses that require escalation.",
    registry=REGISTRY,
)


def record_http_request(
    *,
    endpoint: str,
    method: str,
    status_code: int,
    duration_seconds: float,
) -> None:
    status = str(status_code)
    HTTP_REQUESTS.labels(endpoint=endpoint, method=method, status_code=status).inc()
    HTTP_REQUEST_DURATION.labels(endpoint=endpoint, method=method).observe(
        duration_seconds
    )


def record_ticket_analysis_request() -> None:
    TICKET_ANALYSIS_REQUESTS.inc()


def record_ticket_analysis_success(*, requires_escalation: bool) -> None:
    TICKET_ANALYSIS_SUCCESSES.inc()
    if requires_escalation:
        ANALYSIS_ESCALATIONS.inc()


def record_ticket_analysis_failure() -> None:
    TICKET_ANALYSIS_FAILURES.inc()


def record_provider_request(
    *,
    provider: str,
    model: str,
    outcome: str,
    duration_seconds: float,
) -> None:
    PROVIDER_REQUESTS.labels(provider=provider, model=model, outcome=outcome).inc()
    PROVIDER_REQUEST_DURATION.labels(
        provider=provider,
        model=model,
        outcome=outcome,
    ).observe(duration_seconds)
    if outcome != "success":
        PROVIDER_FAILURES.labels(
            provider=provider,
            model=model,
            outcome=outcome,
        ).inc()


def record_retrieval_request(
    *,
    provider: str,
    outcome: str,
    retrieved_chunk_count: int,
    duration_seconds: float,
) -> None:
    RETRIEVAL_REQUESTS.labels(provider=provider, outcome=outcome).inc()
    RETRIEVAL_DURATION.labels(provider=provider, outcome=outcome).observe(
        duration_seconds
    )
    RETRIEVED_CHUNK_COUNT.labels(provider=provider).observe(retrieved_chunk_count)
    if outcome not in {"success", "no_results"}:
        RETRIEVAL_FAILURES.labels(provider=provider, outcome=outcome).inc()


def render_metrics() -> bytes:
    return generate_latest(REGISTRY)
