# Enterprise AI Support Copilot

[![CI](https://github.com/francisco-melgoza-ai/enterprise-ai-support-copilot/actions/workflows/ci.yml/badge.svg)](https://github.com/francisco-melgoza-ai/enterprise-ai-support-copilot/actions/workflows/ci.yml)
[![CD](https://github.com/francisco-melgoza-ai/enterprise-ai-support-copilot/actions/workflows/cd.yml/badge.svg)](https://github.com/francisco-melgoza-ai/enterprise-ai-support-copilot/actions/workflows/cd.yml)

## Project Overview

Enterprise AI Support Copilot is a production-oriented customer support ticket
analysis API built with FastAPI, Gemini 2.5 Flash, Vertex AI, Vertex AI RAG
Engine (Serverless), Cloud Run, role-based API authorization, structured
logging, request correlation, and a deterministic local mock provider for
development.

The service analyzes support tickets and returns a structured JSON response with
summary, category, priority, sentiment, escalation guidance, a suggested support
reply, and confidence. It supports local-only development with no cloud calls,
Gemini generation through Vertex AI, and managed knowledge grounding through
Vertex AI RAG Engine.

This module intentionally does not implement BigQuery analytics, Terraform,
agents, a frontend, or an automated knowledge ingestion pipeline yet.

## Architecture

```text
API
↓
Service
↓
KnowledgeRetriever
↓
Vertex AI RAG Engine
↓
Gemini 2.5 Flash
↓
Structured JSON Response
```

- **API**: FastAPI routes expose `GET /health` and
  `POST /api/v1/tickets/analyze`. Routes handle HTTP concerns and delegate
  analysis work to the service layer.
- **Service**: `TicketAnalysisService` is an async interface. The mock and
  Gemini implementations share the same request and response contract.
- **KnowledgeRetriever**: Optional async retrieval boundary. It can be disabled,
  use local synthetic Markdown/text files, or call Vertex AI RAG Engine.
- **Vertex AI RAG Engine**: Managed retrieval provider for approved support
  knowledge from a configured RAG corpus.
- **Gemini 2.5 Flash**: Generates structured ticket analysis using the ticket
  and retrieved passages when managed retrieval is enabled.
- **Structured JSON Response**: Pydantic validates the model output before the
  API returns it.

Managed RAG retrieval preserves the existing `RetrievedPassage.relevance_score`
contract. Vertex RAG's returned score is treated as vector distance, so the
service normalizes it with `relevance_score = 1 / (1 + distance)` and sorts
managed passages by normalized relevance descending. Local retriever scores are
unchanged because they are already higher-is-better lexical relevance scores.

## Features

- Deterministic local mock provider
- Gemini provider through Vertex AI
- Vertex AI RAG Engine integration
- Managed knowledge retrieval from a configured corpus
- Structured JSON responses
- Pydantic request and response validation
- Async service boundaries
- FastAPI dependency injection
- Mock and Google OIDC authentication providers
- Role-based authorization for ticket analysis and metrics
- Request correlation with `X-Request-ID`
- Structured application logging
- Unit and integration tests
- Cloud Run deployment support

## Production Validation

The application successfully demonstrated this production flow:

```text
Cloud Run
→ Vertex AI RAG Engine
→ Gemini 2.5 Flash
→ HTTP 200 response
```

Validated components:

- Managed RAG corpus
- Managed retrieval
- Grounded Gemini generation
- Structured API response
- Correlated logging
- Cloud Run deployment

Observed validation facts:

- Knowledge provider: `vertex_rag`
- Retrieved chunk count: `3`
- Gemini completed successfully
- HTTP `200` returned
- Request correlation verified using `X-Request-ID`

Cloud Run tuning:

- Initial deployment at `512 MiB` exceeded memory limits.
- Increasing Cloud Run memory to `1 GiB` resolved the issue.

## Local Development

Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Run locally:

```bash
uvicorn app.main:app --reload
```

The API is available at `http://127.0.0.1:8000`.

### Mock Mode

Mock mode is deterministic, local-only, and does not call Google Cloud:

```bash
export TICKET_ANALYSIS_PROVIDER=mock
export KNOWLEDGE_PROVIDER=none
```

### Gemini Mode

Gemini mode uses Vertex AI with Application Default Credentials:

```bash
gcloud auth application-default login
export TICKET_ANALYSIS_PROVIDER=gemini
export KNOWLEDGE_PROVIDER=none
export GOOGLE_CLOUD_PROJECT="your-project-id"
export GOOGLE_CLOUD_LOCATION="us-central1"
export GEMINI_MODEL="gemini-2.5-flash"
```

### Vertex RAG Mode

Vertex RAG mode adds managed retrieval before Gemini generation:

```bash
export TICKET_ANALYSIS_PROVIDER=gemini
export KNOWLEDGE_PROVIDER=vertex_rag
export GOOGLE_CLOUD_PROJECT="your-project-id"
export GOOGLE_CLOUD_LOCATION="us-central1"
export GEMINI_MODEL="gemini-2.5-flash"
export RAG_CORPUS_RESOURCE_NAME="projects/your-project-id/locations/us-central1/ragCorpora/your-corpus-id"
export RAG_LOCATION="us-central1"
export RAG_TOP_K="3"
export RAG_DISTANCE_THRESHOLD="0.5"
```

Runtime environment variables:

- `APP_ENV`: optional, defaults to `local`.
- `PORT`: supplied by Cloud Run; the production command listens on this port.
- `TICKET_ANALYSIS_PROVIDER`: `mock` or `gemini`; defaults to `mock`.
- `KNOWLEDGE_PROVIDER`: `none`, `local`, or `vertex_rag`; defaults to `none`.
- `GOOGLE_CLOUD_PROJECT`: required for Gemini and Vertex RAG modes.
- `GOOGLE_CLOUD_LOCATION`: optional, defaults to `us-central1`.
- `GEMINI_MODEL`: optional, defaults to `gemini-2.5-flash`.
- `RAG_CORPUS_RESOURCE_NAME`: required when `KNOWLEDGE_PROVIDER=vertex_rag`.
- `RAG_LOCATION`: optional, should match the RAG corpus location.
- `RAG_TOP_K`: optional, defaults to `3`.
- `RAG_DISTANCE_THRESHOLD`: optional, defaults to `0.5`.
- `LOCAL_RETRIEVAL_MIN_SCORE`: optional, defaults to `0.22`; controls the
  minimum lexical relevance score for local retrieval.
- `AUTH_PROVIDER`: `mock` or `google`; defaults to `mock`.
- `AUTH_GOOGLE_AUDIENCE`: required when `AUTH_PROVIDER=google`; set this to the
  expected Google-issued OIDC token audience.
- `AUTH_MOCK_ALLOW_IN_PRODUCTION`: defaults to `false`; only set to `true` for
  tightly controlled break-glass testing because mock auth is not a production
  identity boundary.

Do not commit credentials, API keys, service account keys, or
project-specific secrets.

## API Examples

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Analyze a ticket:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/tickets/analyze \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer mock:agent-123:support_agent" \
  -H "X-Request-ID: demo-request-001" \
  -d '{
    "ticket_id": "TICKET-123",
    "subject": "Payment failed",
    "description": "Invoice payment failed and the customer is frustrated.",
    "channel": "email"
  }'
```

Read metrics as a manager:

```bash
curl http://127.0.0.1:8000/metrics \
  -H "Authorization: Bearer mock:manager-456:support_manager"
```

Request fields:

- `ticket_id`: non-empty string
- `subject`: non-empty string, maximum 200 characters
- `description`: non-empty string, maximum 5000 characters
- `channel`: one of `web`, `email`, `chat`, or `phone`
- `customer_language`: optional, defaults to `en`

## Authentication And Authorization

The API uses a provider abstraction that normalizes authenticated callers into a
principal with `subject`, optional `email`, roles, and provider name. The
supported roles are:

- `support_agent`
- `support_manager`
- `platform_admin`

Authorization rules:

- `POST /api/v1/tickets/analyze`: `support_agent`, `support_manager`, or
  `platform_admin`.
- `GET /metrics`: `support_manager` or `platform_admin`.
- `GET /health` and `GET /ready`: public.

Local mock authentication is deterministic and intended only for local
development and automated tests:

```text
Authorization: Bearer mock:<subject>:<role1,role2>
```

Examples:

```bash
mock:agent-123:support_agent
mock:manager-456:support_manager
mock:admin-789:platform_admin
```

Mock authentication is blocked when `APP_ENV=production` unless
`AUTH_MOCK_ALLOW_IN_PRODUCTION=true`. Enabling that override bypasses the
production identity boundary and should not be used for normal deployments.

Production Google mode validates Google-issued OIDC identity tokens with the
official Google authentication library. The verifier checks the token signature,
issuer, audience, expiration, and subject. The expected audience comes from
`AUTH_GOOGLE_AUDIENCE`; do not manually decode JWTs or trust unsigned claims.

Cloud Run invocation example with an identity token:

```bash
SERVICE_URL="https://YOUR-CLOUD-RUN-URL"
TOKEN="$(gcloud auth print-identity-token --audiences="${SERVICE_URL}")"

curl -X POST "${SERVICE_URL}/api/v1/tickets/analyze" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"ticket_id":"TICKET-123","subject":"Payment failed","description":"Invoice payment failed.","channel":"email"}'
```

Enterprise identity-provider migration path: keep the FastAPI authorization
dependencies and add another `AuthenticationProvider` implementation that
validates the enterprise IdP token, maps approved groups to the same normalized
roles, and preserves the same principal contract.

## Observability

The API emits structured JSON logs and Prometheus-compatible metrics for
request handling, authentication, authorization, startup configuration,
knowledge retrieval, and Gemini ticket-analysis operations. Operational
targets, SLI definitions, and Google Cloud Monitoring setup instructions are
documented in [docs/operations.md](docs/operations.md).

Every request receives a correlation ID:

- If the caller sends `X-Request-ID`, the API preserves it.
- If the caller does not send `X-Request-ID`, the API generates a UUID.
- The response always includes `X-Request-ID`.
- Application logs produced during the request include `request_id`.

Safe request log example:

```json
{
  "level": "INFO",
  "logger": "app.request",
  "message": "request_completed",
  "request_id": "b5f0f1de-9f9b-4d37-9f58-6c5b273ff6d9",
  "method": "POST",
  "path": "/api/v1/tickets/analyze",
  "status_code": 200,
  "duration_ms": 12.4
}
```

Safe managed retrieval telemetry example:

```json
{
  "level": "INFO",
  "logger": "app.services.knowledge",
  "message": "knowledge_retrieval_completed",
  "request_id": "b5f0f1de-9f9b-4d37-9f58-6c5b273ff6d9",
  "provider": "vertex_rag",
  "retrieved_chunk_count": 3,
  "outcome": "success",
  "duration_ms": 86.7
}
```

Safe Gemini telemetry example:

```json
{
  "level": "INFO",
  "logger": "app.services.ticket_analysis",
  "message": "gemini_ticket_analysis_completed",
  "request_id": "b5f0f1de-9f9b-4d37-9f58-6c5b273ff6d9",
  "provider": "gemini",
  "model": "gemini-2.5-flash",
  "outcome": "success",
  "attempt_count": 1,
  "duration_ms": 842.3
}
```

Logs must not include raw ticket IDs, ticket subjects, ticket descriptions,
bearer tokens, raw JWTs, authorization headers, full identity claims, retrieved
text, generated model content, credentials, or PII. Use `request_id` as the
primary trace identifier.

Runtime observability endpoints:

- `GET /health`: liveness endpoint used by uptime checks and Cloud Run health
  verification.
- `GET /ready`: lightweight readiness endpoint that validates configured
  provider names without calling Gemini, Vertex AI, or Vertex AI RAG Engine.
- `GET /metrics`: Prometheus-compatible application metrics. Requires
  `support_manager` or `platform_admin`.

Local verification:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
curl http://localhost:8000/metrics \
  -H "Authorization: Bearer mock:manager-456:support_manager"
```

Metrics use the `support_copilot_` prefix and avoid high-cardinality or
sensitive labels. They do not include request IDs, ticket IDs, ticket text,
prompts, retrieved document content, generated responses, credentials, or PII.

### Distributed Tracing

OpenTelemetry tracing is available but disabled by default for local
development and tests. When enabled, a ticket-analysis request can be followed
across the HTTP request, FastAPI endpoint, knowledge retrieval, Gemini provider
call, and API response.

Tracing environment variables:

- `OTEL_TRACING_ENABLED`: set to `true` to enable tracing; defaults to disabled.
- `OTEL_SERVICE_NAME`: optional, defaults to `enterprise-ai-support-copilot`.
- `OTEL_EXPORTER`: `none`, `console`, or `otlp`; defaults to `none`.
- `OTEL_EXPORTER_OTLP_ENDPOINT`: required when exporting to an OTLP collector
  unless the collector uses the SDK default endpoint.

Console exporter example:

```bash
export OTEL_TRACING_ENABLED=true
export OTEL_EXPORTER=console
uvicorn app.main:app --reload
```

OTLP exporter example:

```bash
export OTEL_TRACING_ENABLED=true
export OTEL_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318/v1/traces"
uvicorn app.main:app --reload
```

Trace, log, and request-ID correlation:

- `X-Request-ID` remains the primary support correlation identifier.
- When tracing is enabled and a real span is active, structured logs include
  `trace_id` and `span_id`.
- The active HTTP span receives `http.request_id` as a safe attribute.

Tracing safe-data policy:

- Do not add ticket text, subjects, descriptions, prompts, generated responses,
  retrieved document content, credentials, raw ticket IDs, or PII to spans.
- Span attributes are limited to low-cardinality operational fields such as
  provider, model, outcome, retry count, category, priority, escalation flag,
  and retrieved chunk count.

Initial portfolio/demo SLOs:

- Availability: `99.5%` successful requests over 30 days.
- Latency: `95%` of `/api/v1/tickets/analyze` requests complete within
  45 seconds.
- Server-side error rate: less than `1%` over 30 days.
- Health checks: `99.9%` successful `/health` responses.

These targets should be adjusted using real production traffic.

### Resilience

Gemini ticket analysis and managed Vertex RAG retrieval use explicit
resilience policies:

```text
timeout
→ retry with exponential backoff and bounded jitter
→ circuit breaker
→ automatic half-open recovery
```

Gemini failures still return the existing safe `503` API error after retries
are exhausted or when the Gemini circuit is open. The public response schema is
unchanged and provider internals are not exposed.

Managed Vertex RAG is protected independently from Gemini. When Vertex RAG
times out, has a transient failure, or its circuit is open, and
`RAG_GRACEFUL_DEGRADATION_ENABLED=true`, analysis continues without retrieved
passages using the existing no-knowledge prompt path. Local retrieval behavior
is unchanged.

Local resilience configuration example:

```bash
export GEMINI_TIMEOUT_SECONDS=20
export GEMINI_MAX_ATTEMPTS=3
export GEMINI_RETRY_BASE_DELAY_SECONDS=0.25
export GEMINI_RETRY_MAX_DELAY_SECONDS=4
export GEMINI_RETRY_JITTER_SECONDS=0.25
export GEMINI_CIRCUIT_BREAKER_ENABLED=true
export GEMINI_CIRCUIT_FAILURE_THRESHOLD=5
export GEMINI_CIRCUIT_RECOVERY_SECONDS=30
export GEMINI_CIRCUIT_HALF_OPEN_MAX_CALLS=1

export RAG_TIMEOUT_SECONDS=10
export RAG_MAX_ATTEMPTS=2
export RAG_RETRY_BASE_DELAY_SECONDS=0.2
export RAG_RETRY_MAX_DELAY_SECONDS=2
export RAG_RETRY_JITTER_SECONDS=0.2
export RAG_CIRCUIT_BREAKER_ENABLED=true
export RAG_CIRCUIT_FAILURE_THRESHOLD=5
export RAG_CIRCUIT_RECOVERY_SECONDS=30
export RAG_CIRCUIT_HALF_OPEN_MAX_CALLS=1
export RAG_GRACEFUL_DEGRADATION_ENABLED=true
```

Production defaults are conservative: Gemini gets up to three attempts, Vertex
RAG gets up to two attempts, both circuits open after five transient failures,
and both automatically probe recovery after 30 seconds. Avoid aggressive retry
settings during provider incidents because retries can amplify load and delay
customer responses.

## Deployment

The project is prepared for Cloud Run source deployment with Google Cloud
Buildpacks. A custom Dockerfile is not required for the current Python/FastAPI
runtime.

The production process command is defined in `Procfile`:

```bash
uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8080}"
```

Enable Vertex AI:

```bash
gcloud services enable aiplatform.googleapis.com \
  --project "$GOOGLE_CLOUD_PROJECT"
```

Deploy mock mode:

```bash
gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --project "$GOOGLE_CLOUD_PROJECT" \
  --region "$REGION" \
  --allow-unauthenticated \
  --memory "1Gi" \
  --set-env-vars "TICKET_ANALYSIS_PROVIDER=mock,KNOWLEDGE_PROVIDER=none"
```

Deploy Gemini with Vertex RAG:

```bash
gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --project "$GOOGLE_CLOUD_PROJECT" \
  --region "$REGION" \
  --allow-unauthenticated \
  --memory "1Gi" \
  --set-env-vars "TICKET_ANALYSIS_PROVIDER=gemini,KNOWLEDGE_PROVIDER=vertex_rag,GOOGLE_CLOUD_PROJECT=$GOOGLE_CLOUD_PROJECT,GOOGLE_CLOUD_LOCATION=$REGION,GEMINI_MODEL=gemini-2.5-flash,RAG_CORPUS_RESOURCE_NAME=projects/$GOOGLE_CLOUD_PROJECT/locations/$REGION/ragCorpora/YOUR_CORPUS_ID,RAG_LOCATION=$REGION"
```

Cloud Run uses the managed service account and Application Default Credentials
for Vertex AI and RAG Engine access. Grant the runtime service account only the
IAM permissions it needs, such as Vertex AI access to the configured project or
resource scope. Do not deploy API keys or credential JSON files.

Verify the health endpoint:

```bash
SERVICE_URL="$(gcloud run services describe "$SERVICE_NAME" \
  --project "$GOOGLE_CLOUD_PROJECT" \
  --region "$REGION" \
  --format 'value(status.url)')"

curl "$SERVICE_URL/health"
```

## Vertex AI RAG Engine Operations

Create or reuse a managed RAG corpus and import files from Cloud Storage:

```bash
python scripts/provision_rag_corpus.py \
  --project "$GOOGLE_CLOUD_PROJECT" \
  --location "us-central1" \
  --display-name "support-copilot-knowledge" \
  --gcs-uri "gs://YOUR_BUCKET/support-knowledge/*"
```

The script prints the full corpus resource name. Store that value in
`RAG_CORPUS_RESOURCE_NAME`.

Verify retrieval without calling Gemini:

```bash
python scripts/verify_rag_retrieval.py \
  --corpus-resource-name "$RAG_CORPUS_RESOURCE_NAME" \
  --query "Customer cannot reset MFA"
```

The verification script prints `normalized_relevance_score`, not raw Vertex RAG
distance. Empty retrieval prints `No relevant passages found.` and exits
successfully.

## Evaluation Framework

The repository includes a local, repeatable evaluation framework for synthetic
support cases. It measures retrieval quality, structured-output reliability,
grounding behavior, latency, and ticket-analysis quality without requiring
Google Cloud by default.

Dataset:

```text
evaluation/data/support_cases.jsonl
```

Default local evaluation uses the deterministic mock analysis provider and local
retrieval:

```bash
python scripts/run_evaluation.py \
  --provider mock \
  --knowledge-provider local \
  --output evaluation/results/local.json \
  --report evaluation/results/local.md
```

The evaluator writes:

- JSON results with run configuration, aggregate metrics, thresholds, failed
  cases, per-case results, provider/model information, and timestamp.
- Markdown summary report with aggregate metrics, failed cases, and per-case
  latency.

Deterministic metrics include:

- Category accuracy
- Priority accuracy
- Escalation accuracy
- JSON/schema validity rate
- Retrieval hit rate
- Expected-source top-1 accuracy
- No-result correctness
- Mean latency
- P95 latency
- Prohibited-claim pass rate

Groundedness checks are deterministic by default. They flag prohibited claims,
check no-knowledge cases for invented procedural steps, and verify expected
retrieved sources when applicable.

Per-case evaluation output also includes safe retrieval diagnostics:

- `top_score`
- `retrieved_count`
- `expected_no_result`
- `actual_no_result`

The diagnostics do not include full ticket text or document content.

Optional live Gemini and Vertex RAG evaluation:

```bash
python scripts/run_evaluation.py \
  --provider gemini \
  --knowledge-provider vertex_rag \
  --output evaluation/results/live-vertex-rag.json \
  --report evaluation/results/live-vertex-rag.md
```

Optional Gemini-as-judge scoring is available behind `--gemini-judge`. Judge
results are model-based, non-deterministic, disabled by default, and should be
reviewed separately from deterministic metrics.

Threshold-gated local run:

```bash
python scripts/run_evaluation.py \
  --provider mock \
  --knowledge-provider local \
  --fail-on-threshold \
  --min-schema-validity 1.0 \
  --min-prohibited-claim-pass-rate 1.0
```

Generated evaluation reports under `evaluation/results/` are ignored by Git.

## Continuous Integration

GitHub Actions runs the CI workflow on pull requests targeting `main`, pushes
to `main`, and manual dispatches.

CI quality gates:

- `ruff format --check .`
- `ruff check .`
- `mypy app`
- `pytest`
- Deterministic local evaluation with `mock` analysis and `local` retrieval

The CI evaluation is cloud-independent. It does not authenticate to Google
Cloud, does not use Gemini, and does not call Vertex AI or Vertex AI RAG Engine.
It runs:

```bash
python scripts/run_evaluation.py \
  --provider mock \
  --knowledge-provider local \
  --dataset evaluation/data/support_cases.jsonl \
  --output evaluation/results/ci \
  --fail-on-threshold
```

The workflow uploads the generated evaluation JSON and Markdown report as the
`evaluation-results` artifact, including when threshold evaluation fails.

## Continuous Deployment

GitHub Actions CD is defined separately from CI in
`.github/workflows/cd.yml`. It deploys the production Cloud Run service from
source when changes are pushed to `main`, and it can also be started manually
from the GitHub Actions **CD** workflow with **Run workflow**.

The CD workflow uses GitHub OpenID Connect and Google Cloud Workload Identity
Federation. GitHub does not store a service account JSON key. Instead, GitHub
issues a short-lived OIDC token for the workflow run, Google Cloud verifies the
token through a Workload Identity Provider restricted to this repository, and
the workflow impersonates a deployment service account.

Deployment flow:

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
gcloud run deploy --source .
↓
Cloud Run
↓
/health verification
```

Repository variables required by CD:

- `GCP_PROJECT_ID`: Google Cloud project that hosts Cloud Run.
- `GCP_REGION`: Cloud Run region, for example `us-central1`.
- `WORKLOAD_IDENTITY_PROVIDER`: full Workload Identity Provider resource name.
- `DEPLOY_SERVICE_ACCOUNT`: deployment service account email.
- `CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT`: runtime service account email used by
  the deployed Cloud Run service.
- `CLOUD_RUN_SERVICE`: must be `enterprise-ai-support-copilot`.
- `TICKET_ANALYSIS_PROVIDER`: production analysis provider, typically
  `gemini`.
- `KNOWLEDGE_PROVIDER`: production knowledge provider, typically `vertex_rag`.
- `GOOGLE_CLOUD_PROJECT`: project used by the application for Vertex AI.
- `GOOGLE_CLOUD_LOCATION`: Vertex AI location, for example `us-central1`.
- `GEMINI_MODEL`: model name, for example `gemini-2.5-flash`.
- `RAG_CORPUS_RESOURCE_NAME`: managed RAG corpus resource name.
- `RAG_LOCATION`: RAG corpus location.
- `AUTH_PROVIDER`: production authentication provider; CD requires `google`.
- `AUTH_GOOGLE_AUDIENCE`: expected audience for Google-issued identity tokens,
  usually the Cloud Run service URL.
- `AUTH_MOCK_ALLOW_IN_PRODUCTION`: deployed as `false` by CD.

The workflow validates these variables before deployment and fails if any are
blank. Production CD fails unless `AUTH_PROVIDER=google` and
`AUTH_GOOGLE_AUDIENCE` is set. The workflow uses `--update-env-vars` so
existing Cloud Run environment variables outside this list are preserved.

No GitHub secrets are required for authentication. Use repository secrets only
for future application environment values that truly must remain private. Do
not store service account keys, downloaded credential files, API keys, or
long-lived Google Cloud credentials in GitHub.

After deployment, the workflow captures the Cloud Run URL with
`gcloud run services describe`, then calls `/health` up to 12 times with a
short delay between attempts. The deployment fails unless `/health` returns
HTTP `200`. The health step prints the URL, status codes, and a small response
body excerpt for diagnostics without exposing credentials or application
secrets.

### One-Time Workload Identity Federation Setup

Run these commands from an administrator workstation with permission to create
service accounts, configure IAM, and create Workload Identity Federation
resources. Do not run them from the CD workflow.

Set project-specific values:

```bash
export PROJECT_ID="your-project-id"
export REGION="us-central1"
export REPO="francisco-melgoza-ai/enterprise-ai-support-copilot"
export POOL_ID="github-actions"
export PROVIDER_ID="github"
export DEPLOY_SA_ID="support-copilot-deployer"
export RUNTIME_SA_ID="support-copilot-runtime"

export PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" \
  --format 'value(projectNumber)')"
export DEPLOY_SA_EMAIL="${DEPLOY_SA_ID}@${PROJECT_ID}.iam.gserviceaccount.com"
export RUNTIME_SA_EMAIL="${RUNTIME_SA_ID}@${PROJECT_ID}.iam.gserviceaccount.com"
```

Enable required APIs:

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  aiplatform.googleapis.com \
  --project "$PROJECT_ID"
```

Create the deployment and runtime service accounts:

```bash
gcloud iam service-accounts create "$DEPLOY_SA_ID" \
  --project "$PROJECT_ID" \
  --display-name "Support Copilot GitHub CD deployer"

gcloud iam service-accounts create "$RUNTIME_SA_ID" \
  --project "$PROJECT_ID" \
  --display-name "Support Copilot Cloud Run runtime"
```

Create the Workload Identity Pool and GitHub OIDC provider:

```bash
gcloud iam workload-identity-pools create "$POOL_ID" \
  --project "$PROJECT_ID" \
  --location "global" \
  --display-name "GitHub Actions"

gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_ID" \
  --project "$PROJECT_ID" \
  --location "global" \
  --workload-identity-pool "$POOL_ID" \
  --display-name "GitHub Actions provider" \
  --issuer-uri "https://token.actions.githubusercontent.com" \
  --attribute-mapping "google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner,attribute.ref=assertion.ref" \
  --attribute-condition "assertion.repository=='${REPO}'"
```

Allow only this repository to impersonate the deployment service account:

```bash
export PRINCIPAL_SET="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/attribute.repository/${REPO}"

gcloud iam service-accounts add-iam-policy-binding "$DEPLOY_SA_EMAIL" \
  --project "$PROJECT_ID" \
  --role "roles/iam.workloadIdentityUser" \
  --member "$PRINCIPAL_SET"
```

Grant deployment permissions:

```bash
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member "serviceAccount:${DEPLOY_SA_EMAIL}" \
  --role "roles/run.admin"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member "serviceAccount:${DEPLOY_SA_EMAIL}" \
  --role "roles/cloudbuild.builds.editor"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member "serviceAccount:${DEPLOY_SA_EMAIL}" \
  --role "roles/artifactregistry.writer"

gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SA_EMAIL" \
  --project "$PROJECT_ID" \
  --member "serviceAccount:${DEPLOY_SA_EMAIL}" \
  --role "roles/iam.serviceAccountUser"
```

Grant runtime permissions for Gemini and managed RAG retrieval:

```bash
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member "serviceAccount:${RUNTIME_SA_EMAIL}" \
  --role "roles/aiplatform.user"
```

If your organization requires the Cloud Build service account to perform
additional source-deployment actions, grant only the minimum permissions needed
for your project policy. Common source deployment requirements include
permission to write build artifacts and to act as the Cloud Run runtime service
account:

```bash
export CLOUDBUILD_SA="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member "serviceAccount:${CLOUDBUILD_SA}" \
  --role "roles/artifactregistry.writer"

gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SA_EMAIL" \
  --project "$PROJECT_ID" \
  --member "serviceAccount:${CLOUDBUILD_SA}" \
  --role "roles/iam.serviceAccountUser"
```

Set these GitHub repository variables after the provider is created:

```text
GCP_PROJECT_ID=your-project-id
GCP_REGION=us-central1
WORKLOAD_IDENTITY_PROVIDER=projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/github-actions/providers/github
DEPLOY_SERVICE_ACCOUNT=support-copilot-deployer@your-project-id.iam.gserviceaccount.com
CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT=support-copilot-runtime@your-project-id.iam.gserviceaccount.com
CLOUD_RUN_SERVICE=enterprise-ai-support-copilot
TICKET_ANALYSIS_PROVIDER=gemini
KNOWLEDGE_PROVIDER=vertex_rag
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=us-central1
GEMINI_MODEL=gemini-2.5-flash
RAG_CORPUS_RESOURCE_NAME=projects/your-project-id/locations/us-central1/ragCorpora/YOUR_CORPUS_ID
RAG_LOCATION=us-central1
```

## Testing

Run the local quality gate:

```bash
ruff format --check .
ruff check .
mypy app
pytest
```

The test suite includes unit tests for providers, retrieval, settings, and
Gemini service behavior, plus integration tests for the FastAPI endpoints.
Managed Google Cloud calls are mocked in automated tests.

## Roadmap

- BigQuery conversation analytics
- Evaluation framework enhancements
- Progressive deployment approvals and rollback strategy
- Terraform infrastructure modules
- Knowledge ingestion pipeline
- Hybrid retrieval
- Monitoring dashboards
