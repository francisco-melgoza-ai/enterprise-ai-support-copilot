# Enterprise AI Support Copilot

## Project Overview

Local FastAPI API for deterministic customer-support ticket analysis.

This milestone intentionally does not include Gemini, Vertex AI, databases,
Docker, Terraform, authentication, or cloud services.

## Architecture

The Sprint 1 API follows a small layered shape:

```text
API -> Service -> Schemas -> Core
```

- API routes handle HTTP concerns only.
- Pydantic schemas define request and response contracts.
- `TicketAnalysisService` defines the analysis interface.
- `MockTicketAnalysisService` provides deterministic local analysis.
- FastAPI dependency injection wires routes to the service.
- Core logging emits structured request metadata and never logs ticket subject,
  description, or PII.

## Local Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

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

- Add real AI integration behind the existing service interface.
- Add persistence and analytics after the local API contract is stable.
- Add authentication and deployment infrastructure in later platform modules.
- Add knowledge search, RAG, and agent workflows only after the core support
  API is production-ready.
