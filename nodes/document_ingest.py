import os
import uuid
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma

UPLOAD_DB_PATH = os.getenv("UPLOAD_DB_PATH", "uploads_db")
embedding_model = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=100)


def ingest_document(filepath: str, session_id: str) -> int:
    """Chunks and embeds a PDF into a session-scoped Chroma collection.
    Returns the number of chunks added."""
    loader = PyPDFLoader(filepath)
    pages = loader.load()
    chunks = splitter.split_documents(pages)

    collection_name = f"session_{session_id}"
    db = Chroma(
        persist_directory=UPLOAD_DB_PATH,
        embedding_function=embedding_model,
        collection_name=collection_name,
    )
    db.add_documents(chunks)
    return len(chunks)


def get_session_vectorstore(session_id: str) -> Chroma:
    collection_name = f"session_{session_id}"
    return Chroma(
        persist_directory=UPLOAD_DB_PATH,
        embedding_function=embedding_model,
        collection_name=collection_name,
    )
