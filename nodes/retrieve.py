import os
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma

DB_PATH = os.getenv("CHROMA_DB_PATH", "db")
UPLOAD_DB_PATH = os.getenv("UPLOAD_DB_PATH", "uploads_db")

embedding_model = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
vectorstore = Chroma(persist_directory=DB_PATH, embedding_function=embedding_model)


def retrieve(state: dict) -> dict:
    docs = vectorstore.similarity_search(state["question"], k=4)

    session_id = state.get("session_id")
    if session_id:
        try:
            session_db = Chroma(
                persist_directory=UPLOAD_DB_PATH,
                embedding_function=embedding_model,
                collection_name=f"session_{session_id}",
            )
            session_docs = session_db.similarity_search(state["question"], k=2)
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
