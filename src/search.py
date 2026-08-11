"""Global search across vendors, indexed documents, and past chat questions.

Pure lookup over already-computed/loaded state — no new indices are built
for vendors or chat history (simple substring matching is sufficient at this
scale); documents reuse the existing FAISS-backed KnowledgeBase.retrieve()
for semantic matches when the knowledge base has been built.
"""
from __future__ import annotations

import pandas as pd

MIN_DOC_RELEVANCE = 0.15


def global_search(
    query: str,
    ranked_df: pd.DataFrame | None,
    knowledge_base=None,
    chat_history: list[dict] | None = None,
    max_results_per_group: int = 5,
) -> dict[str, list[dict]]:
    query = (query or "").strip()
    if not query:
        return {}

    results: dict[str, list[dict]] = {}
    q_lower = query.lower()

    if ranked_df is not None and not ranked_df.empty:
        mask = (
            ranked_df["vendor_name"].astype(str).str.lower().str.contains(q_lower, na=False)
            | ranked_df["vendor_id"].astype(str).str.lower().str.contains(q_lower, na=False)
        )
        matches = ranked_df[mask].head(max_results_per_group)
        if not matches.empty:
            results["Vendors"] = [
                {
                    "label": f"{row['vendor_name']} ({row['vendor_id']})",
                    "subtitle": f"Rank #{int(row['rank'])} · Score {row['overall_score']:.1f}/100"
                    + (" · Anomalous" if bool(row.get("is_anomalous", False)) else ""),
                    "vendor_id": row["vendor_id"],
                }
                for _, row in matches.iterrows()
            ]

    if knowledge_base is not None and getattr(knowledge_base, "is_ready", False):
        retrieved = knowledge_base.retrieve(query, k=max_results_per_group)
        doc_hits = [r for r in retrieved if r.score >= MIN_DOC_RELEVANCE]
        if doc_hits:
            results["Documents"] = [
                {
                    "label": f"{r.chunk.filename}" + (f", p.{r.chunk.page}" if r.chunk.page else ""),
                    "subtitle": r.chunk.text[:160] + ("…" if len(r.chunk.text) > 160 else ""),
                    "chunk_id": r.chunk.chunk_id,
                }
                for r in doc_hits
            ]

    if chat_history:
        matches = [
            entry for entry in chat_history
            if entry.get("role") == "user" and q_lower in entry.get("text", "").lower()
        ][:max_results_per_group]
        if matches:
            results["Conversations"] = [
                {"label": entry["text"], "subtitle": "Asked in AI Assistant"}
                for entry in matches
            ]

    return results
