"""Tests for tool execution: each tool must return JSON-safe, deterministic
facts computed by src.analytics_tools / src.rag — never invented by an LLM."""
import json

from src import agent_tools
from src.rag import DocumentChunk, KnowledgeBase, RetrievedChunk


def test_get_top_vendors_respects_cap(ranked_df):
    executor = agent_tools.build_tool_executor(ranked_df, None, None)
    result = executor["get_top_vendors"]({"n": 999})
    assert len(result["vendors"]) == agent_tools.MAX_TOP_N
    json.dumps(result)


def test_get_vendor_details_fuzzy_match(ranked_df):
    executor = agent_tools.build_tool_executor(ranked_df, None, None)
    result = executor["get_vendor_details"]({"vendor": "Evrest Logistics Partners"})
    assert result["found"] is True
    assert result["record"]["vendor_name"] == "Everest Logistics Partners"


def test_get_vendor_details_unknown_vendor(ranked_df):
    executor = agent_tools.build_tool_executor(ranked_df, None, None)
    result = executor["get_vendor_details"]({"vendor": "Nonexistent Vendor Zzz"})
    assert result["found"] is False


def test_compare_vendors_needs_two_resolvable(ranked_df):
    executor = agent_tools.build_tool_executor(ranked_df, None, None)
    top_name = ranked_df.sort_values("overall_score", ascending=False).iloc[0]["vendor_name"]
    result = executor["compare_vendors"]({"vendors": [top_name]})
    assert result["ok"] is False


def test_compare_vendors_two_names(ranked_df):
    executor = agent_tools.build_tool_executor(ranked_df, None, None)
    names = ranked_df["vendor_name"].tolist()[:2]
    result = executor["compare_vendors"]({"vendors": names})
    assert result["ok"] is True
    assert len(result["comparison"]) == 2
    json.dumps(result)


def test_generate_vendor_recommendation_full_bundle(ranked_df):
    executor = agent_tools.build_tool_executor(ranked_df, None, None)
    top_id = ranked_df.sort_values("overall_score", ascending=False).iloc[0]["vendor_id"]
    result = executor["generate_vendor_recommendation"]({"vendor": top_id, "rationale": "test"})
    assert result["found"] is True
    assert "due_diligence" in result and result["due_diligence"]
    assert result["confidence"] in {"High", "Medium", "Low"}
    assert result["requires_human_approval"] is True
    json.dumps(result)


def test_explain_anomaly_unknown_vendor(ranked_df):
    executor = agent_tools.build_tool_executor(ranked_df, None, None)
    result = executor["explain_anomaly"]({"vendor": "Totally Unknown Vendor Name Zzz"})
    assert result["found"] is False


def test_explain_anomaly_known_vendor(ranked_df):
    anomalous_row = ranked_df[ranked_df["is_anomalous"] == True].iloc[0]  # noqa: E712
    executor = agent_tools.build_tool_executor(ranked_df, None, None)
    result = executor["explain_anomaly"]({"vendor": anomalous_row["vendor_id"]})
    assert result["found"] is True
    assert result["is_anomalous"] is True
    assert result["drivers"]
    json.dumps(result)


def test_run_weight_sensitivity_unknown_feature(ranked_df):
    executor = agent_tools.build_tool_executor(ranked_df, None, None)
    result = executor["run_weight_sensitivity"]({"feature": "nonsense", "direction": "more"})
    assert result["ok"] is False


def test_run_weight_sensitivity_valid(ranked_df):
    executor = agent_tools.build_tool_executor(ranked_df, None, None)
    result = executor["run_weight_sensitivity"]({"feature": "price", "direction": "more"})
    assert result["ok"] is True
    assert "top_after" in result
    json.dumps(result)


def test_get_compliance_risks(ranked_df):
    executor = agent_tools.build_tool_executor(ranked_df, None, None)
    result = executor["get_compliance_risks"]({"threshold": 60})
    assert "vendors" in result
    json.dumps(result)


def test_retrieve_procurement_documents_no_kb(ranked_df):
    executor = agent_tools.build_tool_executor(ranked_df, None, None)
    result = executor["retrieve_procurement_documents"]({"query": "anything"})
    assert result["ok"] is False
    assert result["results"] == []


def test_retrieve_procurement_documents_with_results(ranked_df, monkeypatch):
    chunk = DocumentChunk(chunk_id="d1-aaa", doc_id="d1", filename="tender.pdf", page=3, text="Minimum 5 years experience required.")
    kb = KnowledgeBase()
    kb.chunks = [chunk]
    kb.index = "sentinel"
    monkeypatch.setattr(KnowledgeBase, "retrieve", lambda self, query, k=4: [RetrievedChunk(chunk=chunk, score=0.77)])

    executor = agent_tools.build_tool_executor(ranked_df, None, kb)
    result = executor["retrieve_procurement_documents"]({"query": "minimum experience"})
    assert result["ok"] is True
    assert result["results"][0]["filename"] == "tender.pdf"
    assert result["results"][0]["page"] == 3
    assert result["results"][0]["chunk_id"] == "d1-aaa"
    json.dumps(result)


def test_retrieve_procurement_documents_no_relevant_hits(ranked_df, monkeypatch):
    kb = KnowledgeBase()
    kb.chunks = [DocumentChunk(chunk_id="d1-aaa", doc_id="d1", filename="tender.pdf", page=1, text="irrelevant")]
    kb.index = "sentinel"
    monkeypatch.setattr(KnowledgeBase, "retrieve", lambda self, query, k=4: [])

    executor = agent_tools.build_tool_executor(ranked_df, None, kb)
    result = executor["retrieve_procurement_documents"]({"query": "something totally unrelated"})
    assert result["ok"] is True
    assert result["results"] == []
    assert "no relevant" in result["message"].lower()


def test_tool_execution_never_raises_on_bad_input(ranked_df):
    executor = agent_tools.build_tool_executor(ranked_df, None, None)
    result = executor["get_vendor_details"]({})  # missing required "vendor" key
    assert isinstance(result, dict)
    json.dumps(result)


def test_json_safe_handles_numpy_and_nan():
    import numpy as np
    import pandas as pd

    payload = {
        "a": np.int64(5),
        "b": np.float64(3.2),
        "c": np.bool_(True),
        "d": float("nan"),
        "e": pd.Series({"x": 1}),
    }
    safe = agent_tools._json_safe(payload)
    json.dumps(safe)
    assert safe["a"] == 5 and isinstance(safe["a"], int)
    assert safe["c"] is True
    assert safe["d"] is None
