# Operations Guide

## Service Objectives

These are initial portfolio/demo targets. They should be adjusted after the
service has enough real production traffic to establish realistic baselines.

| Objective | Initial target |
| --- | ---: |
| Availability SLO | 99.5% successful requests over 30 days |
| Latency SLO | 95% of `/api/v1/tickets/analyze` requests complete within 45 seconds |
| Error-rate objective | Less than 1% server-side failures over 30 days |
| Health-check objective | 99.9% successful `/health` responses |

## Service-Level Indicators

### Availability

Numerator: count of Cloud Run HTTP requests with response code class `2xx`,
`3xx`, or `4xx`.

Denominator: count of all Cloud Run HTTP requests.

4xx responses are included as successful service availability because the
service was reachable and returned a client-error response. 5xx responses are
counted as unavailable.

### Request Latency

Numerator: count of `/api/v1/tickets/analyze` requests completed within
45 seconds.

Denominator: count of all `/api/v1/tickets/analyze` requests.

Track p95 latency using Cloud Run request latency and the application metric
`support_copilot_http_request_duration_seconds` when Prometheus collection is
enabled.

### Provider Failure Rate

Numerator: Gemini provider requests with outcome `timeout`, `invalid_response`,
or `error`.

Denominator: all Gemini provider requests.

Application metric:

```text
support_copilot_provider_failures_total / support_copilot_provider_requests_total
```

### Retrieval Failure Rate

Numerator: knowledge retrieval requests with outcome `timeout` or `error`.

Denominator: all knowledge retrieval requests, including `success` and
`no_results`.

Application metric:

```text
support_copilot_retrieval_failures_total / support_copilot_retrieval_requests_total
```

### Health-Check Availability

Numerator: successful `/health` uptime checks returning HTTP `200`.

Denominator: all `/health` uptime checks.

## Runtime Endpoints

- `/health`: minimal liveness endpoint for Cloud Run and external uptime checks.
- `/ready`: lightweight application readiness check. It validates configured
  provider names and does not call Gemini, Vertex AI, or Vertex AI RAG Engine.
- `/metrics`: Prometheus-compatible application metrics. Metrics intentionally
  exclude ticket text, prompts, generated responses, retrieved content,
  credentials, and request IDs.

Local verification:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
curl http://localhost:8000/metrics
```

## Distributed Tracing

OpenTelemetry tracing is available for following one ticket-analysis request
across HTTP handling, FastAPI routing, knowledge retrieval, Gemini generation,
and response serialization.

Tracing is disabled by default so local development, CI, and tests do not
export spans unless explicitly configured.

### Environment Variables

| Variable | Purpose | Default |
| --- | --- | --- |
| `OTEL_TRACING_ENABLED` | Enables tracing when set to `true`, `1`, `yes`, or `on`. | disabled |
| `OTEL_SERVICE_NAME` | Service name attached to traces. | `enterprise-ai-support-copilot` |
| `OTEL_EXPORTER` | Exporter mode: `none`, `console`, or `otlp`. | `none` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP HTTP traces endpoint, such as `http://collector:4318/v1/traces`. | SDK default |

Local console tracing:

```bash
export OTEL_TRACING_ENABLED=true
export OTEL_EXPORTER=console
uvicorn app.main:app --reload
```

OTLP tracing:

```bash
export OTEL_TRACING_ENABLED=true
export OTEL_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_ENDPOINT="http://otel-collector:4318/v1/traces"
uvicorn app.main:app --reload
```

### Production Recommendation

For Cloud Run, prefer exporting OTLP traces to a managed or self-hosted
OpenTelemetry Collector, then route traces to Cloud Trace or another approved
backend. This keeps the application vendor-neutral and avoids service account
JSON keys.

Add the following Cloud Run environment variables when production tracing is
ready:

```text
OTEL_TRACING_ENABLED=true
OTEL_SERVICE_NAME=enterprise-ai-support-copilot
OTEL_EXPORTER=otlp
OTEL_EXPORTER_OTLP_ENDPOINT=https://YOUR_COLLECTOR_ENDPOINT/v1/traces
```

The current CD workflow does not set these variables. Add them only after an
OTLP collector or approved tracing backend is available.

### Sampling Guidance

This application does not implement advanced tail sampling yet.

Initial guidance:

- Capture 100% of errors where the backend or collector supports it.
- Sample a low percentage of successful production traffic to control cost and
  noise.
- Temporarily increase successful-traffic sampling during incident
  investigation.
- Keep local tracing disabled unless actively debugging.

### Safe-Data Policy

Never attach these values to spans:

- ticket text
- ticket subject or description
- prompt contents
- generated response content
- retrieved document contents
- credentials
- raw ticket IDs
- PII

Allowed span attributes are low-cardinality operational values such as
provider, model, outcome, retry attempt count, category, priority, escalation
flag, and retrieved chunk count.

### Troubleshooting

- No spans locally: confirm `OTEL_TRACING_ENABLED=true` and
  `OTEL_EXPORTER=console` or `OTEL_EXPORTER=otlp`.
- No OTLP export: verify `OTEL_EXPORTER_OTLP_ENDPOINT` includes the traces path,
  commonly `/v1/traces` for OTLP HTTP.
- Missing log correlation: confirm tracing is enabled and the log was emitted
  while a real span was active. Logs outside spans continue to omit `trace_id`
  and `span_id`.
- Duplicate spans in development: restart the reload process after changing
  tracing configuration.
- Sensitive data concern: inspect span attributes and events; only operational
  metadata should be present.

## Resilience Operations

Gemini ticket analysis and managed Vertex RAG retrieval each have an independent
timeout, retry policy, and circuit breaker. Vertex RAG can also degrade
gracefully when retrieval is temporarily unavailable.

### Environment Variables

| Variable | Default | Notes |
| --- | ---: | --- |
| `GEMINI_TIMEOUT_SECONDS` | `20` | Per-attempt timeout. Must be greater than zero. |
| `GEMINI_MAX_ATTEMPTS` | `3` | Total attempts including the first call. Must be at least 1. |
| `GEMINI_RETRY_BASE_DELAY_SECONDS` | `0.25` | Initial exponential backoff delay. |
| `GEMINI_RETRY_MAX_DELAY_SECONDS` | `4` | Maximum exponential backoff delay. Must be at least base delay. |
| `GEMINI_RETRY_JITTER_SECONDS` | `0.25` | Bounded random jitter added to retry delay. |
| `GEMINI_CIRCUIT_BREAKER_ENABLED` | `true` | Set `false` only for temporary troubleshooting. |
| `GEMINI_CIRCUIT_FAILURE_THRESHOLD` | `5` | Transient failures before opening the circuit. |
| `GEMINI_CIRCUIT_RECOVERY_SECONDS` | `30` | Time before the open circuit transitions to half-open. |
| `GEMINI_CIRCUIT_HALF_OPEN_MAX_CALLS` | `1` | Concurrent probe calls allowed while half-open. |
| `RAG_TIMEOUT_SECONDS` | `10` | Per-attempt Vertex RAG timeout. |
| `RAG_MAX_ATTEMPTS` | `2` | Total Vertex RAG attempts including the first call. |
| `RAG_RETRY_BASE_DELAY_SECONDS` | `0.2` | Initial RAG retry delay. |
| `RAG_RETRY_MAX_DELAY_SECONDS` | `2` | Maximum RAG retry delay. |
| `RAG_RETRY_JITTER_SECONDS` | `0.2` | Bounded RAG retry jitter. |
| `RAG_CIRCUIT_BREAKER_ENABLED` | `true` | Protects Vertex RAG independently from Gemini. |
| `RAG_CIRCUIT_FAILURE_THRESHOLD` | `5` | Transient RAG failures before opening the circuit. |
| `RAG_CIRCUIT_RECOVERY_SECONDS` | `30` | Time before RAG half-open probes. |
| `RAG_CIRCUIT_HALF_OPEN_MAX_CALLS` | `1` | Concurrent RAG half-open probe calls. |
| `RAG_GRACEFUL_DEGRADATION_ENABLED` | `true` | Allows Gemini analysis to continue without retrieved passages for transient RAG failures. |

Invalid values fail fast at startup or dependency resolution. Examples include
zero timeouts, attempts below 1, negative delays, max delay below base delay,
failure thresholds below 1, and half-open probe limits below 1.

### Circuit States

- `closed`: requests flow normally. Successful calls reset consecutive failure
  count.
- `open`: calls fail fast without invoking the provider. Logs include
  `circuit_request_rejected`, and metrics increment
  `support_copilot_circuit_rejections_total`.
- `half_open`: after the recovery timeout, a limited number of probe calls are
  allowed. Successful probes close the circuit. Failed probes reopen it.

### Retryable Failures

Retryable:

- timeout
- HTTP `408`
- HTTP `429`
- HTTP `500`
- HTTP `502`
- HTTP `503`
- HTTP `504`
- temporary transport failures such as connection errors

Not retryable:

- invalid Gemini structured output
- schema validation failure
- authentication failure
- authorization failure
- malformed request
- deterministic configuration errors
- Vertex RAG response mapping defects
- programmer errors

### Identifying Open Circuits

Use logs and metrics:

- Log events: `circuit_opened`, `circuit_half_opened`, `circuit_closed`,
  `circuit_request_rejected`.
- Metrics:
  - `support_copilot_circuit_state{component,state}`
  - `support_copilot_circuit_rejections_total{component}`

Trace attributes include:

- `resilience.component`
- `resilience.retry_count`
- `resilience.circuit_state`
- `resilience.failure_reason`

### Identifying Degraded RAG Requests

When Vertex RAG degrades, the app logs `knowledge_retrieval_degraded`, sets
`resilience.degraded=true` on the retrieval span, increments
`support_copilot_degraded_operations_total{component="vertex_rag",reason=...}`,
and continues Gemini analysis without retrieved passages.

### Safe Tuning

- Increase timeouts only when provider latency is expected and user-facing
  latency remains acceptable.
- Prefer small retry counts with jitter to avoid synchronized retry bursts.
- Avoid aggressive retries during provider incidents; they can amplify load.
- Raise circuit thresholds only after observing normal transient failure rates.
- To temporarily disable a circuit breaker, set
  `GEMINI_CIRCUIT_BREAKER_ENABLED=false` or
  `RAG_CIRCUIT_BREAKER_ENABLED=false`, then restore protection after
  investigation.

## Google Cloud Monitoring Setup

The following commands are one-time setup examples. Review them for your
project and run them from an administrator workstation. Do not run these from
the application or CD workflow.

Set common values:

```bash
export PROJECT_ID="your-project-id"
export REGION="us-central1"
export SERVICE_NAME="enterprise-ai-support-copilot"
export SERVICE_URL="$(gcloud run services describe "$SERVICE_NAME" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --format 'value(status.url)')"
export SERVICE_HOST="${SERVICE_URL#https://}"
export NOTIFICATION_CHANNEL="projects/${PROJECT_ID}/notificationChannels/CHANNEL_ID"
```

Enable Cloud Monitoring API if needed:

```bash
gcloud services enable monitoring.googleapis.com \
  --project "$PROJECT_ID"
```

### Notification Channel Placeholder

Create a notification channel in the Google Cloud console:

1. Go to **Monitoring** → **Alerting** → **Edit notification channels**.
2. Add an email, Pub/Sub, Slack, PagerDuty, or webhook channel.
3. Copy the created resource name, such as
   `projects/PROJECT_ID/notificationChannels/CHANNEL_ID`.
4. Store it in `NOTIFICATION_CHANNEL` for the alert policy commands.

### Uptime Check For `/health`

```bash
gcloud monitoring uptime create "Support Copilot health" \
  --project "$PROJECT_ID" \
  --resource-type "uptime-url" \
  --resource-labels "host=${SERVICE_HOST},project_id=${PROJECT_ID}" \
  --path "/health" \
  --protocol "HTTPS" \
  --request-method "GET" \
  --status-codes "200" \
  --period "60s" \
  --timeout "10s"
```

### Alert For Cloud Run 5xx Responses

Create `monitoring-cloud-run-5xx.json`:

```json
{
  "displayName": "Support Copilot Cloud Run 5xx responses",
  "combiner": "OR",
  "enabled": true,
  "notificationChannels": ["NOTIFICATION_CHANNEL_PLACEHOLDER"],
  "conditions": [
    {
      "displayName": "5xx response rate",
      "conditionThreshold": {
        "filter": "resource.type=\"cloud_run_revision\" AND resource.label.service_name=\"enterprise-ai-support-copilot\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.label.response_code_class=\"5xx\"",
        "aggregations": [
          {
            "alignmentPeriod": "300s",
            "perSeriesAligner": "ALIGN_RATE",
            "crossSeriesReducer": "REDUCE_SUM",
            "groupByFields": ["resource.label.service_name"]
          }
        ],
        "comparison": "COMPARISON_GT",
        "thresholdValue": 0.01,
        "duration": "300s",
        "trigger": {"count": 1}
      }
    }
  ]
}
```

Create the policy:

```bash
sed "s|NOTIFICATION_CHANNEL_PLACEHOLDER|${NOTIFICATION_CHANNEL}|g" \
  monitoring-cloud-run-5xx.json > /tmp/monitoring-cloud-run-5xx.json

gcloud monitoring policies create \
  --project "$PROJECT_ID" \
  --policy-from-file "/tmp/monitoring-cloud-run-5xx.json"
```

### Alert For High p95 Request Latency

Create `monitoring-cloud-run-p95-latency.json`:

```json
{
  "displayName": "Support Copilot high p95 request latency",
  "combiner": "OR",
  "enabled": true,
  "notificationChannels": ["NOTIFICATION_CHANNEL_PLACEHOLDER"],
  "conditions": [
    {
      "displayName": "p95 request latency above 45 seconds",
      "conditionThreshold": {
        "filter": "resource.type=\"cloud_run_revision\" AND resource.label.service_name=\"enterprise-ai-support-copilot\" AND metric.type=\"run.googleapis.com/request_latencies\"",
        "aggregations": [
          {
            "alignmentPeriod": "300s",
            "perSeriesAligner": "ALIGN_PERCENTILE_95",
            "crossSeriesReducer": "REDUCE_MEAN",
            "groupByFields": ["resource.label.service_name"]
          }
        ],
        "comparison": "COMPARISON_GT",
        "thresholdValue": 45000,
        "duration": "300s",
        "trigger": {"count": 1}
      }
    }
  ]
}
```

Create the policy:

```bash
sed "s|NOTIFICATION_CHANNEL_PLACEHOLDER|${NOTIFICATION_CHANNEL}|g" \
  monitoring-cloud-run-p95-latency.json > /tmp/monitoring-cloud-run-p95-latency.json

gcloud monitoring policies create \
  --project "$PROJECT_ID" \
  --policy-from-file "/tmp/monitoring-cloud-run-p95-latency.json"
```

Cloud Run request latency is reported in milliseconds. The 45-second threshold
is therefore `45000`.

### Alert For Failed Cloud Run Revisions

Create a logs-based alert policy for revision readiness failures. Create
`monitoring-cloud-run-revision-failure.json`:

```json
{
  "displayName": "Support Copilot failed Cloud Run revision",
  "combiner": "OR",
  "enabled": true,
  "notificationChannels": ["NOTIFICATION_CHANNEL_PLACEHOLDER"],
  "conditions": [
    {
      "displayName": "Cloud Run revision readiness failure",
      "conditionMatchedLog": {
        "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"enterprise-ai-support-copilot\" AND severity>=ERROR AND (textPayload:\"Ready condition status changed to False\" OR jsonPayload.message:\"Ready condition status changed to False\")"
      }
    }
  ],
  "alertStrategy": {
    "notificationRateLimit": {"period": "300s"},
    "autoClose": "1800s"
  }
}
```

Create the policy:

```bash
sed "s|NOTIFICATION_CHANNEL_PLACEHOLDER|${NOTIFICATION_CHANNEL}|g" \
  monitoring-cloud-run-revision-failure.json > /tmp/monitoring-cloud-run-revision-failure.json

gcloud monitoring policies create \
  --project "$PROJECT_ID" \
  --policy-from-file "/tmp/monitoring-cloud-run-revision-failure.json"
```

Validate the exact log filter against your project's Cloud Run revision logs
before enabling paging notifications, because log payload fields can vary by
revision failure mode.

## Dashboard Recommendations

Create a Cloud Monitoring dashboard with:

- Cloud Run request count by response code class.
- Cloud Run 5xx rate.
- Cloud Run p50, p95, and p99 request latency.
- Cloud Run instance count and memory utilization.
- Cloud Run revision and deployment events.
- Log-based panels filtered by `request_id`.
- Application Prometheus metrics when collection is configured:
  - `support_copilot_ticket_analysis_requests_total`
  - `support_copilot_provider_failures_total`
  - `support_copilot_retrieval_failures_total`
  - `support_copilot_analysis_escalations_total`

## Prometheus Metrics On Cloud Run

The application exposes Prometheus-compatible metrics at `/metrics`, but Cloud
Run does not automatically ingest arbitrary application metrics from that
endpoint into Cloud Monitoring.

To collect these metrics in Google Cloud, add one of the following explicitly:

- Managed Service for Prometheus with a supported collector path.
- A sidecar or separate scraper that can reach the Cloud Run service and write
  to Cloud Monitoring.
- A future OpenTelemetry Collector or custom metrics exporter.

Until that collection path is configured, Cloud Monitoring dashboards and
alerts should rely on built-in Cloud Run metrics and structured logs. The
`/metrics` endpoint remains useful for local verification and future managed
Prometheus collection.
