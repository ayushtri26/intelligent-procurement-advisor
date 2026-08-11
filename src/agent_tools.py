"""Tool schemas and executors for the Claude procurement agent.

Every tool wraps a deterministic function from src.analytics_tools or
src.rag — Claude only ever receives already-computed, JSON-safe results. No
tool here calls an LLM, and no tool ever computes a score/rank/anomaly flag
itself; they only look up and format facts that src.analytics_tools already
produced.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from src import analytics_tools as at
from src import procurement_assistant as pa
from src.vendor_scoring import DEFAULT_WEIGHTS

MAX_TOP_N = 10
MAX_RETRIEVAL_K = 8

FEATURE_NAME_MAP = {
    "price": "price_competitiveness",
    "delivery": "delivery_reliability",
    "quality": "quality_score",
    "compliance": "compliance_score",
    "experience": "experience_score",
    "financial": "financial_stability_score",
}


def _json_safe(obj):
    """Recursively convert numpy/pandas scalars into plain JSON-serializable Python values."""
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (pd.Series,)):
        return _json_safe(obj.to_dict())
    if isinstance(obj, (pd.DataFrame,)):
        return _json_safe(obj.to_dict(orient="records"))
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        value = float(obj)
        return None if math.isnan(value) else value
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, float) and math.isnan(obj):
        return None
    return obj


def _resolve_vendor(df: pd.DataFrame, name_or_id: str) -> pd.Series | None:
    return pa.find_vendor(df, name_or_id)


# --------------------------------------------------------------------------
# Tool schemas (Anthropic tool-use format)
# --------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "name": "get_top_vendors",
        "description": "Get the top N vendors ranked by overall weighted score (highest first). Use for ranking/shortlist questions.",
        "input_schema": {
            "type": "object",
            "properties": {"n": {"type": "integer", "description": "Number of vendors to return (default 5, max 10)."}},
        },
    },
    {
        "name": "get_vendor_details",
        "description": "Get full evaluation detail for one specific vendor by name or ID: scores, rank, strengths, risks, confidence, due diligence.",
        "input_schema": {
            "type": "object",
            "properties": {"vendor": {"type": "string", "description": "Vendor name or ID, e.g. 'Everest Logistics Partners' or 'V005'."}},
            "required": ["vendor"],
        },
    },
    {
        "name": "compare_vendors",
        "description": "Compare two or more named vendors side by side across all scoring dimensions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "vendors": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Two or more vendor names or IDs to compare.",
                }
            },
            "required": ["vendors"],
        },
    },
    {
        "name": "get_cheapest_qualified_vendor",
        "description": "Get the cheapest vendor that still clears a minimum overall-score bar and isn't anomalous.",
        "input_schema": {
            "type": "object",
            "properties": {"min_overall_score": {"type": "number", "description": "Minimum overall score to qualify (default 60)."}},
        },
    },
    {
        "name": "get_safest_vendor",
        "description": "Get the vendor with the strongest compliance, financial-stability, and quality profile (lowest risk).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_best_value_vendor",
        "description": "Get the vendor with the best quality delivered per unit price (best value for money).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "explain_anomaly",
        "description": "Explain why a specific vendor was (or was not) flagged as anomalous by the Isolation Forest model, with the driving features.",
        "input_schema": {
            "type": "object",
            "properties": {"vendor": {"type": "string", "description": "Vendor name or ID."}},
            "required": ["vendor"],
        },
    },
    {
        "name": "get_compliance_risks",
        "description": "List vendors whose compliance score falls below a risk threshold.",
        "input_schema": {
            "type": "object",
            "properties": {"threshold": {"type": "number", "description": "Compliance score threshold (default 60)."}},
        },
    },
    {
        "name": "run_weight_sensitivity",
        "description": "Recompute vendor rankings if one scoring criterion is weighted more or less heavily, to answer 'what if' questions. Shows whether the top vendor or rankings change.",
        "input_schema": {
            "type": "object",
            "properties": {
                "feature": {
                    "type": "string",
                    "enum": ["price", "delivery", "quality", "compliance", "experience", "financial"],
                    "description": "Which scoring criterion to reweight.",
                },
                "direction": {"type": "string", "enum": ["more", "less"], "description": "Whether the criterion should matter more or less."},
            },
            "required": ["feature", "direction"],
        },
    },
    {
        "name": "retrieve_procurement_documents",
        "description": "Semantic search over the uploaded procurement documents (tenders, contracts, policies). Returns the most relevant passages with citations (filename, page, chunk id). Use for any question about document content or requirements.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for in the documents."},
                "top_k": {"type": "integer", "description": "Number of passages to retrieve (default 4, max 8)."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "generate_vendor_recommendation",
        "description": "Produce the full, structured recommendation bundle (reasons, trade-offs, anomaly status, confidence, due-diligence checklist) for a specific vendor. Call this for the vendor you intend to recommend before writing your final answer — never assemble a recommendation yourself.",
        "input_schema": {
            "type": "object",
            "properties": {
                "vendor": {"type": "string", "description": "Vendor name or ID to build the recommendation for."},
                "rationale": {"type": "string", "description": "Short reason this vendor is being recommended, e.g. 'lowest price among qualified vendors'."},
            },
            "required": ["vendor"],
        },
    },
]


# --------------------------------------------------------------------------
# Executors
# --------------------------------------------------------------------------

def build_tool_executor(df: pd.DataFrame, current_weights: dict | None, knowledge_base) -> dict:
    """Return {tool_name: callable(args_dict) -> JSON-safe dict} bound to this request's data."""
    weights = current_weights or DEFAULT_WEIGHTS

    def get_top_vendors(args: dict) -> dict:
        n = min(int(args.get("n", 5) or 5), MAX_TOP_N)
        top_df = at.get_top_vendors(df, n)
        return {"vendors": [at.vendor_record(r) for _, r in top_df.iterrows()]}

    def get_vendor_details(args: dict) -> dict:
        vendor = _resolve_vendor(df, args.get("vendor", ""))
        if vendor is None:
            return {"found": False, "message": f"No vendor matching '{args.get('vendor')}' found in the current evaluation."}
        return at.explain_vendor(df, vendor["vendor_id"])

    def compare_vendors_tool(args: dict) -> dict:
        names = args.get("vendors") or []
        resolved = []
        unresolved = []
        for name in names:
            row = _resolve_vendor(df, name)
            if row is not None:
                resolved.append(row["vendor_id"])
            else:
                unresolved.append(name)
        if len(resolved) < 2:
            return {
                "ok": False,
                "message": "Need at least two resolvable vendors to compare.",
                "resolved": resolved,
                "unresolved": unresolved,
            }
        comparison_df = at.compare_vendors(df, resolved)
        details = {vid: at.explain_vendor(df, vid) for vid in resolved}
        return {"ok": True, "comparison": comparison_df.to_dict(orient="records"), "details": details, "unresolved": unresolved}

    def get_cheapest_qualified_vendor(args: dict) -> dict:
        min_score = float(args.get("min_overall_score", 60.0) or 60.0)
        row, fallback_used = at.get_cheapest_qualified_vendor(df, min_overall_score=min_score)
        bundle = at.build_recommendation_bundle(df, row, "Lowest quoted price among qualified, non-anomalous vendors.")
        bundle["fallback_used"] = fallback_used
        return bundle

    def get_safest_vendor(args: dict) -> dict:
        row, fallback_used = at.get_safest_vendor(df)
        bundle = at.build_recommendation_bundle(df, row, "Strongest compliance, financial-stability, and quality profile.")
        bundle["fallback_used"] = fallback_used
        return bundle

    def get_best_value_vendor(args: dict) -> dict:
        row, fallback_used = at.get_best_value_vendor(df)
        bundle = at.build_recommendation_bundle(df, row, "Best quality delivered relative to price among non-anomalous vendors.")
        bundle["fallback_used"] = fallback_used
        return bundle

    def explain_anomaly(args: dict) -> dict:
        vendor = _resolve_vendor(df, args.get("vendor", ""))
        if vendor is None:
            return {"found": False, "message": f"No vendor matching '{args.get('vendor')}' found."}
        return at.explain_anomaly(df, vendor["vendor_id"])

    def get_compliance_risks(args: dict) -> dict:
        threshold = float(args.get("threshold", at.COMPLIANCE_RISK_THRESHOLD) or at.COMPLIANCE_RISK_THRESHOLD)
        risky = at.get_compliance_risks(df, threshold=threshold)
        return {"threshold": threshold, "vendors": risky.to_dict(orient="records")}

    def run_weight_sensitivity(args: dict) -> dict:
        feature_key = args.get("feature")
        feature = FEATURE_NAME_MAP.get(feature_key)
        direction = args.get("direction", "more")
        if feature is None:
            return {"ok": False, "message": f"Unknown feature '{feature_key}'. Use one of: {list(FEATURE_NAME_MAP)}."}
        adjusted = pa.adjust_weight(weights, feature, direction)
        result = at.run_weight_sensitivity(df, adjusted)
        return {
            "ok": True,
            "feature": feature,
            "direction": direction,
            "top_before": result["top_before"],
            "top_after": result["top_after"],
            "top_changed": result["top_changed"],
            "comparison": result["comparison"].to_dict(orient="records"),
        }

    def retrieve_procurement_documents(args: dict) -> dict:
        query = args.get("query", "")
        top_k = min(int(args.get("top_k", 4) or 4), MAX_RETRIEVAL_K)
        if knowledge_base is None or not knowledge_base.is_ready:
            return {"ok": False, "results": [], "message": "No procurement documents have been indexed yet."}
        retrieved = knowledge_base.retrieve(query, k=top_k)
        if not retrieved:
            return {"ok": True, "results": [], "message": "No relevant passages found in the uploaded documents."}
        results = [
            {
                "filename": r.chunk.filename,
                "page": r.chunk.page,
                "chunk_id": r.chunk.chunk_id,
                "text": r.chunk.text,
                "relevance_score": round(r.score, 3),
            }
            for r in retrieved
        ]
        return {"ok": True, "results": results}

    def generate_vendor_recommendation(args: dict) -> dict:
        vendor = _resolve_vendor(df, args.get("vendor", ""))
        if vendor is None:
            return {"found": False, "message": f"No vendor matching '{args.get('vendor')}' found."}
        rationale = args.get("rationale") or "Selected based on the analysis performed in this conversation."
        bundle = at.build_recommendation_bundle(df, vendor, rationale)
        bundle["found"] = True
        return bundle

    raw_executors = {
        "get_top_vendors": get_top_vendors,
        "get_vendor_details": get_vendor_details,
        "compare_vendors": compare_vendors_tool,
        "get_cheapest_qualified_vendor": get_cheapest_qualified_vendor,
        "get_safest_vendor": get_safest_vendor,
        "get_best_value_vendor": get_best_value_vendor,
        "explain_anomaly": explain_anomaly,
        "get_compliance_risks": get_compliance_risks,
        "run_weight_sensitivity": run_weight_sensitivity,
        "retrieve_procurement_documents": retrieve_procurement_documents,
        "generate_vendor_recommendation": generate_vendor_recommendation,
    }

    def _wrap(fn):
        def wrapped(args: dict) -> dict:
            try:
                return _json_safe(fn(args or {}))
            except Exception as exc:
                return {"error": f"Tool execution failed: {exc}"}

        return wrapped

    return {name: _wrap(fn) for name, fn in raw_executors.items()}
