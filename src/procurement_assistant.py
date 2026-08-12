"""Procurement assistant: intent detection, entity matching, conversation
context, and hybrid (Claude + deterministic) response orchestration.

The assistant NEVER computes scores or rankings itself — every fact comes
from src.analytics_tools. Claude (src.llm_service), when available, only
narrates a bundle that was already computed. Without an API key, the
deterministic formatting below is the entire answer.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

import pandas as pd

from src import analytics_tools as at
from src import dashboard as db
from src import llm_service
from src.feature_engineering import FEATURE_COLUMNS
from src.vendor_scoring import DEFAULT_WEIGHTS

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
ORDINAL_WORDS = {
    "first": 1, "top": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "last": -1, "bottom": -1, "lowest-ranked": -1,
}
FEATURE_KEYWORDS = {
    "price": "price_competitiveness", "cost": "price_competitiveness",
    "delivery": "delivery_reliability", "quality": "quality_score",
    "compliance": "compliance_score", "experience": "experience_score",
    "financial": "financial_stability_score", "finance": "financial_stability_score",
}
PRONOUN_PATTERN = re.compile(r"\b(it|its|it's|that vendor|this vendor|them|they)\b", re.I)

SUGGESTED_QUESTIONS = [
    "Who is the best overall vendor?",
    "Which vendors are anomalous?",
    "Compare the top 2 vendors",
    "Which vendors fail compliance thresholds?",
    "Give me an executive summary",
    "Who is the cheapest qualified vendor?",
]


@dataclass
class AssistantResponse:
    text: str
    recommended_vendor_id: str | None = None
    confidence: str | None = None
    comparison_df: pd.DataFrame | None = None
    evidence: dict | None = None
    source: str = "rule_based"
    warnings: list[str] = field(default_factory=list)


def new_conversation_context() -> dict:
    return {"last_intent": None, "last_vendor_ids": [], "last_recommended_vendor_id": None}


# --------------------------------------------------------------------------
# Entity matching (fuzzy vendor names, ids, rank references, pronouns)
# --------------------------------------------------------------------------

_PUNCT_RE = re.compile(r"[?.,!;:\"'()]")


def _best_match_score(name: str, text: str) -> float:
    name_l = name.lower().strip()
    text_l = text.lower()
    if not name_l:
        return 0.0
    if name_l in text_l:
        return 1.0
    name_words = name_l.split()
    text_words = _PUNCT_RE.sub(" ", text_l).split()
    if not name_words or not text_words:
        return 0.0
    best = 0.0
    for window_len in {max(1, len(name_words) - 1), len(name_words), len(name_words) + 1}:
        for i in range(0, max(1, len(text_words) - window_len + 1)):
            window = " ".join(text_words[i : i + window_len])
            ratio = difflib.SequenceMatcher(None, name_l, window).ratio()
            best = max(best, ratio)
    return best


def extract_vendor_mentions(text: str, df: pd.DataFrame, cutoff: float = 0.80, max_matches: int = 5) -> list[pd.Series]:
    """Fuzzy + exact matching of vendor names/ids mentioned anywhere in `text`."""
    text_l = text.lower()
    scored: list[tuple[float, pd.Series]] = []
    for _, row in df.iterrows():
        vid = str(row["vendor_id"]).lower()
        if re.search(rf"\b{re.escape(vid)}\b", text_l):
            scored.append((1.0, row))
            continue
        score = _best_match_score(str(row["vendor_name"]), text)
        if score >= cutoff:
            scored.append((score, row))
    scored.sort(key=lambda t: t[0], reverse=True)
    seen: set[str] = set()
    results = []
    for _score, row in scored:
        if row["vendor_id"] in seen:
            continue
        seen.add(row["vendor_id"])
        results.append(row)
        if len(results) >= max_matches:
            break
    return results


def find_vendor(df: pd.DataFrame, text: str) -> pd.Series | None:
    matches = extract_vendor_mentions(text, df, max_matches=1)
    return matches[0] if matches else None


def resolve_rank_reference(text: str) -> int | None:
    """'the second vendor' / 'rank 2' / 'the #2 vendor' -> 2.

    Deliberately does NOT fire on 'top N vendors' (e.g. 'top 2 vendors') — that's a
    request for a shortlist of N vendors (see extract_top_n), not a single rank-K
    reference, even though "top" is also in ORDINAL_WORDS as a synonym for rank 1
    when used alone (e.g. 'tell me about the top vendor').
    """
    ql = text.lower()
    if re.search(r"\btop\s+\d+\b", ql):
        return None
    m = re.search(r"\brank\s*#?\s*(\d+)\b", ql) or re.search(r"#\s*(\d+)\b", ql)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(\d+)(st|nd|rd|th)\s+(?:ranked\s+)?vendor\b", ql)
    if m:
        return int(m.group(1))
    for word, n in ORDINAL_WORDS.items():
        if re.search(rf"\b{word}\b", ql) and "vendor" in ql:
            return n
    return None


def has_pronoun(text: str) -> bool:
    return bool(PRONOUN_PATTERN.search(text))


def extract_top_n(text: str) -> int | None:
    ql = text.lower()
    m = re.search(r"top\s+(\d+)", ql)
    if m:
        return int(m.group(1))
    for word, n in NUMBER_WORDS.items():
        if re.search(rf"top\s+{word}\b", ql):
            return n
    if "shortlist" in ql:
        return 3
    return None


def parse_sensitivity_request(text: str) -> tuple[str | None, str]:
    ql = text.lower()
    feature = None
    for kw, col in FEATURE_KEYWORDS.items():
        if kw in ql:
            feature = col
            break
    direction = "more"
    if any(k in ql for k in ["less", "lower", "decrease", "unimportant", "matter less", "matters less"]):
        direction = "less"
    return feature, direction


def adjust_weight(weights: dict[str, float], feature: str, direction: str, delta: float = 0.15) -> dict[str, float]:
    adjusted = dict(weights)
    current = adjusted.get(feature, 0.0)
    adjusted[feature] = max(0.0, current + delta) if direction == "more" else max(0.0, current - delta)
    return adjusted


# --------------------------------------------------------------------------
# Intent detection
# --------------------------------------------------------------------------

INTENT_KEYWORDS = {
    "compare": ["compare", " vs ", "versus", "difference between", "how does", "which is better", "against"],
    "why_anomaly": ["why is", "why was", "why did", "reason for", "why flagged", "why anomal", "explain the anomaly", "explain why"],
    "sensitivity": ["what if", "sensitivity", "reweight", "matter more", "matters more", "matter less", "matters less", "more important", "less important"],
    "compliance_risk": ["compliance risk", "compliance issue", "non-compliant", "noncompliant", "fail compliance", "failing compliance", "compliance violat", "regulatory risk", "compliance threshold"],
    "executive_summary": ["executive summary", "summarize", "summary", "brief me", "overview", "tl;dr", "rundown", "give me the highlights"],
    "strengths_weaknesses": ["strength", "weakness", "pros and cons", "pros/cons", "good and bad", "what's good and bad"],
    "cheapest": ["cheapest", "lowest price", "least expensive", "best price", "most affordable", "lowest cost", "who is cheaper"],
    "safest": ["safest", "lowest risk", "least risky", "least risk", "most reliable", "most trustworthy", "safer"],
    "best_value": ["value for money", "best value", "bang for buck", "bang for the buck", "cost effective", "cost-effective", "most value"],
    "anomalous": ["anomal", "outlier", "suspicious", "red flag", "flagged", "unusual", "irregular"],
    "best_overall": ["best vendor", "best overall", "top vendor", "top pick", "who should we choose", "who should we pick",
                      "which vendor should we pick", "who do you recommend", "which vendor do you recommend",
                      "overall winner", "who is the best", "which one is the best", "recommend a vendor",
                      "strongest vendor", "who should we go with", "which vendor to choose", "pick a vendor",
                      "would you pick", "you pick", "you recommend", "you suggest", "your recommendation",
                      "your pick", "who wins", "top choice", "which vendor should i", "which vendor would"],
    "count": ["how many vendors", "number of vendors", "vendor count"],
}

# General catch-all for "which vendor/supplier should/would we pick/choose/select/use/go with"
# style phrasing, so paraphrases don't need to be individually enumerated above.
_BEST_OVERALL_PATTERN = re.compile(
    r"\b(which|what)\s+(vendor|supplier|one)\b[^.?!]*\b(should|would|do|did)\b[^.?!]*\b(we|you|i)\b[^.?!]*"
    r"\b(pick|choose|select|use|go with|award|recommend)\b"
    r"|\bwho\s+should\s+(we|you|i)\b[^.?!]*\b(pick|choose|select|use|go with|award)\b",
    re.I,
)


def detect_intent(question: str, n_vendor_mentions: int) -> str:
    ql = question.lower()
    if n_vendor_mentions >= 2 or any(k in ql for k in INTENT_KEYWORDS["compare"]):
        return "compare"
    for intent in ["why_anomaly", "sensitivity", "compliance_risk", "executive_summary", "strengths_weaknesses",
                    "cheapest", "safest", "best_value"]:
        if any(k in ql for k in INTENT_KEYWORDS[intent]):
            return intent
    if any(k in ql for k in INTENT_KEYWORDS["anomalous"]):
        return "anomalous"
    if extract_top_n(ql) is not None:
        return "top_n"
    if any(k in ql for k in INTENT_KEYWORDS["count"]):
        return "count"
    if any(k in ql for k in INTENT_KEYWORDS["best_overall"]) or _BEST_OVERALL_PATTERN.search(question):
        return "best_overall"
    if n_vendor_mentions == 1:
        return "vendor_specific"
    return "unsupported"


# --------------------------------------------------------------------------
# Deterministic text formatting (used as-is with no API key, or as a base
# for Claude to narrate when one is configured). Every recommendation-style
# answer is structured as Recommendation / Evidence / Trade-offs / Business
# Impact / Suggested Next Step so the assistant reads like an executive
# procurement adviser rather than a one-line lookup tool.
# --------------------------------------------------------------------------

def _markdown_table(headers: list[str], rows: list[list]) -> str:
    header_line = "| " + " | ".join(headers) + " |"
    sep_line = "| " + " | ".join(["---"] * len(headers)) + " |"
    body_lines = ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join([header_line, sep_line] + body_lines)


def _business_impact_line(bundle: dict) -> str:
    confidence = bundle.get("confidence", "Medium")
    if bundle.get("is_anomalous"):
        return "Proceeding without further due diligence carries elevated risk — an anomalous vendor profile can indicate data errors, financial distress, or non-standard bidding, any of which could disrupt delivery on this contract."
    if confidence == "High":
        return "This is a low-risk, well-differentiated choice — the scoring gap and clean compliance/anomaly profile support moving forward with standard due diligence."
    if confidence == "Medium":
        return "The recommendation is directionally sound but the margin over alternatives is not decisive — treat this as a strong starting point for negotiation rather than a foregone conclusion."
    return "Confidence is low — basing a decision on this recommendation alone carries meaningful risk; the flagged concerns should be resolved before this vendor is prioritized."


def format_recommendation_bundle(bundle: dict, heading: str) -> str:
    rec = bundle["recommended_vendor"]
    lines = [
        f"### Recommendation",
        f"**{heading}: {rec['vendor_name']} ({rec['vendor_id']})** — overall score {rec['overall_score']}/100, "
        f"rank #{rec['rank']}, confidence **{bundle['confidence']}**. {bundle['rationale']}",
    ]

    lines.append("### Evidence")
    lines.append("**Key reasons:** " + ("; ".join(bundle["key_reasons"]) if bundle["key_reasons"] else "no single feature stands out — this is the strongest option currently available."))
    lines.append(f"**Anomaly status:** {'Flagged as a statistical outlier — see why before proceeding.' if bundle['is_anomalous'] else 'No anomaly detected; feature profile is consistent with peer vendors.'}")
    if bundle["risks"]:
        lines.append("**Risks noted:** " + "; ".join(bundle["risks"]))

    lines.append("### Trade-offs")
    if bundle["trade_offs"]:
        lines.append("Compared with the next-best alternative, this vendor is weaker on: " + "; ".join(bundle["trade_offs"]))
    else:
        lines.append("No significant trade-offs versus the next-best alternative — this vendor leads or matches on every major criterion.")

    lines.append("### Business Impact")
    lines.append(_business_impact_line(bundle))

    lines.append("### Suggested Next Step")
    lines.append("Before finalizing: " + "; ".join(bundle["due_diligence"]))
    if bundle.get("had_missing_data"):
        lines.append("This vendor's source data had missing fields that were imputed — confirm real values before relying on the score.")
    lines.append("_This is a recommendation only. Final selection requires explicit human approval — no vendor is approved automatically._")
    return "\n\n".join(lines)


def _format_tender_recommendation(recommendation: dict) -> str:
    """Format the centralized, tender-aware recommendation (src.recommendation_engine)
    the same way format_recommendation_bundle formats a generic bundle, so the
    rule-based fallback answer matches every other page for the current tender."""
    lines = [
        "### Recommendation",
        f"**Recommended for {recommendation['tender_title']}: {recommendation['vendor_name']} ({recommendation['vendor_id']})** — "
        f"final score {recommendation['final_score']}/100, rank #{recommendation['rank']} of {recommendation['qualified_vendors']} "
        f"qualified vendor(s), confidence **{recommendation['confidence'] * 100:.0f}%**. {recommendation['reasoning']}",
    ]
    lines.append("### Evidence")
    lines.append("**Key reasons:** " + ("; ".join(recommendation["strengths"]) if recommendation["strengths"] else "no single factor stands out — this is the strongest eligible option currently available."))
    if recommendation["risks"]:
        lines.append("**Risks noted:** " + "; ".join(recommendation["risks"]))
    if not recommendation.get("vendor_id") and recommendation.get("closest_matches"):
        lines.append(
            "**Closest matches:** " + "; ".join(
                f"{c['vendor_name']} ({c['match_pct']:.0f}% requirement match)" for c in recommendation["closest_matches"]
            )
        )
    lines.append("### Score Breakdown")
    breakdown = recommendation.get("score_breakdown") or {}
    for label, vals in breakdown.items():
        lines.append(f"- {label}: {vals['points']}/{vals['max']}")
    lines.append("_This is a recommendation only. Final selection requires explicit human approval — no vendor is approved automatically._")
    return "\n\n".join(lines)


def _format_comparison(comparison_df: pd.DataFrame, evidence: dict) -> str:
    records = [info["record"] for info in evidence.values()]
    headers = ["Vendor", "Overall", "Rank", "Price", "Delivery", "Quality", "Compliance", "Experience", "Financial", "Anomalous"]
    rows = [
        [
            f"{r['vendor_name']} ({r['vendor_id']})",
            r["overall_score"],
            r["rank"],
            r["price_score"],
            r["delivery_score"],
            r["quality_score"],
            r["compliance_score"],
            r["experience_score"],
            r["financial_stability_score"],
            "Yes" if r["is_anomalous"] else "No",
        ]
        for r in records
    ]
    lines = ["### Comparison", _markdown_table(headers, rows)]

    if len(records) == 2:
        ordered = sorted(records, key=lambda r: r["overall_score"], reverse=True)
        leader_id = ordered[0]["vendor_id"]
        leader_row = [row for row in evidence.values() if row["record"]["vendor_id"] == leader_id][0]
        gap = round(ordered[0]["overall_score"] - ordered[1]["overall_score"], 1)
        lines.append("### Evidence")
        lines.append(f"**{ordered[0]['vendor_name']}** leads by {gap} overall points. Strengths: {', '.join(leader_row['strengths']) or 'none standout'}.")

    lines.append("### Trade-offs")
    for info in evidence.values():
        rec = info["record"]
        if info["risks"]:
            lines.append(f"- **{rec['vendor_name']}**: {', '.join(info['risks'])}")
    if not any(info["risks"] for info in evidence.values()):
        lines.append("No material risks identified for either vendor.")

    lines.append("### Business Impact")
    any_anomalous = any(info["record"]["is_anomalous"] for info in evidence.values())
    if any_anomalous:
        lines.append("At least one compared vendor is anomaly-flagged — factor that risk into the decision even if its headline score looks competitive.")
    else:
        lines.append("Neither vendor carries an anomaly flag, so the decision can reasonably rest on the score, trade-off, and due-diligence comparison above.")

    lines.append("### Suggested Next Step")
    lines.append("Review the full evidence panel for each vendor (expand below), then move the preferred vendor to Human Approval with your rationale.")
    return "\n\n".join(lines)


def _format_top_n(top_df: pd.DataFrame, n: int) -> str:
    headers = ["Rank", "Vendor", "Overall Score", "Anomalous"]
    rows = [
        [int(row["rank"]), f"{row['vendor_name']} ({row['vendor_id']})", f"{row['overall_score']:.1f}", "Yes" if bool(row.get("is_anomalous", False)) else "No"]
        for _, row in top_df.iterrows()
    ]
    lines = [f"### Top {n} Vendors", _markdown_table(headers, rows)]
    lines.append("### Business Impact")
    n_anom = int(top_df.get("is_anomalous", pd.Series(dtype=bool)).sum())
    if n_anom:
        lines.append(f"{n_anom} of the top {n} carry an anomaly flag — shortlisting them without further review risks carrying an unresolved data or compliance concern into the final decision.")
    else:
        lines.append(f"None of the top {n} are anomaly-flagged, so this shortlist can be taken forward for comparison with reasonable confidence.")
    lines.append("### Suggested Next Step")
    lines.append("Ask to compare any two of these vendors directly, or ask for the executive recommendation to see the single best pick with full justification.")
    return "\n\n".join(lines)


def _format_anomalous(flagged: pd.DataFrame) -> str:
    if flagged.empty:
        return (
            "### Direct Answer\nNo vendors are currently flagged as anomalous.\n\n"
            "### Business Impact\nThe evaluated vendor pool shows no statistical outliers under the current anomaly sensitivity setting — "
            "this does not guarantee every vendor is legitimate, only that none stands out as unusual relative to the others."
        )
    headers = ["Vendor", "Overall Score", "Compliance", "Financial Stability"]
    rows = [[f"{row['vendor_name']} ({row['vendor_id']})", f"{row['overall_score']:.1f}", f"{row['compliance_score']:.0f}", f"{row['financial_stability_score']:.0f}"] for _, row in flagged.iterrows()]
    lines = [
        f"### Direct Answer\n{len(flagged)} vendor(s) are flagged as statistical outliers versus their peers:",
        _markdown_table(headers, rows),
        "### Why this matters\nAn anomaly flag means this vendor's feature profile (price, delivery, compliance, etc.) differs "
        "significantly from the rest of the evaluated pool — it can indicate unusually favorable terms that don't hold up, "
        "incomplete or incorrect submitted data, or genuine outlier performance. It is a prompt to investigate, not a verdict.",
        "### Suggested Next Step",
        "Ask 'why is <vendor> flagged?' for any of these to see the specific features driving the flag before deciding whether to shortlist or exclude them.",
    ]
    return "\n\n".join(lines)


def _format_anomaly_explanation(info: dict) -> str:
    if not info.get("found"):
        return "I couldn't find that vendor in the current evaluation. Check the spelling or try the vendor ID."
    if not info["is_anomalous"]:
        return (
            f"### Direct Answer\n**{info['vendor_name']}** is not flagged as anomalous.\n\n"
            "### Why\nIts feature profile (price, delivery, quality, compliance, experience, financial stability) falls within "
            "the normal range for this vendor set — no combination of features stood out as statistically unusual to the anomaly model."
        )
    headers = ["Feature", "This Vendor", "Peer Average", "Direction", "Z-score"]
    rows = [
        [at.FEATURE_LABELS.get(d["feature"], d["feature"]), d["value"], d["peer_average"], d["direction"], d["z_score"]]
        for d in info["drivers"]
    ]
    lines = [
        f"### Direct Answer\n**{info['vendor_name']} ({info['vendor_id']})** is flagged as anomalous (anomaly score {info['anomaly_score']}).",
        "### Why",
        "The Isolation Forest model flags vendors whose combination of feature scores is statistically unusual relative to the rest "
        "of the evaluated pool. For this vendor, the biggest contributors were:",
        _markdown_table(headers, rows),
        "### Business Impact",
        "This does not automatically disqualify the vendor — it means the profile deviates enough from peers to warrant a closer look "
        "before relying on the headline score alone.",
        "### Suggested Next Step",
        "Independently verify the flagged figures (e.g. request supporting documentation for pricing or delivery history) before "
        "shortlisting this vendor.",
    ]
    return "\n\n".join(lines)


def _format_strengths_weaknesses(info: dict) -> str:
    if not info.get("found"):
        return "I couldn't find that vendor in the current evaluation. Check the spelling or try the vendor ID."
    rec = info["record"]
    lines = [
        f"### Direct Answer\n**{rec['vendor_name']} ({rec['vendor_id']})** — overall score {rec['overall_score']}/100, rank #{rec['rank']}, "
        f"confidence **{info['confidence']}**.",
        "### Strengths\n" + ("\n".join(f"- {s}" for s in info["strengths"]) if info["strengths"] else "None identified above the strength threshold."),
        "### Weaknesses\n" + ("\n".join(f"- {r}" for r in info["risks"]) if info["risks"] else "None identified below the risk threshold."),
        f"### Business Impact\nRecommendation category: **{info['recommendation_category']}**. "
        + ("This vendor carries an anomaly flag, so any weaknesses above should be treated as priority follow-ups." if rec["is_anomalous"] else "No anomaly flag is present, so weaknesses here are normal negotiation points rather than red flags."),
        "### Suggested Next Step\n" + "; ".join(info["due_diligence"]),
    ]
    return "\n\n".join(lines)


def _format_compliance_risks(risky: pd.DataFrame, threshold: float) -> str:
    if risky.empty:
        return (
            f"### Direct Answer\nNo vendors fall below the compliance-score threshold of {threshold}/100.\n\n"
            "### Why this matters\nCompliance score reflects certifications held and recorded violations — every evaluated vendor "
            "currently clears the bar, which reduces regulatory and contractual risk across the shortlist."
        )
    headers = ["Vendor", "Compliance Score", "Recorded Violations", "Anomalous"]
    rows = [
        [f"{row['vendor_name']} ({row['vendor_id']})", f"{row['compliance_score']:.0f}", int(row.get("compliance_violations", 0)), "Yes" if bool(row.get("is_anomalous", False)) else "No"]
        for _, row in risky.iterrows()
    ]
    lines = [
        f"### Direct Answer\n{len(risky)} vendor(s) fall below the compliance threshold of {threshold}/100:",
        _markdown_table(headers, rows),
        "### Why this matters\nCompliance score combines certifications held against recorded violations. A low score means the vendor "
        "either lacks standard industry certifications or has a documented history of violations — both raise the risk of contract "
        "non-conformance, audit findings, or regulatory exposure if this vendor is selected.",
        "### Suggested Next Step",
        "For any vendor on this list you're still considering, request updated compliance certifications and a corrective-action "
        "history before proceeding.",
    ]
    return "\n\n".join(lines)


def _format_sensitivity(result: dict, feature: str, direction: str) -> str:
    label = at.FEATURE_LABELS.get(feature, feature)
    top_before = result["top_before"]
    top_after = result["top_after"]
    lines = ["### Direct Answer"]
    if result["top_changed"]:
        lines.append(f"If **{label}** matters {direction}, the top vendor changes from **{top_before}** to **{top_after}**.")
    else:
        lines.append(f"Even weighting **{label}** {direction}, **{top_after}** remains the top vendor.")

    movers = result["comparison"]
    if "rank_change" in movers.columns:
        moved = movers[movers["rank_change"].abs() >= 1].head(8)
        if not moved.empty:
            headers = ["Vendor", "Old Rank", "New Rank"]
            rows = [[r["vendor_name"], int(r["old_rank"]), int(r["new_rank"])] for _, r in moved.iterrows()]
            lines.append("### Evidence\nRank changes under the adjusted weighting:")
            lines.append(_markdown_table(headers, rows))
        else:
            lines.append("### Evidence\nNo vendor's rank moves under this adjustment — the current ranking is robust to this weight change.")

    lines.append("### Business Impact")
    lines.append(
        "A ranking that changes with the weighting is telling you the decision is sensitive to how much this criterion matters — "
        "worth resolving that priority explicitly with stakeholders before finalizing."
        if result["top_changed"]
        else "The ranking is stable under this weighting change, which is a good sign the recommendation isn't an artifact of how the criteria happen to be weighted."
    )
    lines.append("### Suggested Next Step\nAdjust the sidebar weight sliders to make this change permanent if it reflects the tender's actual priorities, then re-run the recommendation.")
    return "\n\n".join(lines)


def _format_executive_summary(summary: dict) -> str:
    rec = summary["recommended_vendor"]
    lines = [
        f"### Recommendation\n{summary['vendor_count']} vendors evaluated. Recommended: **{rec['vendor_name']} ({rec['vendor_id']})** "
        f"— overall score {rec['overall_score']}/100, confidence **{summary['confidence']}**.",
        "### Evidence\n**Key reasons:** " + "; ".join(summary["key_reasons"]),
    ]
    if summary["trade_offs"]:
        lines.append("### Trade-offs\n" + "; ".join(summary["trade_offs"]))
    lines.append(
        f"### Business Impact\n{summary['anomalous_count']} vendor(s) flagged as anomalous; "
        f"{summary['compliance_risk_count']} vendor(s) below the compliance threshold across the full pool. "
        + ("These should be excluded or investigated before award." if (summary["anomalous_count"] or summary["compliance_risk_count"]) else "The overall pool carries low structural risk.")
    )
    lines.append("### Suggested Next Step\n" + "; ".join(summary["due_diligence"]))
    lines.append("_This summary is advisory — final vendor selection requires explicit human approval._")
    return "\n\n".join(lines)


def _format_vendor_detail(info: dict) -> str:
    if not info.get("found"):
        return "I couldn't find that vendor in the current evaluation. Check the spelling or try the vendor ID."
    rec = info["record"]
    headers = ["Price", "Delivery", "Quality", "Compliance", "Experience", "Financial"]
    rows = [[rec["price_score"], rec["delivery_score"], rec["quality_score"], rec["compliance_score"], rec["experience_score"], rec["financial_stability_score"]]]
    lines = [
        f"### Direct Answer\n**{rec['vendor_name']} ({rec['vendor_id']})** — overall score {rec['overall_score']}/100, rank #{rec['rank']}, "
        f"recommendation category **{info['recommendation_category']}** (confidence: {info['confidence']}).",
        "### Evidence\n" + _markdown_table(headers, rows),
        f"**Anomaly status:** {'Flagged as a statistical outlier' if rec['is_anomalous'] else 'Not flagged — consistent with peer vendors'} (anomaly score {rec['anomaly_score']}).",
        "### Strengths\n" + ("\n".join(f"- {s}" for s in info["strengths"]) if info["strengths"] else "None above the strength threshold."),
        "### Risks\n" + ("\n".join(f"- {r}" for r in info["risks"]) if info["risks"] else "None below the risk threshold."),
        "### Suggested Next Step\n" + "; ".join(info["due_diligence"]),
    ]
    if rec["had_missing_data"]:
        lines.append("Note: this vendor's source data had missing fields that were imputed — treat the score as approximate.")
    return "\n\n".join(lines)


def _fallback_help_text() -> str:
    return (
        "I can help with vendor rankings, scores, anomalies, comparisons, compliance risk, and recommendations — and I'll always "
        "answer with the evidence and trade-offs behind it, not just a single number. A few things you can ask:\n\n"
        + "\n".join(f"- {q}" for q in SUGGESTED_QUESTIONS)
        + "\n\nYou can also ask follow-ups like \"why?\", \"what are its risks?\", or \"compare it with the second vendor.\""
    )


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def handle(
    question: str,
    df: pd.DataFrame,
    context: dict | None = None,
    current_weights: dict[str, float] | None = None,
    api_key: str | None = None,
    history: list[tuple[str, str]] | None = None,
    recommendation: dict | None = None,
) -> tuple[AssistantResponse, dict]:
    context = dict(context) if context else new_conversation_context()
    q = question.strip()
    if not q:
        return AssistantResponse(text="Please ask a question about the vendors."), context

    mentions = extract_vendor_mentions(q, df)

    rank_ref = resolve_rank_reference(q)
    if rank_ref is not None and "rank" in df.columns:
        rank_row = df[df["rank"] == rank_ref] if rank_ref > 0 else df[df["rank"] == df["rank"].max()]
        if not rank_row.empty:
            already = {m["vendor_id"] for m in mentions}
            if rank_row.iloc[0]["vendor_id"] not in already:
                mentions = [rank_row.iloc[0]] + mentions

    if not mentions and has_pronoun(q) and context.get("last_vendor_ids"):
        prior = df[df["vendor_id"] == context["last_vendor_ids"][0]]
        if not prior.empty:
            mentions = [prior.iloc[0]]

    n_mentions = len(mentions)
    intent = detect_intent(q, n_mentions)

    # bare "why?" follow-up reuses the last turn's intent/vendor
    if intent == "unsupported" and re.match(r"^why\W*$", q.strip().lower()):
        if context.get("last_vendor_ids"):
            prior = df[df["vendor_id"] == context["last_vendor_ids"][0]]
            if not prior.empty:
                mentions = [prior.iloc[0]]
                intent = "why_anomaly" if bool(prior.iloc[0].get("is_anomalous", False)) else "vendor_specific"

    warnings: list[str] = []
    bundle: dict | None = None
    comparison_df: pd.DataFrame | None = None
    recommended_id: str | None = None
    confidence: str | None = None
    text = ""

    if intent == "compare":
        ids = [m["vendor_id"] for m in mentions[:2]]
        if len(ids) < 2:
            # "compare the top N vendors" with no vendor named explicitly -> use the ranking itself.
            top_n = extract_top_n(q)
            if top_n:
                for vid in at.get_top_vendors(df, top_n)["vendor_id"].tolist():
                    if vid not in ids:
                        ids.append(vid)

        if len(ids) == 0:
            text = "Tell me which two vendors to compare — by name, ID, or 'the top N vendors'."
        elif len(ids) == 1:
            text = f"I found {mentions[0]['vendor_name']} — which other vendor should I compare it with?"
        else:
            comparison_df = at.compare_vendors(df, ids)
            evidence = {vid: at.explain_vendor(df, vid) for vid in ids}
            bundle = {"comparison": comparison_df.to_dict(orient="records"), "details": evidence}
            text = _format_comparison(comparison_df, evidence)

    elif intent == "why_anomaly":
        if not mentions:
            text = "Which vendor would you like me to explain the anomaly flag for?"
        else:
            bundle = at.explain_anomaly(df, mentions[0]["vendor_id"])
            text = _format_anomaly_explanation(bundle)

    elif intent == "strengths_weaknesses":
        if not mentions:
            text = "Which vendor's strengths and weaknesses would you like to see?"
        else:
            bundle = at.explain_vendor(df, mentions[0]["vendor_id"])
            text = _format_strengths_weaknesses(bundle)
            confidence = bundle.get("confidence")

    elif intent == "compliance_risk":
        risky = at.get_compliance_risks(df)
        comparison_df = risky if not risky.empty else None
        bundle = {"compliance_risks": risky.to_dict(orient="records")}
        text = _format_compliance_risks(risky, at.COMPLIANCE_RISK_THRESHOLD)

    elif intent == "sensitivity":
        feature, direction = parse_sensitivity_request(q)
        if feature is None:
            text = "Tell me which criterion matters more or less — e.g. 'what if price mattered more?'"
        else:
            base_weights = current_weights or DEFAULT_WEIGHTS
            adjusted = adjust_weight(base_weights, feature, direction)
            result = at.run_weight_sensitivity(df, adjusted)
            comparison_df = result["comparison"]
            bundle = {"top_before": result["top_before"], "top_after": result["top_after"], "top_changed": result["top_changed"]}
            text = _format_sensitivity(result, feature, direction)

    elif intent == "executive_summary":
        bundle = at.build_executive_summary(df)
        text = _format_executive_summary(bundle)
        recommended_id = bundle["recommended_vendor"]["vendor_id"]
        confidence = bundle["confidence"]

    elif intent == "cheapest":
        row, fallback_used = at.get_cheapest_qualified_vendor(df)
        if fallback_used:
            warnings.append("No vendor cleared the quality/anomaly bar, so this is the cheapest among all vendors — review carefully.")
        bundle = at.build_recommendation_bundle(df, row, "Lowest quoted price among qualified, non-anomalous vendors.")
        text = format_recommendation_bundle(bundle, "Cheapest qualified vendor")
        recommended_id, confidence = row["vendor_id"], bundle["confidence"]

    elif intent == "safest":
        row, fallback_used = at.get_safest_vendor(df)
        if fallback_used:
            warnings.append("Every vendor is flagged anomalous, so this is the safest by score alone — review carefully.")
        bundle = at.build_recommendation_bundle(df, row, "Strongest compliance, financial-stability, and quality profile.")
        text = format_recommendation_bundle(bundle, "Safest vendor")
        recommended_id, confidence = row["vendor_id"], bundle["confidence"]

    elif intent == "best_value":
        row, fallback_used = at.get_best_value_vendor(df)
        if fallback_used:
            warnings.append("Every vendor is flagged anomalous, so this is the best value by score alone — review carefully.")
        bundle = at.build_recommendation_bundle(df, row, "Best quality delivered relative to price among non-anomalous vendors.")
        text = format_recommendation_bundle(bundle, "Best value-for-money vendor")
        recommended_id, confidence = row["vendor_id"], bundle["confidence"]

    elif intent == "best_overall":
        if recommendation and recommendation.get("vendor_id"):
            # Prefer the centralized, tender-aware recommendation (src.recommendation_engine)
            # over a generic highest-overall-score lookup, so the answer matches every other
            # page's recommended vendor for the currently selected tender.
            text = _format_tender_recommendation(recommendation)
            recommended_id = recommendation["vendor_id"]
            confidence = "High" if recommendation["confidence"] >= 0.7 else ("Medium" if recommendation["confidence"] >= 0.4 else "Low")
            bundle = {k: v for k, v in recommendation.items() if k != "scored_pool_df"}
        else:
            row = df.sort_values("overall_score", ascending=False).iloc[0]
            bundle = at.build_recommendation_bundle(df, row, "Highest overall weighted score across all evaluation criteria.")
            text = format_recommendation_bundle(bundle, "Best overall vendor")
            recommended_id, confidence = row["vendor_id"], bundle["confidence"]

    elif intent == "top_n":
        n = extract_top_n(q) or 3
        top_df = at.get_top_vendors(df, n)
        comparison_df = top_df[["rank", "vendor_id", "vendor_name", "overall_score", "is_anomalous"]]
        bundle = {"top_vendors": [at.vendor_record(r) for _, r in top_df.iterrows()]}
        text = _format_top_n(top_df, n)

    elif intent == "anomalous":
        flagged = df[df.get("is_anomalous", False) == True]  # noqa: E712
        comparison_df = flagged if not flagged.empty else None
        bundle = {"anomalous_vendors": [at.vendor_record(r) for _, r in flagged.iterrows()]}
        text = _format_anomalous(flagged)

    elif intent == "count":
        n_anom = int(df.get("is_anomalous", pd.Series(dtype=bool)).sum())
        text = f"There are {len(df)} vendors evaluated, {n_anom} of them flagged as anomalous."
        bundle = {"vendor_count": len(df), "anomalous_count": n_anom}

    elif intent == "vendor_specific":
        bundle = at.explain_vendor(df, mentions[0]["vendor_id"])
        text = _format_vendor_detail(bundle)
        confidence = bundle.get("confidence")

    else:
        text = _fallback_help_text()

    source = "rule_based"
    if bundle is not None:
        claude_text = llm_service.interpret(q, bundle, history=history, api_key=api_key)
        if claude_text:
            text = claude_text
            source = "claude"

    context["last_intent"] = intent
    if mentions:
        context["last_vendor_ids"] = [m["vendor_id"] for m in mentions]
    if recommended_id:
        context["last_recommended_vendor_id"] = recommended_id

    return (
        AssistantResponse(
            text=text,
            recommended_vendor_id=recommended_id,
            confidence=confidence,
            comparison_df=comparison_df,
            evidence=bundle,
            source=source,
            warnings=warnings,
        ),
        context,
    )
