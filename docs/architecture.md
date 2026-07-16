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
  lexical overlap.
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

## Observability

The application uses structured JSON logging and request correlation.

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

## Out Of Scope

The current implementation does not include:

- BigQuery conversation analytics
- Authentication or authorization
- Terraform
- CI/CD
- Frontend UI
- Agent workflows
- Automated production knowledge ingestion pipeline
