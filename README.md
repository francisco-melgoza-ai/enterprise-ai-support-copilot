# Enterprise AI Support Copilot

## Project Overview

FastAPI API for customer-support ticket analysis with a local deterministic mock
provider and an optional Gemini on Vertex AI provider.

This milestone intentionally does not include databases, Terraform,
application authentication, RAG, agents, or frontend work.

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

To use Gemini through Vertex AI, authenticate with Application Default
Credentials and set the provider configuration:

```bash
gcloud auth application-default login
export TICKET_ANALYSIS_PROVIDER=gemini
export GOOGLE_CLOUD_PROJECT="your-project-id"
export GOOGLE_CLOUD_LOCATION="us-central1"
export GEMINI_MODEL="gemini-2.5-flash"
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
  "ticket_id": "TICKET-123",
  "provider": "gemini",
  "model": "gemini-2.5-flash",
  "outcome": "success",
  "attempt_count": 1,
  "duration_ms": 842.3
}
```

Gemini telemetry outcomes are `success`, `timeout`, `invalid_response`, and
`error`. Logs must not include ticket subjects, ticket descriptions, generated
model content, credentials, or PII.

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
  --set-env-vars "TICKET_ANALYSIS_PROVIDER=gemini,GOOGLE_CLOUD_PROJECT=$GOOGLE_CLOUD_PROJECT,GOOGLE_CLOUD_LOCATION=$REGION,GEMINI_MODEL=gemini-2.5-flash"
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
- `GOOGLE_CLOUD_PROJECT`: required only when `TICKET_ANALYSIS_PROVIDER=gemini`.
- `GOOGLE_CLOUD_LOCATION`: optional, defaults to `us-central1`; should match the
  Vertex AI region.
- `GEMINI_MODEL`: optional, defaults to `gemini-2.5-flash`.

Do not commit credentials, API keys, service account keys, or project-specific
secrets. In Cloud Run, the Gemini provider uses Application Default Credentials
from the service runtime environment.

## Roadmap

- Add persistence and analytics after the local API contract is stable.
- Add authentication and deployment infrastructure in later platform modules.
- Add knowledge search, RAG, and agent workflows only after the core support
  API is production-ready.
