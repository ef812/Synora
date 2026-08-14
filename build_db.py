import os
import gc
import shutil

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma

# =====================================================
# SETTINGS
# =====================================================

# Number of PDF pages to process at once
PAGES_PER_BATCH = 10

# Number of chunks to save to Chroma at once
CHUNK_BATCH_SIZE = 50

# Resume from this page (0 = first page)
START_PAGE = 20

# Set to True ONLY if you want to rebuild the database
REBUILD_DATABASE = False

# =====================================================
# DELETE OLD DATABASE (OPTIONAL)
# =====================================================

if REBUILD_DATABASE and os.path.exists("db"):
    print("Deleting old database...")
    shutil.rmtree("db")

# =====================================================
# LOAD EMBEDDING MODEL
# =====================================================

print("Loading embedding model...")

embeddings = HuggingFaceEmbeddings(
    model_name="all-MiniLM-L6-v2"
)

# =====================================================
# OPEN / CREATE DATABASE
# =====================================================

print("Opening Chroma database...")

db = Chroma(
    persist_directory="db",
    embedding_function=embeddings
)

# =====================================================
# TEXT SPLITTER
# =====================================================

splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=100
)

# =====================================================
# FIND PDF FILES
# =====================================================

pdfs = sorted(
    file
    for file in os.listdir("docs")
    if file.endswith(".pdf")
)

print(f"\nFound {len(pdfs)} PDF files.\n")

total_saved = 0

# =====================================================
# PROCESS PDFS
# =====================================================

for pdf in pdfs:

    print("=" * 70)
    print(f"Processing: {pdf}")

    loader = PyPDFLoader(os.path.join("docs", pdf))
    pages = loader.load()

    total_pages = len(pages)

    print(f"Total pages: {total_pages}")

    for start in range(START_PAGE, total_pages, PAGES_PER_BATCH):

        end = min(start + PAGES_PER_BATCH, total_pages)

        print(f"\nPages {start + 1} - {end}")

        page_batch = pages[start:end]

        chunks = splitter.split_documents(page_batch)

        print(f"Created {len(chunks)} chunks")

        if len(chunks) == 0:
            print("No chunks found. Skipping...")
            continue

        # ---------------------------------------------
        # SAVE SMALL CHUNK BATCHS
        # ---------------------------------------------

        for i in range(0, len(chunks), CHUNK_BATCH_SIZE):

            chunk_batch = chunks[i:i + CHUNK_BATCH_SIZE]

            print(
                f"Saving chunk batch "
                f"{i // CHUNK_BATCH_SIZE + 1} "
                f"({len(chunk_batch)} chunks)..."
            )

            db.add_documents(chunk_batch)

            total_saved += len(chunk_batch)

            print(f"Saved! Total added this run: {total_saved}")

            del chunk_batch
            gc.collect()

        # Free RAM

        del page_batch
        del chunks
        gc.collect()

    # Finished this PDF

    del pages
    gc.collect()

    print(f"Finished {pdf}\n")

print("=" * 70)
print("Done!")
print(f"Chunks added during this run: {total_saved}")