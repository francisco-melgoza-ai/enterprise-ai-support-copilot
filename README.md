# Enterprise AI Support Copilot

[![CI](https://github.com/francisco-melgoza-ai/enterprise-ai-support-copilot/actions/workflows/ci.yml/badge.svg)](https://github.com/francisco-melgoza-ai/enterprise-ai-support-copilot/actions/workflows/ci.yml)

## Project Overview

Enterprise AI Support Copilot is a production-oriented customer support ticket
analysis API built with FastAPI, Gemini 2.5 Flash, Vertex AI, Vertex AI RAG
Engine (Serverless), Cloud Run, structured logging, request correlation, and a
deterministic local mock provider for development.

The service analyzes support tickets and returns a structured JSON response with
summary, category, priority, sentiment, escalation guidance, a suggested support
reply, and confidence. It supports local-only development with no cloud calls,
Gemini generation through Vertex AI, and managed knowledge grounding through
Vertex AI RAG Engine.

This module intentionally does not implement BigQuery analytics, Terraform,
CI/CD, authentication, agents, a frontend, or an automated knowledge ingestion
pipeline yet.

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
  -H "X-Request-ID: demo-request-001" \
  -d '{
    "ticket_id": "TICKET-123",
    "subject": "Payment failed",
    "description": "Invoice payment failed and the customer is frustrated.",
    "channel": "email"
  }'
```

Request fields:

- `ticket_id`: non-empty string
- `subject`: non-empty string, maximum 200 characters
- `description`: non-empty string, maximum 5000 characters
- `channel`: one of `web`, `email`, `chat`, or `phone`
- `customer_language`: optional, defaults to `en`

## Observability

The API emits structured JSON logs for request handling, startup configuration,
knowledge retrieval, and Gemini ticket-analysis operations.

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
retrieved text, generated model content, credentials, or PII. Use `request_id`
as the primary trace identifier.

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
- Evaluation framework for ticket analysis quality
- CI/CD pipeline
- Terraform infrastructure modules
- Knowledge ingestion pipeline
- Hybrid retrieval
- Monitoring dashboards
