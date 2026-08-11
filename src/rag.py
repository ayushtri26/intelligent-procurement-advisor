"""Local RAG over uploaded procurement documents.

Extraction (PyMuPDF / python-docx / plain text) -> overlapping chunking ->
sentence-transformers embeddings -> local FAISS similarity search. Every
retrieved chunk carries citation metadata (filename, page if available,
chunk id) so any document-derived claim can be traced back to its source.

Deliberately independent of Streamlit and of src.llm_service — this module
only ever returns plain data; nothing here calls an LLM.
"""
from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass

EMBEDDING_MODEL_NAME = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
CHUNK_SIZE = 800
CHUNK_OVERLAP = 150
DEFAULT_TOP_K = 4
SUPPORTED_EXTENSIONS = ("pdf", "txt", "docx")


@dataclass
class DocumentChunk:
    chunk_id: str
    doc_id: str
    filename: str
    page: int | None
    text: str


@dataclass
class RetrievedChunk:
    chunk: DocumentChunk
    score: float


# --------------------------------------------------------------------------
# Extraction — each returns a list of (page_number_or_None, page_text)
# --------------------------------------------------------------------------

def extract_pdf_pages(data: bytes) -> list[tuple[int, str]]:
    import fitz  # PyMuPDF

    pages = []
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        for i, page in enumerate(doc, start=1):
            text = page.get_text().strip()
            if text:
                pages.append((i, text))
    finally:
        doc.close()
    return pages


def extract_docx_pages(file) -> list[tuple[None, str]]:
    import docx

    document = docx.Document(file)
    text = "\n".join(p.text for p in document.paragraphs if p.text.strip())
    return [(None, text)] if text.strip() else []


def extract_txt_pages(text: str) -> list[tuple[None, str]]:
    return [(None, text)] if text.strip() else []


def extract_document_pages(filename: str, file) -> list[tuple[int | None, str]]:
    """`file` is a file-like object (must support .read()) or raw bytes/str."""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported document type: {filename} (allowed: {', '.join(SUPPORTED_EXTENSIONS)})")

    if ext == "pdf":
        data = file.read() if hasattr(file, "read") else file
        return extract_pdf_pages(data)
    if ext == "docx":
        return extract_docx_pages(file)
    # txt
    data = file.read() if hasattr(file, "read") else file
    if isinstance(data, bytes):
        data = data.decode("utf-8", errors="ignore")
    return extract_txt_pages(data)


# --------------------------------------------------------------------------
# Chunking — overlapping, character-based, avoids cutting mid-word
# --------------------------------------------------------------------------

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            last_space = text.rfind(" ", start, end)
            if last_space > start:
                end = last_space
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def chunk_document(doc_id: str, filename: str, pages: list[tuple[int | None, str]]) -> list[DocumentChunk]:
    chunks = []
    for page_num, page_text in pages:
        for piece in chunk_text(page_text):
            chunks.append(
                DocumentChunk(
                    chunk_id=f"{doc_id}-{uuid.uuid4().hex[:8]}",
                    doc_id=doc_id,
                    filename=filename,
                    page=page_num,
                    text=piece,
                )
            )
    return chunks


def format_citation(chunk: DocumentChunk) -> str:
    page_part = f", p.{chunk.page}" if chunk.page else ""
    return f"{chunk.filename}{page_part} [{chunk.chunk_id}]"


# --------------------------------------------------------------------------
# Embeddings + FAISS
# --------------------------------------------------------------------------

def get_embedding_model():
    """Lazily load the local sentence-transformers model. Returns None if unavailable."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return None
    try:
        return SentenceTransformer(EMBEDDING_MODEL_NAME)
    except Exception:
        return None


class KnowledgeBase:
    """In-memory FAISS index over uploaded document chunks, rebuilt on demand."""

    def __init__(self):
        self.chunks: list[DocumentChunk] = []
        self.index = None
        self.document_names: list[str] = []
        self._model = None

    @property
    def is_ready(self) -> bool:
        return self.index is not None and len(self.chunks) > 0

    def build(self, documents: list[tuple[str, list[tuple[int | None, str]]]]) -> dict:
        """`documents`: list of (filename, pages). Returns a small build report."""
        try:
            import faiss
        except ImportError:
            return {"ok": False, "error": "faiss is not available in this environment.", "chunk_count": 0}

        self._model = self._model or get_embedding_model()
        if self._model is None:
            return {
                "ok": False,
                "error": "sentence-transformers is not available in this environment.",
                "chunk_count": 0,
            }

        all_chunks: list[DocumentChunk] = []
        for filename, pages in documents:
            doc_id = uuid.uuid4().hex[:8]
            all_chunks.extend(chunk_document(doc_id, filename, pages))

        if not all_chunks:
            self.chunks, self.index, self.document_names = [], None, []
            return {"ok": False, "error": "No extractable text found in the uploaded documents.", "chunk_count": 0}

        texts = [c.text for c in all_chunks]
        embeddings = self._model.encode(texts, show_progress_bar=False, convert_to_numpy=True).astype("float32")
        faiss.normalize_L2(embeddings)

        index = faiss.IndexFlatIP(embeddings.shape[1])
        index.add(embeddings)

        self.chunks = all_chunks
        self.index = index
        self.document_names = [name for name, _ in documents]
        return {"ok": True, "error": None, "chunk_count": len(all_chunks), "document_count": len(documents)}

    def retrieve(self, query: str, k: int = DEFAULT_TOP_K) -> list[RetrievedChunk]:
        if not self.is_ready or not query.strip():
            return []
        import faiss

        model = self._model or get_embedding_model()
        if model is None:
            return []
        query_vec = model.encode([query], convert_to_numpy=True).astype("float32")
        faiss.normalize_L2(query_vec)
        k = min(k, len(self.chunks))
        scores, indices = self.index.search(query_vec, k)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            results.append(RetrievedChunk(chunk=self.chunks[idx], score=float(score)))
        return results
