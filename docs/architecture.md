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

The Gemini path can optionally use a local retrieval layer:

```text
API
→ TicketAnalysisService
→ KnowledgeRetriever
→ retrieved support passages
→ Gemini prompt
```

`KnowledgeRetriever` is an async protocol. `LocalKnowledgeRetriever` is the
current implementation and reads synthetic Markdown or text support documents
from `sample_data/knowledge/`. It splits documents into deterministic chunks and
ranks them with lexical term overlap.

The local retriever is intentionally not a managed RAG system. It does not use
embeddings, Vertex AI RAG Engine, Vertex AI Vector Search, Vertex AI Search,
Cloud Storage ingestion, BigQuery, upload endpoints, or new cloud resources.

Future managed retrieval can replace `LocalKnowledgeRetriever` behind the same
`KnowledgeRetriever` protocol without changing the API request or response
contract.

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
