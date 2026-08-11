# ADR-0003: Minimal role-based auth stub for initial build

## Status
Accepted — 2026-07-26

## Context
The human-approval gate (ADR-0002) depends on identity: maker-checker requires knowing who prepared a recommendation and who is approving it, and roles (preparer/reviewer/admin) gate which actions are allowed. Full enterprise identity integration (OAuth2/OIDC against a corporate identity provider, SSO) is a real requirement for production deployment but is substantial upfront work that isn't necessary to build and validate the rest of the system.

## Decision
Phase 3 implements a minimal role-based auth stub: a JWT or role-header-based mechanism with three roles (preparer, reviewer, admin), sufficient to enforce maker-checker and demonstrate/test the approval gate end-to-end. Full OAuth2/OIDC/SSO integration is explicitly deferred, not designed away — the auth dependency in `src/api/dependencies.py` should be isolated enough that swapping in a real identity provider later doesn't require touching the workflow or approval logic.

## Rationale
- This was an explicit choice made with the user over the alternative of building full enterprise auth now, or skipping auth entirely (which would make maker-checker unenforceable, undermining ADR-0002's core guarantee).
- A stub is enough to write meaningful tests for the approval gate (illegal transitions, reviewer == preparer rejection) without blocking Phase 3 on identity-provider integration work that has no bearing on the ML/RAG/workflow architecture.
- Isolating auth behind a dependency (rather than scattering role checks inline) keeps the later upgrade to real SSO a contained change.

## Consequences
- The initial build is **not** production-ready from a security standpoint until real identity integration replaces the stub — this must be called out explicitly in Phase 6 hardening and not allowed to be quietly forgotten.
- Role/permission logic should be centralized (e.g., a single `require_role()` dependency) so the eventual swap touches one place, not every router.
