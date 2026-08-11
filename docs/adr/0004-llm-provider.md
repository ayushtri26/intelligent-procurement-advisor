# ADR-0004: Anthropic (Claude) as the Agentic RAG LLM provider

## Status
Accepted — 2026-07-26

## Context
The required technology stack (Python, FastAPI, Streamlit, PostgreSQL, SQLAlchemy, Pydantic, Scikit-learn, FAISS, MLflow, Pytest, Docker) does not pin an LLM provider for the Agentic RAG assistant. A provider must be chosen to implement `src/rag/agent.py` and `src/rag/llm_client.py`.

## Decision
Target the Anthropic API (Claude) as the LLM backing the agentic RAG assistant, accessed through a dedicated interface module (`src/rag/llm_client.py`) rather than calling the Anthropic SDK directly from `agent.py` or `tools.py`.

## Rationale
- Explicit choice made with the user when presented with Anthropic, OpenAI, provider-agnostic-stub, and local/self-hosted options.
- Wrapping the provider behind `llm_client.py` keeps `agent.py`'s tool-use loop and orchestration logic independent of the specific SDK, so a different provider or a local model can be substituted later (e.g., for cost, latency, or data-residency reasons) via configuration rather than a rewrite.

## Consequences
- `requirements.txt` includes the `anthropic` SDK; `src/config/settings.py` needs an Anthropic API key setting, sourced from environment/secret store, never committed.
- Cost, rate limits, and availability of the Anthropic API become an operational dependency for the RAG assistant specifically (not for scoring/anomaly detection, which have no LLM dependency) — this should be monitored and is called out as a standing risk in `docs/architecture.md` §7.
- The bounded tool-use loop (max iterations, wall-clock timeout) in `agent.py` should be implemented against the `llm_client.py` interface, not against Anthropic-specific response types directly, to keep the swap-out path real rather than theoretical.
