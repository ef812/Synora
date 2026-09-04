import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Base

# Railway injects DATABASE_URL automatically once the Postgres plugin is
# attached to this service. Fallback lets local dev point at a local Postgres
# (or you can swap to a local sqlite:/// URL for quick local testing).
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/synora_dev")

# Railway's DATABASE_URL sometimes comes as "postgres://" (old scheme);
# SQLAlchemy 1.4+/2.x requires "postgresql://".
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db():
    """Create tables if they don't exist. Call once on app startup."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency: yields a session, closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
