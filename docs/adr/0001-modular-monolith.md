# ADR-0001: Modular monolith over microservices

## Status
Accepted — 2026-07-26

## Context
The application combines several distinct capabilities: vendor scoring, anomaly detection, feature engineering, an agentic RAG assistant, and a human-approval workflow, on top of a shared FastAPI backend, Streamlit UI, PostgreSQL store, and MLflow tracking server. These could be built as independent microservices (e.g., a separate scoring service, a separate RAG service) or as one application with internal module boundaries.

## Decision
Build one FastAPI application with strongly separated internal layers (`api/routers` → `services` → `db`/`models`/`rag`/`workflow`), a Streamlit process that talks to it only over HTTP, and a standalone MLflow tracking server (which has its own lifecycle and storage regardless of this decision). ML and RAG are internal packages (`src/models`, `src/rag`), not separate deployable services.

## Rationale
- There is no current requirement for independent scaling or independent team ownership of scoring vs. anomaly detection vs. RAG — they operate on the same vendor/tender data and are typically invoked together to produce one recommendation.
- Network boundaries between these components would add operational cost (service discovery, inter-service auth, distributed tracing, partial-failure handling) without a corresponding benefit at this stage.
- The internal module seams (`src/models`, `src/rag`, `src/workflow`) are deliberately clean so any of them can be extracted into its own service later — e.g., if the RAG agent needs a different scaling or GPU profile — without a rewrite.
- Keeping Streamlit as a pure HTTP client of FastAPI (never touching PostgreSQL directly) is treated as a hard boundary regardless of the monolith-vs-microservices decision, because it's what keeps the human-approval gate (ADR-0002) unbypassable.

## Consequences
- Single deployable API artifact simplifies Phase 6 Docker/deployment work (one API container, one Streamlit container, one Postgres, one MLflow).
- If a future need for independent scaling emerges (e.g., RAG embedding load dominates), extracting `src/rag` into its own service is a scoped, anticipated change rather than an emergency rewrite.
- All internal modules currently share one process's memory and failure domain — a crash in RAG tool execution must not be allowed to take down request handling for scoring/anomaly endpoints; this needs to be enforced with proper exception boundaries in the API layer during Phase 3/4 implementation.
