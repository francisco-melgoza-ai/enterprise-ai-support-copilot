# Enterprise AI Support Copilot

## Project Overview

FastAPI API for customer-support ticket analysis with a local deterministic mock
provider, an optional Gemini on Vertex AI provider, and an optional local
or managed Vertex AI RAG Engine retrieval layer for approved support knowledge.

This milestone intentionally does not include Vertex AI Search, custom Vector
Search indexes, Document AI, upload APIs, BigQuery, Terraform, application
authentication, agents, or frontend work.

## Architecture

The Sprint 1 API follows a small layered shape:

```text
API -> Service -> Schemas -> Core
```

- API routes handle HTTP concerns only.
- Pydantic schemas define request and response contracts.
- `TicketAnalysisService` defines the analysis interface.
- `MockTicketAnalysisService` provides deterministic local analysis.
- `GeminiTicketAnalysisService` provides the Vertex AI implementation behind the
  same async service interface.
- `KnowledgeRetriever` defines the retrieval interface.
- `LocalKnowledgeRetriever` loads synthetic approved support documents from
  `sample_data/knowledge/`, chunks them deterministically, and ranks them with
  lexical relevance.
- `VertexRagKnowledgeRetriever` retrieves managed passages from a configured
  Vertex AI RAG Engine corpus and maps them into the same retrieval schema.
- FastAPI dependency injection wires routes to the service.
- Core logging emits structured request metadata and never logs ticket subject,
  description, or PII.

## Local Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Provider Modes

The API defaults to local mock mode:

```bash
export TICKET_ANALYSIS_PROVIDER=mock
```

Mock mode is deterministic, does not call external services, and is used by
tests and local development.

Retrieval is disabled by default:

```bash
export KNOWLEDGE_PROVIDER=none
```

Enable local approved-knowledge retrieval for Gemini mode:

```bash
export KNOWLEDGE_PROVIDER=local
```

The local retriever reads Markdown and text files from `sample_data/knowledge/`.
It does not call a vector database, Vertex AI Search, Cloud Storage, BigQuery,
or any other managed retrieval service.

Enable managed Vertex AI RAG Engine retrieval for Gemini mode:

```bash
export KNOWLEDGE_PROVIDER=vertex_rag
export RAG_CORPUS_RESOURCE_NAME="projects/your-project-id/locations/us-central1/ragCorpora/your-corpus-id"
export RAG_LOCATION="us-central1"
export RAG_TOP_K="3"
export RAG_DISTANCE_THRESHOLD="0.5"
```

The corpus resource name format is:

```text
projects/{project}/locations/{location}/ragCorpora/{corpus_id}
```

The managed retriever uses Application Default Credentials and IAM. It does not
use API keys or credential JSON files.

To use Gemini through Vertex AI, authenticate with Application Default
Credentials and set the provider configuration:

```bash
gcloud auth application-default login
export TICKET_ANALYSIS_PROVIDER=gemini
export KNOWLEDGE_PROVIDER=vertex_rag
export GOOGLE_CLOUD_PROJECT="your-project-id"
export GOOGLE_CLOUD_LOCATION="us-central1"
export GEMINI_MODEL="gemini-2.5-flash"
export RAG_CORPUS_RESOURCE_NAME="projects/your-project-id/locations/us-central1/ragCorpora/your-corpus-id"
export RAG_LOCATION="us-central1"
```

The service uses Vertex AI authentication through ADC. Do not set or store API
keys for this project.

## Run Instructions

```bash
uvicorn app.main:app --reload
```

The API will be available at `http://127.0.0.1:8000`.

The production process command is defined in `Procfile` for Cloud Run source
deployments:

```bash
uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8080}"
```

## Endpoints

- `GET /health`
- `POST /api/v1/tickets/analyze`

`GET /health` returns `200` with `{"status":"ok"}` and does not depend on
Gemini, credentials, databases, or external services, so it is suitable for
Cloud Run health checks.

## API Examples

```bash
curl http://127.0.0.1:8000/health
```

```bash
curl -X POST http://127.0.0.1:8000/api/v1/tickets/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "ticket_id": "TICKET-123",
    "subject": "Payment failed",
    "description": "Invoice payment failed and the customer is frustrated.",
    "channel": "email"
  }'
```

## Ticket Analysis Request

```json
{
  "ticket_id": "TICKET-123",
  "subject": "Payment failed",
  "description": "Invoice payment failed and the customer is frustrated.",
  "channel": "email",
  "customer_language": "en"
}
```

`channel` must be one of `web`, `email`, `chat`, or `phone`.
`customer_language` is optional and defaults to `en`.

## Testing Instructions

```bash
ruff format --check .
ruff check .
mypy app
pytest
```

## Observability

The API emits structured JSON logs for request handling, startup configuration,
and Gemini ticket-analysis operations.

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

Safe startup log example:

```json
{
  "level": "INFO",
  "logger": "app.main",
  "message": "application_startup",
  "app_env": "production",
  "provider": "gemini",
  "model": "gemini-2.5-flash",
  "cloud_region": "us-central1"
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

Gemini telemetry outcomes are `success`, `timeout`, `invalid_response`, and
`error`. Use `request_id` as the primary trace identifier. Logs must not include
raw ticket IDs, ticket subjects, ticket descriptions, generated model content,
credentials, or PII.

Safe retrieval telemetry example:

```json
{
  "level": "INFO",
  "logger": "app.services.knowledge",
  "message": "knowledge_retrieval_completed",
  "request_id": "b5f0f1de-9f9b-4d37-9f58-6c5b273ff6d9",
  "provider": "local",
  "retrieved_chunk_count": 2,
  "outcome": "success",
  "duration_ms": 3.1
}
```

Retrieval logs must not include retrieved text, ticket content, generated model
content, credentials, or sensitive filenames.

Safe managed RAG telemetry example:

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

## Cloud Run Deployment

This project is prepared for Cloud Run source deployment with Google Cloud
Buildpacks. A custom Dockerfile is not required for the current Python/FastAPI
runtime.

Set your deployment variables locally:

```bash
export SERVICE_NAME="enterprise-ai-support-copilot"
export REGION="us-central1"
export GOOGLE_CLOUD_PROJECT="your-project-id"
```

Deploy in local mock mode:

```bash
gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --project "$GOOGLE_CLOUD_PROJECT" \
  --region "$REGION" \
  --allow-unauthenticated \
  --set-env-vars "TICKET_ANALYSIS_PROVIDER=mock"
```

Deploy with Gemini through Vertex AI:

```bash
gcloud services enable aiplatform.googleapis.com \
  --project "$GOOGLE_CLOUD_PROJECT"

gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --project "$GOOGLE_CLOUD_PROJECT" \
  --region "$REGION" \
  --allow-unauthenticated \
  --set-env-vars "TICKET_ANALYSIS_PROVIDER=gemini,KNOWLEDGE_PROVIDER=vertex_rag,GOOGLE_CLOUD_PROJECT=$GOOGLE_CLOUD_PROJECT,GOOGLE_CLOUD_LOCATION=$REGION,GEMINI_MODEL=gemini-2.5-flash,RAG_CORPUS_RESOURCE_NAME=projects/$GOOGLE_CLOUD_PROJECT/locations/$REGION/ragCorpora/YOUR_CORPUS_ID,RAG_LOCATION=$REGION"
```

After deployment, verify the health endpoint:

```bash
SERVICE_URL="$(gcloud run services describe "$SERVICE_NAME" \
  --project "$GOOGLE_CLOUD_PROJECT" \
  --region "$REGION" \
  --format 'value(status.url)')"

curl "$SERVICE_URL/health"
```

### Runtime Environment Variables

- `PORT`: supplied by Cloud Run; the app startup command listens on this port.
- `TICKET_ANALYSIS_PROVIDER`: optional, defaults to `mock`; valid values are
  `mock` and `gemini`.
- `KNOWLEDGE_PROVIDER`: optional, defaults to `none`; valid values are `none`
  `local`, and `vertex_rag`.
- `GOOGLE_CLOUD_PROJECT`: required only when `TICKET_ANALYSIS_PROVIDER=gemini`.
- `GOOGLE_CLOUD_LOCATION`: optional, defaults to `us-central1`; should match the
  Vertex AI region.
- `GEMINI_MODEL`: optional, defaults to `gemini-2.5-flash`.
- `RAG_CORPUS_RESOURCE_NAME`: required when `KNOWLEDGE_PROVIDER=vertex_rag`.
  Format: `projects/{project}/locations/{location}/ragCorpora/{corpus_id}`.
- `RAG_LOCATION`: optional, defaults to the Google Cloud location; should match
  the RAG corpus location.
- `RAG_TOP_K`: optional, defaults to `3`.
- `RAG_DISTANCE_THRESHOLD`: optional, defaults to `0.5`.

Do not commit credentials, API keys, service account keys, or project-specific
secrets. In Cloud Run, Gemini and Vertex RAG providers use Application Default
Credentials from the service runtime environment.

## Vertex AI RAG Engine Operations

Install dependencies and authenticate locally with ADC:

```bash
pip install -e ".[dev]"
gcloud auth application-default login
```

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

Least-privilege IAM for the runtime service account:

- `roles/aiplatform.user` on the project or a narrower resource scope that can
  retrieve from the configured corpus.

For provisioning imports from Cloud Storage, the identity running
`scripts/provision_rag_corpus.py` also needs read access to the source objects,
for example `roles/storage.objectViewer` on the import bucket.

## Roadmap

- Add persistence and analytics after the local API contract is stable.
- Expand managed retrieval operations after the RAG corpus workflow is proven.
- Add authentication and deployment infrastructure in later platform modules.
- Add knowledge search and agent workflows only after the core support API is
  production-ready.
