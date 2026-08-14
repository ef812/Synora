import os
import zipfile
import requests

DB_PATH = os.getenv("CHROMA_DB_PATH", "db")
DB_ZIP_URL = os.getenv("DB_ZIP_URL")  # set this in Railway variables


def db_is_populated() -> bool:
    sqlite_path = os.path.join(DB_PATH, "chroma.sqlite3")
    return os.path.exists(sqlite_path) and os.path.getsize(sqlite_path) > 1_000_000


def download_and_extract_db():
    print("Downloading pre-built database...")
    response = requests.get(DB_ZIP_URL, stream=True)
    response.raise_for_status()

    zip_path = "db.zip"
    with open(zip_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    print("Extracting...")
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(os.path.dirname(DB_PATH) or ".")

    os.remove(zip_path)
    print("Database ready.")


if __name__ == "__main__":
    if db_is_populated():
        print("Database already populated, skipping download.")
    else:
        download_and_extract_db()
