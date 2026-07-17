# Enterprise AI Support Copilot Architecture

## System Architecture

```text
Cloud Run
↓
FastAPI
↓
Dependency Injection
↓
TicketAnalysisService
↓
KnowledgeRetriever
↓
Vertex AI RAG Engine
↓
Gemini
↓
Structured Response
```

### Cloud Run

Cloud Run hosts the FastAPI application as a production HTTP service. The app
listens on the `PORT` environment variable supplied by Cloud Run and uses the
runtime service account for Google Cloud access.

### FastAPI

FastAPI exposes:

- `GET /health`
- `GET /ready`
- `GET /metrics`
- `POST /api/v1/tickets/analyze`

Routes handle HTTP concerns, request validation, response serialization, and
error translation. They do not contain ticket-analysis business logic.

### Dependency Injection

FastAPI dependency injection selects the configured analysis and knowledge
providers from environment variables:

- `TICKET_ANALYSIS_PROVIDER=mock`
- `TICKET_ANALYSIS_PROVIDER=gemini`
- `KNOWLEDGE_PROVIDER=none`
- `KNOWLEDGE_PROVIDER=local`
- `KNOWLEDGE_PROVIDER=vertex_rag`

Unsupported provider values fail clearly during dependency resolution.

### TicketAnalysisService

`TicketAnalysisService` is an async protocol for ticket analysis. Current
implementations are:

- `MockTicketAnalysisService`: deterministic local provider for development and
  tests.
- `GeminiTicketAnalysisService`: Vertex AI Gemini provider with structured
  output validation, timeout handling, retry handling, and safe service-level
  exceptions.

The service layer does not depend on FastAPI.

### KnowledgeRetriever

`KnowledgeRetriever` is an async protocol for retrieving approved support
knowledge. Current implementations are:

- `LocalKnowledgeRetriever`: loads synthetic Markdown and text files from
  `sample_data/knowledge/`, chunks them deterministically, and ranks chunks with
  lexical overlap. It applies stop-word filtering, requires meaningful token
  overlap, and filters weak matches with `LOCAL_RETRIEVAL_MIN_SCORE`.
- `VertexRagKnowledgeRetriever`: retrieves managed passages from a configured
  Vertex AI RAG Engine corpus.

The managed retriever maps SDK contexts into the shared `RetrievedPassage`
schema. Vertex RAG's returned score is treated as vector distance and converted
to higher-is-better relevance with `1 / (1 + distance)`.

### Vertex AI RAG Engine

Vertex AI RAG Engine provides managed retrieval from a configured corpus. The
application does not expose upload endpoints and does not create cloud resources
at request time. Corpus provisioning and import are handled by the
`scripts/provision_rag_corpus.py` operational helper.

### Gemini

Gemini 2.5 Flash receives the ticket and, when configured, retrieved support
passages. The prompt separates application instructions from retrieved content
and instructs the model not to invent unsupported policy or procedure claims.

### Structured Response

Gemini output is validated with Pydantic before being returned by the API. The
public response contract includes:

- `ticket_id`
- `summary`
- `category`
- `priority`
- `sentiment`
- `requires_escalation`
- `escalation_reason`
- `suggested_response`
- `confidence`

## Request Flow

1. A client sends `POST /api/v1/tickets/analyze`.
2. Request middleware accepts or generates `X-Request-ID`.
3. FastAPI validates the request body with Pydantic.
4. Dependency injection resolves the configured `TicketAnalysisService`.
5. In mock mode, the mock service returns deterministic analysis.
6. In Gemini mode, the service optionally calls the configured
   `KnowledgeRetriever`.
7. With `KNOWLEDGE_PROVIDER=vertex_rag`, the retriever calls Vertex AI RAG
   Engine and maps contexts into retrieved passages.
8. Retrieved passages are inserted into the Gemini prompt as untrusted support
   knowledge.
9. Gemini 2.5 Flash returns structured output.
10. Pydantic validates the model output.
11. The API returns the structured JSON response with `X-Request-ID`.

## Production Architecture

```text
Client
↓
Cloud Run
↓
FastAPI application
↓
Vertex AI RAG Engine
↓
Gemini 2.5 Flash on Vertex AI
↓
Cloud Logging
```

Production components:

- **Cloud Run**: hosts the FastAPI API and supplies the `PORT` runtime
  environment variable.
- **Vertex AI**: provides Gemini model access through Application Default
  Credentials and IAM.
- **RAG Engine**: provides managed retrieval from the configured corpus.
- **Cloud Storage**: used as a source for corpus file import through the
  provisioning script; it is not accessed by the API request path directly.
- **Cloud Logging**: receives structured application, request, retrieval, and
  Gemini telemetry logs from Cloud Run.

Production validation demonstrated:

```text
Cloud Run
→ Vertex AI RAG Engine
→ Gemini 2.5 Flash
→ HTTP 200 response
```

Observed validation facts:

- Knowledge provider: `vertex_rag`
- Retrieved chunk count: `3`
- Gemini completed successfully
- HTTP `200` returned
- Request correlation verified using `X-Request-ID`
- Cloud Run memory increased from `512 MiB` to `1 GiB` to resolve memory limits

## Continuous Deployment Architecture

```text
GitHub push to main
↓
GitHub Actions CD
↓
GitHub OIDC token
↓
Google Workload Identity Federation
↓
deployment service account
↓
Cloud Run
↓
health verification
```

The CD workflow is intentionally separate from CI. CI validates code quality,
tests, and deterministic local evaluation. CD deploys only after a push to
`main` or an explicit manual dispatch.

### GitHub Actions CD

The CD workflow runs from `.github/workflows/cd.yml`. It checks out the
repository, validates that required repository variables are present, exchanges
a GitHub OIDC token for Google Cloud access through Workload Identity
Federation, deploys from source with `gcloud run deploy`, captures the Cloud
Run service URL, and verifies `GET /health`.

### GitHub OIDC Token

GitHub issues a short-lived OIDC token to the workflow because the workflow has
`id-token: write`. The token identifies the repository and workflow context. No
service account JSON key, API key, downloaded credential file, or long-lived
Google Cloud secret is used.

### Workload Identity Federation

Google Cloud Workload Identity Federation validates the GitHub token through a
provider whose attribute condition is restricted to:

```text
francisco-melgoza-ai/enterprise-ai-support-copilot
```

The principal set for that repository receives
`roles/iam.workloadIdentityUser` on the deployment service account, allowing
GitHub Actions to impersonate that account only through the configured provider.

### Deployment Service Account

The deployment service account performs the source deployment. It requires
permissions to administer Cloud Run, create Cloud Build builds for source
deployment, write build artifacts, and act as the Cloud Run runtime service
account.

### Cloud Run Runtime Service Account

The runtime service account is attached to the deployed Cloud Run service. It
is the identity used by the application for Vertex AI Gemini and Vertex AI RAG
Engine access through Application Default Credentials.

### Health Verification

After deployment, the workflow resolves the Cloud Run URL and calls `/health`
with retries to allow for transient startup delay. The deployment fails unless
the endpoint returns HTTP `200`.

## Observability

The application uses structured JSON logging and request correlation.

```text
Client
↓
Cloud Run
↓
FastAPI middleware and service instrumentation
↓
Structured logs + Prometheus metrics
↓
OpenTelemetry traces
↓
Cloud Logging / Cloud Monitoring
↓
Dashboards, SLOs, and alerts
```

### X-Request-ID

- Incoming `X-Request-ID` is preserved when present.
- A UUID is generated when the header is absent.
- The response includes `X-Request-ID`.
- Application logs include `request_id` for logs emitted during the request.

### Request Lifecycle Logs

Request logs include method, path, status code, duration, and `request_id`.
They do not include ticket subject, description, raw ticket ID, or PII.

### Knowledge Retrieval Telemetry

Retrieval telemetry includes:

- `provider`
- `retrieved_chunk_count`
- `duration_ms`
- `outcome`
- `request_id`

It does not log query text, retrieved text, source paths, credentials, ticket
content, or generated content.

### Gemini Telemetry

Gemini telemetry includes:

- `provider`
- `model`
- `outcome`
- `attempt_count`
- `duration_ms`
- `request_id`

Outcomes include `success`, `timeout`, `invalid_response`, and `error`.

### Cloud Run Logs

Cloud Run captures application logs in Cloud Logging. A single request can be
traced across request lifecycle, retrieval telemetry, and Gemini telemetry by
filtering on `request_id`.

### Prometheus Metrics

The application exposes Prometheus-compatible metrics at `/metrics` with the
`support_copilot_` prefix. Metrics include HTTP request counts and duration,
ticket-analysis request/success/failure counts, Gemini provider request counts,
provider failures, provider duration, retrieval counts, retrieval failures,
retrieval duration, retrieved chunk counts, and escalation counts.

Metric labels are intentionally low-cardinality:

- HTTP metrics: endpoint route template, method, status code.
- Provider metrics: provider, model, outcome.
- Retrieval metrics: provider, outcome.

Metrics do not use request IDs, ticket IDs, ticket content, prompts, retrieved
document content, generated responses, credentials, or PII as labels or values.

Cloud Run does not automatically ingest arbitrary application `/metrics`
endpoints into Cloud Monitoring. Built-in Cloud Run metrics and structured logs
are immediately available. Application Prometheus metrics require an explicit
collection path such as Managed Service for Prometheus, a scraper, or a future
OpenTelemetry Collector.

### Health And Readiness

- `/health` is the liveness endpoint for Cloud Run health verification and
  external uptime checks.
- `/ready` is a lightweight readiness endpoint that validates configured
  provider names. It does not call Gemini, Vertex AI, or Vertex AI RAG Engine.

Operational SLOs, SLIs, alert policy examples, and dashboard recommendations
are documented in [operations.md](operations.md).

### Distributed Tracing

```text
Client
↓
Cloud Run
↓
FastAPI instrumentation
↓
ticket.analysis span
├── knowledge.retrieve span
└── provider.generate span
↓
OpenTelemetry exporter
↓
Cloud Trace or OTLP backend
```

OpenTelemetry tracing is environment-controlled and disabled by default. When
enabled, FastAPI instrumentation creates HTTP request spans and the application
adds custom spans for ticket analysis, retrieval, and Gemini generation.

Custom spans use safe, low-cardinality attributes:

- `ticket.analysis`: category, priority, escalation flag.
- `knowledge.retrieve`: provider, outcome, retrieved chunk count.
- `provider.generate`: provider, model, outcome, retry attempt count.

The active HTTP span receives `http.request_id` for request correlation.
Structured logs include `trace_id` and `span_id` when a real span is active,
while preserving the existing `request_id` field.

Tracing does not attach ticket text, subject, description, raw ticket ID,
prompts, generated content, retrieved document content, credentials, or PII.

## Security

- Uses Application Default Credentials for Vertex AI and RAG Engine access.
- Uses IAM service accounts in Cloud Run.
- Does not use API keys for Gemini or Vertex RAG.
- Does not store credential JSON files in the repository.
- Does not log ticket subject, ticket description, raw ticket ID, retrieved
  content, generated model content, credentials, or PII.
- Follows least-privilege IAM guidance for runtime and provisioning identities.

## Testing

Testing coverage includes:

- Unit tests for the deterministic mock service.
- Unit tests for Gemini service success, invalid responses, timeouts, retries,
  and safe telemetry.
- Unit tests for local retrieval chunking and ranking.
- Unit tests for Vertex RAG response mapping, no-result handling, relevance
  normalization, and provider selection.
- Integration tests for `GET /health`.
- Integration tests for `POST /api/v1/tickets/analyze`.
- Mock providers and fake adapters so automated tests do not require Google
  Cloud access.
- Live validation of Cloud Run, managed RAG retrieval, Gemini generation,
  structured response, and correlated logging.

Run the local validation suite:

```bash
ruff format --check .
ruff check .
mypy app
pytest
```

## Evaluation Framework

The evaluation framework is separate from the production API. It runs from
`scripts/run_evaluation.py` and uses synthetic cases in
`evaluation/data/support_cases.jsonl`.

Default mode is cloud-independent:

```text
MockTicketAnalysisService
↓
LocalKnowledgeRetriever
↓
Deterministic metrics and reports
```

Live evaluation is explicit and opt-in:

```text
GeminiTicketAnalysisService
↓
VertexRagKnowledgeRetriever
↓
Vertex AI RAG Engine
↓
Gemini 2.5 Flash
↓
Evaluation metrics and reports
```

The evaluator measures:

- Category accuracy
- Priority accuracy
- Escalation accuracy
- JSON/schema validity rate
- Retrieval hit rate
- Expected-source top-1 accuracy
- No-result correctness
- Mean and p95 latency
- Prohibited-claim pass rate

Grounding checks do not require an evaluator model by default. They detect
prohibited claims in `suggested_response`, check that no-knowledge cases do not
invent procedural steps, and verify expected retrieved sources.

Per-case output includes safe retrieval diagnostics: top score, retrieved count,
whether no result was expected, and whether no result was returned. It does not
include full ticket text or document content.

Optional Gemini-as-judge evaluation is disabled by default. When enabled, it is
clearly labeled as model-based and non-deterministic. It uses a separate
evaluation prompt and does not reuse the production ticket-analysis prompt.

Generated evaluation outputs are written as JSON and Markdown under
`evaluation/results/`, which is ignored by Git.

## Out Of Scope

The current implementation does not include:

- BigQuery conversation analytics
- Authentication or authorization
- Terraform
- Frontend UI
- Agent workflows
- Automated production knowledge ingestion pipeline
