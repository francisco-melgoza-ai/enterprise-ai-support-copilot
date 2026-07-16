# Enterprise AI Support Copilot

## Project Overview

FastAPI API for customer-support ticket analysis with a local deterministic mock
provider and an optional Gemini on Vertex AI provider.

This milestone intentionally does not include databases, Docker, Terraform,
authentication, RAG, agents, or deployment infrastructure.

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

## Endpoints

- `GET /health`
- `POST /api/v1/tickets/analyze`

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

## Roadmap

- Add persistence and analytics after the local API contract is stable.
- Add authentication and deployment infrastructure in later platform modules.
- Add knowledge search, RAG, and agent workflows only after the core support
  API is production-ready.
