# Enterprise AI Platform

## Module 1

Customer Support Copilot

---

## Objective

Build an enterprise AI platform that assists customer support agents by:

- Classifying tickets
- Summarizing issues
- Searching enterprise knowledge
- Drafting responses
- Recommending actions
- Escalating cases
- Providing analytics

---

## Current Local Architecture

The current module exposes a FastAPI ticket-analysis API with two analysis
providers:

- `MockTicketAnalysisService` for deterministic local development and tests.
- `GeminiTicketAnalysisService` for Gemini through Vertex AI.

The Gemini path can optionally use a retrieval layer:

```text
API
→ TicketAnalysisService
→ KnowledgeRetriever
→ retrieved support passages
→ Gemini prompt
```

`KnowledgeRetriever` is an async protocol. Current implementations are:

- `LocalKnowledgeRetriever`, which reads synthetic Markdown or text support
  documents from `sample_data/knowledge/`, splits them into deterministic
  chunks, and ranks them with lexical term overlap.
- `VertexRagKnowledgeRetriever`, which retrieves passages from a configured
  managed Vertex AI RAG Engine corpus and maps SDK results into the shared
  `RetrievedPassage` schema.

Provider selection is environment-based:

- `KNOWLEDGE_PROVIDER=none`: no retrieval.
- `KNOWLEDGE_PROVIDER=local`: local synthetic knowledge retrieval.
- `KNOWLEDGE_PROVIDER=vertex_rag`: managed Vertex AI RAG Engine retrieval.

The ticket-analysis API request and response contract does not change when the
retrieval provider changes.

The managed retriever isolates SDK calls behind an adapter, so tests mock the
adapter and never require Google Cloud access. Runtime authentication uses
Application Default Credentials and IAM. No API keys or credential files are
stored in the repository.

Safe retrieval telemetry records provider, retrieved chunk count, duration, and
outcome only. Logs must not include query text, retrieved content, ticket
content, generated model content, credentials, or sensitive source paths.

---

## Technology Stack

Frontend
- React (future)

Backend
- FastAPI

AI
- Gemini
- Vertex AI

Database
- BigQuery

Storage
- Cloud Storage

Deployment
- Cloud Run

Infrastructure
- Terraform

Monitoring
- Cloud Logging
- Cloud Monitoring

CI/CD
- GitHub Actions

Authentication
- IAM
- Secret Manager

Future

- RAG
- AI Agents
- Document Intelligence
- Analytics Copilot
