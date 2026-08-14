import os
import requests

DB_PATH = os.getenv("CHROMA_DB_PATH", "db")
DOCS_PATH = "docs"

# Map of filename -> direct download URL
PDF_SOURCES = {
    "medical1.pdf": "https://drive.google.com/uc?export=download&id=YOUR_FILE_ID_1",
    "medical2.pdf": "https://drive.google.com/uc?export=download&id=YOUR_FILE_ID_2",
    "medical3.pdf": "",
    "medical4.pdf": "",
    "medical5.pdf": "",
}


def download_pdfs():
    os.makedirs(DOCS_PATH, exist_ok=True)
    for filename, url in PDF_SOURCES.items():
        filepath = os.path.join(DOCS_PATH, filename)
        if os.path.exists(filepath):
            continue
        print(f"Downloading {filename}...")
        response = requests.get(url)
        response.raise_for_status()
        with open(filepath, "wb") as f:
            f.write(response.content)
        print(f"Saved {filename}")


def db_is_populated() -> bool:
    sqlite_path = os.path.join(DB_PATH, "chroma.sqlite3")
    return os.path.exists(sqlite_path) and os.path.getsize(sqlite_path) > 1_000_000


if __name__ == "__main__":
    if db_is_populated():
        print("Database already populated, skipping seed.")
    else:
        print("Database empty — seeding from source PDFs...")
        download_pdfs()
        # import and run your existing build logic
        import build_db
        print("Seed complete.")
