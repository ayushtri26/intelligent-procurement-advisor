# Intelligent Procurement Advisor — Architecture

## 1. Purpose

Intelligent Procurement Advisor evaluates vendors for procurement tenders, detects anomalous vendor behavior, produces configurable, explainable vendor scores, and answers questions over procurement documents via an agentic RAG assistant. Every recommendation it produces requires explicit human approval before it can be treated as a decision — the application recommends, it never decides.

This document describes the target architecture. It is a living document; material changes should be recorded as a new ADR under `docs/adr/` rather than by silently editing history here.

## 2. Goals and non-goals

**Goals**
- Score and rank vendors against tender criteria using a transparent, configurable weighted model.
- Flag anomalous vendor behavior (pricing, delivery, bidding patterns) using Isolation Forest.
- Explain every recommendation with evidence: score contributions, anomaly drivers, and cited source documents.
- Enforce a hard human-approval gate before any procurement decision is considered final.
- Track models and experiments reproducibly (MLflow) so any past recommendation can be traced back to the exact model, feature set, and scoring configuration that produced it.

**Non-goals (for now)**
- Fully autonomous procurement execution (explicitly excluded by design).
- Multi-tenant / multi-organization deployment.
- Full enterprise SSO/OIDC integration (deferred past the initial build — see ADR-0003).
- Microservice decomposition of ML/RAG (deferred — see ADR-0001).

## 3. System architecture

### 3.1 Service topology

A **modular monolith**: one FastAPI application with clearly separated internal layers, a Streamlit UI that speaks to it only over HTTP, and a standalone MLflow tracking server. See [ADR-0001](adr/0001-modular-monolith.md) for the reasoning.

```
┌─────────────┐   HTTPS/JSON   ┌───────────────────────────────────────────┐
│  Streamlit  │ ─────────────▶ │              FastAPI app                    │
│  (UI only)  │ ◀───────────── │  routers → services → domain → db           │
└─────────────┘                │                                             │
                                │  ┌─────────────┐   ┌──────────────────┐   │
                                │  │ ML subsystem │   │ Agentic RAG      │   │
                                │  │ IsolForest,  │   │ FAISS + Claude   │   │
                                │  │ scoring,     │   │ agent loop+tools │   │
                                │  │ explainer    │   │                  │   │
                                │  └──────┬───────┘   └────────┬─────────┘   │
                                │         ▼                    ▼             │
                                │  ┌───────────────────────────────────┐    │
                                │  │ Workflow (approval state machine)  │    │
                                │  │ + append-only audit log            │    │
                                │  └──────────────────┬──────────────────┘   │
                                └─────────────────────┼──────────────────────┘
                                                       ▼
                                ┌───────────────────────────────────────────┐
                                │              PostgreSQL                     │
                                │ vendors, tenders, bids, documents,          │
                                │ vendor_features, scoring_config,            │
                                │ recommendations, decision_audit_log         │
                                └───────────────────────────────────────────┘
                                                       ▲
                                ┌──────────────────────┴──────────────────────┐
                                │            MLflow tracking server             │
                                │ experiments, metrics, model registry          │
                                │ (anomaly + scoring models)                    │
                                └───────────────────────────────────────────┘
```

The one boundary treated as hard, not just conventional: **Streamlit never touches PostgreSQL directly.** It is a pure API client. This is what keeps the human-approval gate unbypassable — there is no UI code path that can write a decision state directly to the database.

### 3.2 Human-approval workflow

Implemented as a DB-backed state machine, not an in-memory flag.

- `recommendations.status ∈ {DRAFT, PENDING_REVIEW, APPROVED, REJECTED, ESCALATED}`. Every recommendation is created in `PENDING_REVIEW`; there is no code path that creates one already `APPROVED`.
- `decision_audit_log` is append-only: actor, role, timestamp, previous status, new status, justification. Written in the same transaction as any status change.
- `src/workflow/approval_service.py` is the **only** code path permitted to set `APPROVED`. It enforces maker-checker separation (the approving identity must differ from the preparing identity) and writes the audit row atomically with the status change.
- Any future logic that "executes" a decision must independently re-check `status == APPROVED` at the point of execution rather than trusting an earlier check — defense in depth against a future code path that forgets the gate.
- API surface: `POST /recommendations`, `GET /recommendations/{id}`, `POST /recommendations/{id}/approve`, `POST /recommendations/{id}/reject`, `GET /recommendations/{id}/audit-trail`.

See [ADR-0002](adr/0002-human-approval-gate.md).

### 3.3 Agentic RAG assistant

`src/rag/agent.py` runs a bounded tool-use loop (hard cap on iterations and wall-clock time) against a fixed toolset defined in `src/rag/tools.py`:

| Tool | Purpose |
|---|---|
| `search_documents(query, filters)` | FAISS similarity search over chunked procurement documents |
| `get_vendor_profile(vendor_id)` | Structured vendor lookup |
| `get_vendor_score(vendor_id, tender_id)` | Calls the scoring service, returns score + per-criterion breakdown |
| `get_anomaly_flags(vendor_id)` | Calls the anomaly model wrapper |
| `get_tender_requirements(tender_id)` | Tender criteria / spec lookup |
| `compare_vendors(vendor_ids, tender_id)` | Composite comparison built from the above |

The LLM backing the agent is **Anthropic (Claude)**, reached through `src/rag/llm_client.py` — a thin interface, not a hard dependency baked into `agent.py`, so the provider can be swapped later without touching agent logic (see [ADR-0004](adr/0004-llm-provider.md)).

The agent's output is a structured object: answer text plus a list of `Citation{doc_id, chunk_id, page, snippet, score}`. It is never returned as free text alone. This output feeds `services/procurement_advisor.py` strictly as **evidence** — the agent has no path to `APPROVED`; it informs a recommendation, it does not gate one.

### 3.4 Explainability

One `ExplanationBundle` Pydantic schema — defined before any model code exists — that all model and agent work targets:

- **Vendor scoring**: exact, not approximated. `{criterion, raw_value, normalized_value, weight, contribution}` rows plus total, read directly off the weighted computation.
- **Anomaly detection**: Isolation Forest has no native per-feature attribution. Use a model-agnostic SHAP explainer (Kernel/Permutation) on a background sample, or a shallow interpretable surrogate validated by fidelity (R²) against the true anomaly score. Presented in the UI as "top contributing features," with that caveat stated explicitly — not framed as an exact attribution guarantee.
- **RAG**: the citation list described in §3.3.

The bundle is persisted with every recommendation alongside `feature_set_version`, `model_version` (from the MLflow registry), and `scoring_config_version`, so any past recommendation is fully reproducible after models or weights change.

### 3.5 Configurable dynamic vendor scoring

`scoring_config` is a versioned table (`effective_from`/`effective_to`, `changed_by`, `change_reason`), not a hardcoded weight dict. `src/models/vendor_scoring.py` reads the active configuration for a given category/tender-type and computes a weighted multi-criteria score. Changing weights goes through the same maker-checker approval pattern as procurement decisions, and every recommendation records which `scoring_config_version` was used to produce it — so scoring stays governable and auditable, not just configurable.

## 4. Data model (core entities)

- `vendors`, `tenders`, `bids`, `procurement_documents`
- `vendor_features` (versioned, output of feature engineering)
- `scoring_config` (versioned weight profiles)
- `recommendations` (status, score, anomaly flags, `ExplanationBundle`, model/config versions)
- `decision_audit_log` (append-only)

## 5. Folder structure

```
.
├── alembic/                         # Postgres migrations
├── docker/                          # Dockerfiles + docker-compose.yml (postgres, mlflow, api, streamlit)
├── data/{raw,processed,sample,vector_store}/
├── docs/{architecture.md, adr/}
├── scripts/                         # train_anomaly_model.py, ingest_documents.py, seed_db.py
├── src/
│   ├── api/            # FastAPI app, routers, request/response schemas
│   ├── config/         # Pydantic Settings, scoring_config loader
│   ├── db/             # SQLAlchemy entities + repositories (separate from ML "models")
│   ├── data/           # sample data generation
│   ├── features/       # feature engineering
│   ├── models/         # ML wrappers: anomaly_model.py, vendor_scoring.py
│   ├── explainability/ # anomaly_explainer.py, scoring_explainer.py
│   ├── rag/            # document_loader, retriever (FAISS), agent, tools, llm_client
│   ├── workflow/        # approval state machine + service
│   ├── services/        # procurement_advisor.py — orchestrates everything above
│   ├── ui/               # Streamlit app
│   └── utils/            # logger, etc.
└── tests/{unit,integration}/
```

`src/models/` is reserved for ML model wrappers only. SQLAlchemy ORM entities live in `src/db/models/` to avoid the naming collision between "ML model" and "database model."

## 6. Implementation phases

0. **Foundation** — settings, logging, docker-compose skeleton, Alembic init with the approval/audit/scoring-config tables and the `ExplanationBundle` schema created up front.
1. **Data & feature engineering** — synthetic data generator, core entity migrations, versioned `vendor_features`.
2. **Anomaly detection + vendor scoring + MLflow** — Isolation Forest wrapper, explainers, weighted scorer, MLflow tracking and model registry.
3. **API + human approval workflow** — routers, state machine, maker-checker, minimal role-based auth stub.
4. **Agentic RAG (Claude)** — ingestion, FAISS index, bounded agent loop, tools, `/rag/ask`.
5. **Streamlit UI** — scoring dashboard, anomaly review, RAG assistant, approvals queue.
6. **Docker/deployment/hardening** — compose orchestration, healthchecks, rate limiting, PII-scrubbed logging.
7. **Tests + CI** — integration tests, contract tests for `ExplanationBundle`, coverage gate, CI pipeline.

The gate and the explanation contract are designed in Phase 0, before any model or write-path code exists, specifically so nothing downstream has to be retrofitted around them.

## 7. Key risks

See individual ADRs for the decisions that mitigate these; summarized here:

1. Isolation Forest has no native feature attribution — mitigated with SHAP model-agnostic explainers or a validated surrogate.
2. FAISS indexes don't support easy in-place update — mitigated with versioned rebuild-on-ingest and atomic swap.
3. Agentic RAG can hallucinate or loop — mitigated with iteration/timeout budgets and mandatory citation grounding.
4. Procurement data includes PII/sensitive financials — mitigated with field-level classification, encryption, log scrubbing, RBAC.
5. The approval gate could be bypassed by a future code path — mitigated by a single enforced code path, DB constraints, and periodic reconciliation.
6. New vendors have no history to score against — mitigated with a fallback profile and explicit low-confidence flagging.
7. MLflow "Production" model can drift from what's actually loaded in the API — mitigated by pinning explicit versions and logging them per prediction.
8. Scoring weights are powerful and could be changed to bias outcomes — mitigated by versioning, governance, and maker-checker approval on config changes.

## 8. Architecture Decision Records

- [ADR-0001](adr/0001-modular-monolith.md) — Modular monolith over microservices
- [ADR-0002](adr/0002-human-approval-gate.md) — DB-backed human approval gate
- [ADR-0003](adr/0003-auth-scope.md) — Minimal role-based auth stub for initial build
- [ADR-0004](adr/0004-llm-provider.md) — Anthropic (Claude) as the Agentic RAG LLM provider
