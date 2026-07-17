import json
import logging
import time
from contextvars import ContextVar
from typing import Any
from uuid import uuid4

from fastapi import Request, Response
from opentelemetry import trace
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.metrics import record_http_request
from app.core.tracing import get_trace_log_fields, record_span_exception

REQUEST_ID_HEADER = "X-Request-ID"
request_id_context: ContextVar[str | None] = ContextVar(
    "request_id_context", default=None
)
_default_log_record_factory = logging.getLogRecordFactory()


def get_request_id() -> str | None:
    return request_id_context.get()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None) or get_request_id()
        if request_id is not None:
            payload["request_id"] = request_id
        trace_id = getattr(record, "trace_id", None)
        span_id = getattr(record, "span_id", None)
        if trace_id is not None:
            payload["trace_id"] = trace_id
        if span_id is not None:
            payload["span_id"] = span_id

        for key in (
            "method",
            "path",
            "status_code",
            "duration_ms",
            "provider",
            "model",
            "outcome",
            "attempt_count",
            "retrieved_chunk_count",
            "app_env",
            "cloud_region",
            "auth_provider",
            "roles",
            "authorization_outcome",
            "message_count",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, separators=(",", ":"))


def configure_logging() -> None:
    def record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = _default_log_record_factory(*args, **kwargs)
        record.request_id = get_request_id()
        trace_fields = get_trace_log_fields()
        record.trace_id = trace_fields.get("trace_id")
        record.span_id = trace_fields.get("span_id")
        return record

    logging.setLogRecordFactory(record_factory)

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        started_at = time.perf_counter()
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid4())
        token = request_id_context.set(request_id)
        response: Response | None = None

        try:
            current_span = trace.get_current_span()
            if current_span.is_recording():
                current_span.set_attribute("http.request_id", request_id)
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        except Exception as exc:
            record_span_exception(trace.get_current_span(), exc)
            raise
        finally:
            duration_seconds = time.perf_counter() - started_at
            duration_ms = round(duration_seconds * 1000, 2)
            status_code = response.status_code if response is not None else 500
            record_http_request(
                endpoint=_route_template(request),
                method=request.method,
                status_code=status_code,
                duration_seconds=duration_seconds,
            )
            logging.getLogger("app.request").info(
                "request_completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )
            request_id_context.reset(token)


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str):
        return path
    return "unmatched"
