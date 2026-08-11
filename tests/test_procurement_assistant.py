"""Focused tests for the procurement assistant: recommendations, comparisons,
anomaly explanations, fuzzy vendor matching, follow-ups, and the no-API-key
fallback path. All tests run with ANTHROPIC_API_KEY unset (see conftest.py),
so every response here is produced by the deterministic rule-based layer.
"""
from src import procurement_assistant as pa


def _ask(ranked_df, question, context=None, weights=None):
    return pa.handle(question, ranked_df, context=context, current_weights=weights)


# --------------------------------------------------------------------------
# Recommendation questions — must never be "just the top score"
# --------------------------------------------------------------------------

def test_best_overall_recommendation_has_full_structure(ranked_df):
    response, _ = _ask(ranked_df, "Who should we go with overall?")
    assert response.recommended_vendor_id is not None
    assert response.confidence in {"High", "Medium", "Low"}
    assert response.evidence is not None
    assert "confidence" in response.text.lower()
    assert "suggested next step" in response.text.lower()
    assert "human approval" in response.text.lower()
    assert response.evidence["is_anomalous"] in (True, False)


def test_cheapest_vendor_recommendation_is_full_bundle(ranked_df):
    response, _ = _ask(ranked_df, "who is the cheapest vendor?")
    assert response.recommended_vendor_id is not None
    assert "suggested next step" in response.text.lower()
    assert response.evidence["requires_human_approval"] is True


def test_safest_vendor_recommendation(ranked_df):
    response, _ = _ask(ranked_df, "which vendor is safest?")
    assert response.recommended_vendor_id is not None


def test_best_value_recommendation(ranked_df):
    response, _ = _ask(ranked_df, "who offers the best value for money?")
    assert response.recommended_vendor_id is not None


def test_paraphrased_recommendation_question_still_resolves(ranked_df):
    """Different wording, same intent — this is the core ask of this feature."""
    response, _ = _ask(ranked_df, "which vendor would you pick for this tender?")
    assert response.recommended_vendor_id is not None
    top_by_score = ranked_df.sort_values("overall_score", ascending=False).iloc[0]["vendor_id"]
    assert response.recommended_vendor_id == top_by_score


def test_unrecognized_phrasing_falls_back_gracefully(ranked_df):
    response, _ = _ask(ranked_df, "gibberish about nothing in particular")
    assert response.text
    assert response.recommended_vendor_id is None


# --------------------------------------------------------------------------
# Vendor comparison
# --------------------------------------------------------------------------

def test_compare_two_named_vendors(ranked_df):
    names = ranked_df.sort_values("overall_score", ascending=False)["vendor_name"].tolist()[:2]
    response, _ = _ask(ranked_df, f"Compare {names[0]} and {names[1]}.")
    assert response.comparison_df is not None
    assert len(response.comparison_df) == 2
    assert set(response.comparison_df["vendor_name"]) == set(names)


def test_compare_with_only_one_vendor_asks_for_clarification(ranked_df):
    top_name = ranked_df.sort_values("overall_score", ascending=False).iloc[0]["vendor_name"]
    response, _ = _ask(ranked_df, f"compare {top_name} to another vendor")
    assert response.text
    assert response.comparison_df is None


# --------------------------------------------------------------------------
# Anomaly explanation
# --------------------------------------------------------------------------

def test_why_is_vendor_anomalous(ranked_df):
    anomalous = ranked_df[ranked_df["is_anomalous"] == True]  # noqa: E712
    assert not anomalous.empty, "fixture expected at least one anomalous vendor in sample data"
    vendor_name = anomalous.iloc[0]["vendor_name"]
    response, _ = _ask(ranked_df, f"why is {vendor_name} flagged as anomalous?")
    assert response.evidence is not None
    assert response.evidence.get("is_anomalous") is True
    assert "drivers" in response.evidence
    assert len(response.evidence["drivers"]) > 0


def test_non_anomalous_vendor_explains_it_is_not_flagged(ranked_df):
    normal = ranked_df[ranked_df["is_anomalous"] == False]  # noqa: E712
    vendor_name = normal.iloc[0]["vendor_name"]
    response, _ = _ask(ranked_df, f"why is {vendor_name} flagged as anomalous?")
    assert response.evidence.get("is_anomalous") is False
    assert "not flagged" in response.text.lower()


def test_anomalous_vendors_listing(ranked_df):
    response, _ = _ask(ranked_df, "which vendors are anomalous?")
    assert response.evidence is not None
    assert "anomalous_vendors" in response.evidence


# --------------------------------------------------------------------------
# Fuzzy vendor-name matching
# --------------------------------------------------------------------------

def test_fuzzy_match_misspelled_vendor_name(ranked_df):
    correct_name = "Everest Logistics Partners"
    assert correct_name in ranked_df["vendor_name"].values
    match = pa.find_vendor(ranked_df, "Evrest Logistics Partners")
    assert match is not None
    assert match["vendor_name"] == correct_name


def test_fuzzy_match_within_full_sentence(ranked_df):
    matches = pa.extract_vendor_mentions("tell me about Keystone Electronic please", ranked_df)
    assert matches
    assert matches[0]["vendor_name"] == "Keystone Electronics"


def test_vendor_specific_question_with_typo_resolves_correct_vendor(ranked_df):
    response, _ = _ask(ranked_df, "What is the score for Evrest Logistics Partners?")
    assert "Everest Logistics Partners" in response.text


def test_no_false_positive_on_unrelated_text(ranked_df):
    matches = pa.extract_vendor_mentions("what is the weather forecast tomorrow", ranked_df)
    assert matches == []


# --------------------------------------------------------------------------
# Follow-up questions (conversation context)
# --------------------------------------------------------------------------

def test_followup_bare_why_after_anomaly_question(ranked_df):
    anomalous_row = ranked_df[ranked_df["is_anomalous"] == True].iloc[0]  # noqa: E712
    _first, context = _ask(ranked_df, f"why is {anomalous_row['vendor_name']} flagged?")
    assert context["last_vendor_ids"][0] == anomalous_row["vendor_id"]

    second, _context2 = _ask(ranked_df, "why?", context=context)
    assert second.text
    assert second.evidence is not None
    assert second.evidence.get("vendor_id") == anomalous_row["vendor_id"]


def test_followup_pronoun_reference_resolves_to_prior_vendor(ranked_df):
    top_row = ranked_df.sort_values("overall_score", ascending=False).iloc[0]
    _first, context = _ask(ranked_df, f"tell me about {top_row['vendor_name']}")
    assert context["last_vendor_ids"][0] == top_row["vendor_id"]

    second, _context2 = _ask(ranked_df, "what are its risks?", context=context)
    assert second.evidence is not None
    assert second.evidence.get("record", {}).get("vendor_id") == top_row["vendor_id"]


def test_followup_ordinal_rank_reference(ranked_df):
    second_ranked = ranked_df[ranked_df["rank"] == 2].iloc[0]
    response, _ = _ask(ranked_df, "tell me about the second vendor")
    assert response.evidence is not None
    assert response.evidence.get("record", {}).get("vendor_id") == second_ranked["vendor_id"]


# --------------------------------------------------------------------------
# No-API-key fallback
# --------------------------------------------------------------------------

def test_no_api_key_still_answers_with_rule_based_source(ranked_df):
    response, _ = _ask(ranked_df, "who is the best overall vendor?")
    assert response.source == "rule_based"
    assert response.recommended_vendor_id is not None
    assert response.text


def test_llm_service_interpret_returns_none_without_key():
    from src import llm_service

    assert llm_service.get_api_key() is None
    assert llm_service.interpret("any question", {"a": 1}) is None


def test_comparison_still_works_without_api_key(ranked_df):
    names = ranked_df["vendor_name"].tolist()[:2]
    response, _ = _ask(ranked_df, f"{names[0]} vs {names[1]}")
    assert response.source == "rule_based"
    assert response.comparison_df is not None
