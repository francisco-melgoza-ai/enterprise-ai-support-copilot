import os
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import Span, Status, StatusCode

DEFAULT_SERVICE_NAME = "enterprise-ai-support-copilot"
SUPPORTED_EXPORTERS = {"none", "console", "otlp", "memory"}

_configured_state: "TracingState | None" = None
_memory_exporter: InMemorySpanExporter | None = None
_instrumented_app_ids: set[int] = set()
_httpx_instrumented = False


@dataclass(frozen=True)
class TracingSettings:
    enabled: bool
    service_name: str = DEFAULT_SERVICE_NAME
    exporter: str = "none"
    otlp_endpoint: str | None = None

    @classmethod
    def from_env(cls) -> "TracingSettings":
        exporter = os.getenv("OTEL_EXPORTER", "none").strip().lower() or "none"
        return cls(
            enabled=_env_flag("OTEL_TRACING_ENABLED", default=False),
            service_name=os.getenv("OTEL_SERVICE_NAME", DEFAULT_SERVICE_NAME).strip()
            or DEFAULT_SERVICE_NAME,
            exporter=exporter,
            otlp_endpoint=_optional_env("OTEL_EXPORTER_OTLP_ENDPOINT"),
        )


@dataclass(frozen=True)
class TracingState:
    enabled: bool
    service_name: str
    exporter: str


def configure_tracing(
    app: FastAPI | None = None,
    settings: TracingSettings | None = None,
) -> TracingState:
    selected = settings or TracingSettings.from_env()
    exporter = selected.exporter.lower()
    if not selected.enabled or exporter == "none":
        return TracingState(
            enabled=False,
            service_name=selected.service_name,
            exporter="none",
        )
    if exporter not in SUPPORTED_EXPORTERS:
        raise ValueError(
            "Unsupported OTEL_EXPORTER. Expected 'none', 'console', 'otlp', "
            "or 'memory'."
        )

    state = _configure_provider(selected)
    _instrument_httpx()
    if app is not None:
        instrument_fastapi_app(app)
    return state


def instrument_fastapi_app(app: FastAPI) -> None:
    app_id = id(app)
    if app_id in _instrumented_app_ids:
        return
    FastAPIInstrumentor.instrument_app(app)
    _instrumented_app_ids.add(app_id)


def get_tracer(name: str) -> trace.Tracer:
    return trace.get_tracer(name)


def record_span_exception(span: Span, exc: BaseException) -> None:
    if not span.is_recording():
        return
    span.record_exception(exc)
    span.set_status(Status(StatusCode.ERROR, type(exc).__name__))


def set_span_attributes(span: Span, attributes: dict[str, Any]) -> None:
    if not span.is_recording():
        return
    for key, value in attributes.items():
        if value is not None:
            span.set_attribute(key, value)


def get_trace_log_fields() -> dict[str, str]:
    span = trace.get_current_span()
    context = span.get_span_context()
    if not context.is_valid:
        return {}
    return {
        "trace_id": f"{context.trace_id:032x}",
        "span_id": f"{context.span_id:016x}",
    }


def get_finished_spans() -> list[Any]:
    if _memory_exporter is None:
        return []
    return list(_memory_exporter.get_finished_spans())


def clear_finished_spans() -> None:
    if _memory_exporter is not None:
        _memory_exporter.clear()


def _configure_provider(settings: TracingSettings) -> TracingState:
    global _configured_state
    if _configured_state is not None:
        return _configured_state

    resource = Resource.create({SERVICE_NAME: settings.service_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(_span_processor(settings))
    trace.set_tracer_provider(provider)
    _configured_state = TracingState(
        enabled=True,
        service_name=settings.service_name,
        exporter=settings.exporter.lower(),
    )
    return _configured_state


def _span_processor(
    settings: TracingSettings,
) -> SimpleSpanProcessor | BatchSpanProcessor:
    exporter = _span_exporter(settings)
    if settings.exporter.lower() == "otlp":
        return BatchSpanProcessor(exporter)
    return SimpleSpanProcessor(exporter)


def _span_exporter(settings: TracingSettings) -> SpanExporter:
    global _memory_exporter
    exporter = settings.exporter.lower()
    if exporter == "console":
        return ConsoleSpanExporter()
    if exporter == "otlp":
        return OTLPSpanExporter(endpoint=settings.otlp_endpoint)
    if exporter == "memory":
        _memory_exporter = InMemorySpanExporter()
        return _memory_exporter
    raise ValueError("Tracing exporter must be configured before creating a provider.")


def _instrument_httpx() -> None:
    global _httpx_instrumented
    if _httpx_instrumented:
        return
    HTTPXClientInstrumentor().instrument()
    _httpx_instrumented = True


def _env_flag(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    return value.strip()
