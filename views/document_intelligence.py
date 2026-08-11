"""Document Intelligence — the local RAG knowledge base (src/rag.py,
unchanged): upload, extraction, chunking, embedding, FAISS indexing, and a
searchable index of what's been ingested."""
from datetime import datetime

import streamlit as st

from src import audit, dashboard as db, rag, ui_components

st.title("Document Intelligence")
st.caption("Upload tender specs, contracts, or policy documents (PDF, TXT, DOCX) for the AI Assistant to search and cite.")

uploaded_docs = st.file_uploader("Upload procurement documents", type=["pdf", "txt", "docx"], accept_multiple_files=True, key="doc_uploader")
if st.button("Build / Refresh Knowledge Base", icon=":material/library_add:"):
    if not uploaded_docs:
        st.warning("Upload at least one document first.")
    else:
        with st.spinner("Extracting text and building the local FAISS index..."):
            documents, extraction_errors = [], []
            for f in uploaded_docs:
                try:
                    pages = rag.extract_document_pages(f.name, f)
                    documents.append((f.name, pages))
                    audit.log_action("Document Uploaded", "AI Workspace", f.name, status="Success")
                except Exception as exc:
                    extraction_errors.append(f"{f.name}: {exc}")
                    audit.log_action("Document Uploaded", "AI Workspace", f.name, status="Failed")
            build_report = (
                st.session_state.knowledge_base.build(documents) if documents
                else {"ok": False, "error": "No documents could be read.", "chunk_count": 0}
            )
            build_report["extraction_errors"] = extraction_errors
            st.session_state.kb_report = build_report
            if build_report.get("ok"):
                st.session_state.kb_last_upload = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                audit.log_action("Knowledge Base Built", "AI Workspace", f"{build_report['chunk_count']} chunks", status="Success")

kb = st.session_state.knowledge_base

if kb.is_ready:
    kb_cols = st.columns(4)
    kb_cols[0].metric("Documents Indexed", len(kb.document_names))
    kb_cols[1].metric("Chunks Created", len(kb.chunks))
    kb_cols[2].metric("Embedding Status", "Ready")
    kb_cols[3].metric("Latest Upload", st.session_state.kb_last_upload or "N/A")
    st.caption(f"Embedding model: `{rag.EMBEDDING_MODEL_NAME}` · Knowledge base status: Ready for retrieval")

    doc_summary = db.summarize_knowledge_base(kb)
    search_filter = st.text_input("Search indexed documents", placeholder="Filter by filename...", icon=":material/search:")
    if search_filter:
        doc_summary = doc_summary[doc_summary["Document"].str.contains(search_filter, case=False, na=False)]
    ui_components.data_table(doc_summary)
elif st.session_state.kb_report and st.session_state.kb_report.get("error"):
    st.error(f"Knowledge base build failed: {st.session_state.kb_report['error']}")
else:
    ui_components.empty_state(
        "No Documents Indexed Yet",
        "Upload PDF, TXT, or DOCX procurement documents above and click Build / Refresh Knowledge Base "
        "to enable document-grounded answers with citations.",
    )
    st.caption(f"Embedding model configured: `{rag.EMBEDDING_MODEL_NAME}` · Knowledge base status: Not built")

for err in (st.session_state.kb_report or {}).get("extraction_errors", []):
    st.warning(f"Could not extract text: {err}")
