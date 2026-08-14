import os
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings

DB_PATH = os.getenv("CHROMA_DB_PATH", "db")
embedding_model = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
vectorstore = Chroma(persist_directory=DB_PATH, embedding_function=embedding_model)


def retrieve(state: dict) -> dict:
    docs = vectorstore.similarity_search(state["question"], k=4)

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