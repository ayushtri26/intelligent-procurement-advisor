# Intelligent Procurement Advisor

A single Streamlit app for end-to-end procurement vendor evaluation: upload vendor data and procurement documents, engineer features, score vendors with configurable weights, flag anomalies with Isolation Forest, ground a Claude-powered agent in both the vendor data and a local document knowledge base, and require explicit human approval before any vendor is treated as selected.

This is a local-only build: no database, no Docker, no auth — the only external dependency is an optional Claude API call.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -r requirements.txt

streamlit run app.py
```

Then, in the app, click **Use sample dataset** (backed by `data/sample_vendors.csv`) or upload your own vendor CSV.

## The AI procurement agent

With `ANTHROPIC_API_KEY` configured, Section 5 runs a single Claude-powered agent that decides for itself which tools to call — vendor analytics (rankings, comparisons, anomaly explanations, compliance risk, weight sensitivity) and/or `retrieve_procurement_documents` for questions about uploaded tenders/contracts/policies. Claude only ever *interprets* results that these tools already computed; it never calculates a score, rank, or anomaly flag itself, and every document-derived claim is cited (filename, page if available, chunk id).

1. Copy `.env.example` to `.env`.
2. Set `ANTHROPIC_API_KEY=<your key>`.
3. Restart the app.

**Without a key** (or if the Claude call fails for any reason — rate limit, network, no credits), the app falls back automatically: a deterministic rule-based assistant still answers vendor-analytics questions, and document search still runs and displays the matching passages with citations. The UI always labels which path produced an answer — it never claims a rule-based answer came from Claude.

## Procurement document knowledge base (RAG)

Section 4 accepts PDF, TXT, and DOCX uploads. Clicking **Build / Refresh Knowledge Base**:

1. Extracts text (PyMuPDF for PDF — page numbers preserved; python-docx for DOCX; plain read for TXT).
2. Splits it into overlapping ~800-character chunks.
3. Embeds each chunk locally with `sentence-transformers` (default model `all-MiniLM-L6-v2`, CPU-friendly, configurable via `EMBEDDING_MODEL`).
4. Indexes the embeddings in a local FAISS index (in-memory, rebuilt each time you click the button).

Every retrieved passage carries its filename, page (when available), and chunk id, so any document-derived claim can be traced back to its source.

## How scoring works

Six 0-100 feature scores are engineered per vendor (price competitiveness, delivery reliability, quality, compliance, experience, financial stability). The sidebar lets you reweight these live; weights are auto-normalized to sum to 100%. Isolation Forest flags vendors whose feature profile is statistically unusual relative to the rest of the uploaded vendors — adjust the expected anomaly rate in the sidebar.

## Human approval

Ranking, scoring, and the AI agent never auto-select a vendor. Section 6 requires a person to explicitly pick a vendor from a dropdown and click **Confirm Approval** before an "Approved Vendor" result is shown.

## Expected CSV columns

`vendor_id, vendor_name, category, quoted_price, market_avg_price, on_time_delivery_rate, avg_delay_days, defect_rate, quality_rating, certifications_count, compliance_violations, years_in_business, completed_contracts, annual_revenue, debt_to_equity_ratio`

Missing numeric values are reported in the UI and then imputed with the column median before scoring.

## Environment variables

```
ANTHROPIC_API_KEY=       # optional — omit to run fully rule-based
CLAUDE_MODEL=claude-sonnet-5
EMBEDDING_MODEL=all-MiniLM-L6-v2
```

## Project structure

```
app.py                        # Streamlit UI — the only entry point
src/
  data_processing.py          # CSV loading + validation
  feature_engineering.py      # 0-100 feature score calculations
  vendor_scoring.py           # configurable weighted overall score + ranking
  anomaly_detection.py        # Isolation Forest + rule-based driver explanations
  analytics_tools.py          # deterministic vendor analytics (never LLM-computed)
  rag.py                      # document extraction, chunking, embeddings, FAISS, retrieval
  llm_service.py              # Anthropic client abstraction, fails soft with no key
  agent_tools.py              # tool schemas + executors binding Claude tools to analytics_tools/rag
  agent.py                    # Claude tool-use loop (single agent, max-iteration capped)
  procurement_assistant.py    # deterministic fallback assistant (intent detection, fuzzy matching)
  recommendation.py           # per-vendor detail narrative (Section 3 "inspect a vendor" panel)
data/sample_vendors.csv       # sample dataset
tests/                        # pytest suite: analytics, RAG, agent tool routing, assistant
```

## Notes

This build intentionally skips the enterprise architecture (FastAPI, PostgreSQL, Docker, MLflow, auth, LangGraph/multi-agent orchestration) in favor of a single working Streamlit app with one agent and local RAG. See `docs/architecture.md` for the longer-term enterprise design this can grow into.
