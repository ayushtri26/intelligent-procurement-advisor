# ADR-0002: DB-backed human approval gate

## Status
Accepted — 2026-07-26

## Context
The product requirement is explicit and non-negotiable: no procurement decision may execute without human approval. This has to survive future code changes, not just hold true in the initial implementation — a bug, a shortcut UI feature, or an unrelated refactor must not be able to create a silently-approved decision.

## Decision
Model approval as a persisted state machine on `recommendations.status`, with values `DRAFT, PENDING_REVIEW, APPROVED, REJECTED, ESCALATED`. Every recommendation is created in `PENDING_REVIEW`. The only code path permitted to set `APPROVED` is `src/workflow/approval_service.py`, which enforces maker-checker (approving identity ≠ preparing identity) and writes an append-only audit row (`decision_audit_log`) in the same transaction as the status change. Any future code that "executes" a decision must independently re-check `status == APPROVED` at the point of execution.

## Rationale
- An in-memory flag or a status field writable from multiple places cannot give this guarantee — any endpoint or script that can `UPDATE recommendations SET status='APPROVED'` becomes a bypass. Concentrating the transition in one service function makes the gate auditable and testable in isolation (illegal-transition tests belong in Phase 3's unit tests).
- Append-only audit logging (no UPDATE/DELETE at the app layer, and ideally enforced by a DB permission or trigger later) means the history of who approved what, and when, cannot be quietly edited after the fact.
- Maker-checker (the approver cannot be the preparer) is a standard control for exactly this kind of decision and is cheap to enforce once identity exists (see ADR-0003).
- Re-checking `status == APPROVED` at the execution point, rather than trusting the caller already validated it, is defense in depth: it means even a future feature that forgets to call through `approval_service` first will still fail safe.

## Consequences
- Streamlit must never write to PostgreSQL directly (see ADR-0001) — it can only reach `APPROVED` via `POST /recommendations/{id}/approve`.
- A periodic reconciliation job (Phase 6 hardening) should flag any "executed" decision without a matching approval audit event, as a backstop against a bypass nobody anticipated.
- Every recommendation's `ExplanationBundle`, `model_version`, `feature_set_version`, and `scoring_config_version` must be captured at creation time (not looked up later) so an approved decision remains fully reproducible even after models or config change.
