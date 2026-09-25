import os
import zipfile
from b2sdk.v2 import InMemoryAccountInfo, B2Api

DB_PATH = os.getenv("CHROMA_DB_PATH", "db")
B2_KEY_ID = os.getenv("B2_KEY_ID")
B2_APPLICATION_KEY = os.getenv("B2_APPLICATION_KEY")
B2_BUCKET_NAME = os.getenv("B2_BUCKET_NAME", "Synora")
DB_ZIP_FILENAME = os.getenv("DB_ZIP_FILENAME", "db.zip")


def db_is_populated() -> bool:
    sqlite_path = os.path.join(DB_PATH, "chroma.sqlite3")
    return os.path.exists(sqlite_path) and os.path.getsize(sqlite_path) > 1_000_000


def download_and_extract_db():
    print("Downloading pre-built database...")

    info = InMemoryAccountInfo()
    b2_api = B2Api(info)
    b2_api.authorize_account("production", B2_KEY_ID, B2_APPLICATION_KEY)
    bucket = b2_api.get_bucket_by_name(B2_BUCKET_NAME)

    zip_path = "db.zip"
    downloaded_file = bucket.download_file_by_name(DB_ZIP_FILENAME)
    downloaded_file.save_to(zip_path)

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
