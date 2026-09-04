import os
import re
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma

DB_PATH = os.getenv("CHROMA_DB_PATH", "db")
UPLOAD_DB_PATH = os.getenv("UPLOAD_DB_PATH", "uploads_db")

embedding_model = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
vectorstore = Chroma(persist_directory=DB_PATH, embedding_function=embedding_model)

# Phrasing that adds no clinical signal but shifts the embedding vector enough
# to change which chunks rank in the top-k (e.g. "I am tired" vs "I feel tired").
# Stripped before embedding only — the original question still goes to
# classify_intent/analyze untouched.
_FILLER_PATTERNS = [
    r"\bi am\b", r"\bi'm\b", r"\bi feel\b", r"\bi have been feeling\b",
    r"\bi have been experiencing\b", r"\bi have\b", r"\bi've been\b",
    r"\bi think i\b", r"\bi've got\b", r"\bi got\b", r"\bi'm experiencing\b",
    r"\bfeeling\b", r"\bexperiencing\b",
]
_FILLER_RE = re.compile("|".join(_FILLER_PATTERNS), flags=re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_query(question: str) -> str:
    """Collapse phrasing variance (copulas, filler verbs) before embedding,
    so semantically identical symptom descriptions retrieve consistently."""
    stripped = _FILLER_RE.sub(" ", question)
    stripped = _WHITESPACE_RE.sub(" ", stripped).strip()
    # Fall back to the original question if stripping left nothing useful
    return stripped if len(stripped) >= 3 else question


def retrieve(state: dict) -> dict:
    question = state["question"]
    normalized = normalize_query(question)

    # Retrieve on the original phrasing (preserves whatever already worked),
    # then add results from the normalized query as extra candidates —
    # additive, so normalization can only help coverage, never remove a
    # chunk the original phrasing would have found on its own.
    docs = vectorstore.similarity_search(question, k=4)
    if normalized != question:
        extra_docs = vectorstore.similarity_search(normalized, k=4)
        seen = {d.page_content for d in docs}
        for d in extra_docs:
            if d.page_content not in seen:
                docs.append(d)
                seen.add(d.page_content)

    session_id = state.get("session_id")
    if session_id:
        try:
            session_db = Chroma(
                persist_directory=UPLOAD_DB_PATH,
                embedding_function=embedding_model,
                collection_name=f"session_{session_id}",
            )
            session_docs = session_db.similarity_search(question, k=2)
            docs = session_docs + docs
        except Exception:
            pass

    context_parts = []
    sources = []
    pages = []

    for i, doc in enumerate(docs):
        source_id = f"src_{i}"
        context_parts.append(f"[{source_id}] {doc.page_content}")
        sources.append(source_id)
        pages.append(doc.metadata.get("page", -1))

    state["context"] = "\n\n".join(context_parts)
    state["sources"] = sources
    state["pages"] = pages
    return state
