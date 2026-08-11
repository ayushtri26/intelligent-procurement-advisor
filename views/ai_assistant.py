"""AI Assistant — the Claude-powered procurement agent chat, with a rule-based
fallback. Logic is moved here unchanged from the previous single-page
version (src/agent.py, src/agent_tools.py, src/procurement_assistant.py are
untouched by this refactor). This page owns the single st.chat_input in the
app."""
import json

import streamlit as st

from src import agent, notifications, procurement_assistant as pa, rag, ui_components
from src.llm_service import get_api_key

MIN_SUPPLEMENTARY_RELEVANCE = 0.15

AGENT_ERROR_MESSAGES = {
    "no_api_key": "No ANTHROPIC_API_KEY configured.",
    "client_unavailable": "The Anthropic client could not be initialized (check the `anthropic` package and API key).",
    "max_iterations": "The agent used too many tool calls without reaching an answer.",
}

ranked_df = st.session_state.ranked_df
api_key_present = st.session_state.api_key_present
current_weights = st.session_state.current_weights


def _describe_agent_error(error_code):
    if error_code in AGENT_ERROR_MESSAGES:
        return AGENT_ERROR_MESSAGES[error_code]
    return f"Claude agent error: {error_code}" if error_code else "Unknown agent error."


def _supplementary_doc_passages(question):
    kb = st.session_state.knowledge_base
    if not kb.is_ready:
        return []
    retrieved = kb.retrieve(question, k=3)
    return [
        {"filename": r.chunk.filename, "page": r.chunk.page, "chunk_id": r.chunk.chunk_id, "text": r.chunk.text, "relevance_score": round(r.score, 3)}
        for r in retrieved if r.score >= MIN_SUPPLEMENTARY_RELEVANCE
    ]


st.title("AI Assistant")
if api_key_present:
    st.caption("Claude decides which analytics and document-retrieval tools to call, then explains the verified results as an executive procurement adviser would.")
else:
    st.info("Full LLM-powered reasoning requires `ANTHROPIC_API_KEY` to be configured. The deterministic analytical assistant and document search below remain fully functional.")

st.write("**Suggested questions:**")
suggestion_cols = st.columns(3)
pending_question = None
for i, sq in enumerate(pa.SUGGESTED_QUESTIONS):
    if suggestion_cols[i % 3].button(sq, key=f"suggest_{i}", use_container_width=True):
        pending_question = sq

if st.button("Clear conversation", icon=":material/delete:"):
    st.session_state.chat_history = []
    st.session_state.assistant_context = pa.new_conversation_context()
    st.rerun()

for entry in st.session_state.chat_history:
    with st.chat_message(entry["role"]):
        st.markdown(entry["text"])
        if entry["role"] != "assistant":
            continue

        if entry.get("mode") == "agent":
            if entry.get("sources"):
                with st.expander(f"Sources ({len(entry['sources'])})"):
                    for src in entry["sources"]:
                        page_part = f", p.{src['page']}" if src.get("page") else ""
                        st.markdown(f"**{src['filename']}{page_part}** · `{src['chunk_id']}` · relevance {src.get('relevance_score', 0):.2f}")
                        st.caption(src["text"][:400] + ("…" if len(src["text"]) > 400 else ""))
            if entry.get("tool_calls"):
                with st.expander(f"Tools used ({len(entry['tool_calls'])})"):
                    for call in entry["tool_calls"]:
                        st.code(f"{call['tool']}({json.dumps(call['input'], default=str)})", language="text")
            st.caption(f"Answered by the Claude agent ({len(entry.get('tool_calls', []))} tool call(s)).")
            continue

        if entry.get("recommended_vendor_id"):
            rec_row = ranked_df.loc[ranked_df["vendor_id"] == entry["recommended_vendor_id"]]
            if not rec_row.empty:
                r = rec_row.iloc[0]
                st.info(f"**Recommended: {r['vendor_name']} ({r['vendor_id']})** — confidence: {entry.get('confidence') or 'N/A'}")
        if entry.get("comparison_df") is not None and not entry["comparison_df"].empty:
            ui_components.data_table(entry["comparison_df"])
        for w in entry.get("warnings") or []:
            st.warning(w)
        if entry.get("fallback_reason"):
            st.caption(f"Claude agent unavailable ({entry['fallback_reason']}) — showing rule-based analysis instead.")
        if entry.get("evidence"):
            with st.expander("Evidence, risks & due diligence"):
                try:
                    st.code(json.dumps(entry["evidence"], indent=2, default=str), language="json")
                except Exception:
                    st.write(entry["evidence"])
        if entry.get("doc_passages"):
            with st.expander(f"Related document passages found ({len(entry['doc_passages'])})"):
                for src in entry["doc_passages"]:
                    page_part = f", p.{src['page']}" if src.get("page") else ""
                    st.markdown(f"**{src['filename']}{page_part}** · `{src['chunk_id']}` · relevance {src['relevance_score']:.2f}")
                    st.caption(src["text"][:400] + ("…" if len(src["text"]) > 400 else ""))
        st.caption("Rule-based analysis (deterministic, no LLM involved).")

user_question = st.chat_input("Ask about vendors, documents, or both...")
question_to_process = pending_question or user_question
if question_to_process:
    st.session_state.chat_history.append({"role": "user", "text": question_to_process})
    history_pairs = [(e["role"], e["text"]) for e in st.session_state.chat_history[-8:]]

    agent_result = None
    recommended_name_for_notif = None
    if api_key_present:
        with st.spinner("Thinking..."):
            agent_result = agent.run_agent(
                question_to_process, ranked_df, st.session_state.knowledge_base,
                current_weights=current_weights, history=history_pairs,
                api_key=get_api_key(), max_iterations=st.session_state.ai_max_iterations_override or agent.MAX_ITERATIONS,
            )

    if agent_result and agent_result["ok"]:
        st.session_state.chat_history.append({
            "role": "assistant", "mode": "agent", "text": agent_result["text"],
            "tool_calls": agent_result["tool_calls"], "sources": agent_result["sources"],
        })
        recommended_name_for_notif = st.session_state.top_bundle["recommended_vendor"]["vendor_name"]
    else:
        response, updated_context = pa.handle(
            question_to_process, ranked_df, context=st.session_state.assistant_context,
            current_weights=current_weights, api_key=None, history=history_pairs,
        )
        st.session_state.assistant_context = updated_context
        entry = {
            "role": "assistant", "mode": "rule_based", "text": response.text,
            "recommended_vendor_id": response.recommended_vendor_id, "confidence": response.confidence,
            "comparison_df": response.comparison_df, "evidence": response.evidence, "warnings": response.warnings,
            "doc_passages": _supplementary_doc_passages(question_to_process),
        }
        if agent_result is not None:
            entry["fallback_reason"] = _describe_agent_error(agent_result["error"])
        st.session_state.chat_history.append(entry)
        if response.recommended_vendor_id:
            match = ranked_df[ranked_df["vendor_id"] == response.recommended_vendor_id]
            if not match.empty:
                recommended_name_for_notif = match.iloc[0]["vendor_name"]

    if recommended_name_for_notif and st.session_state.notification_settings.get("AI Recommendation Ready", True):
        notifications.notify_ai_recommendation_ready(recommended_name_for_notif)
    st.rerun()
