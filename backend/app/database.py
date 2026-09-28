import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


def _resolve_database_url() -> str:
    """Resolve the SQLAlchemy database URL.

    Supports the standard DATABASE_URL env var. If the platform provides a
    `file:` scheme URL (e.g. file:/home/z/my-project/db/custom.db), it is
    converted to a proper SQLite URL with an absolute path.
    """
    raw = os.getenv("DATABASE_URL", "").strip()
    if raw.startswith("file:"):
        db_path = Path(raw[len("file:"):])
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{db_path}"
    if raw:
        return raw
    # Local development default: SQLite next to the backend package
    default_path = Path(__file__).resolve().parent.parent / "dev.db"
    return f"sqlite:///{default_path}"


DATABASE_URL = _resolve_database_url()

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def get_db():
    """FastAPI dependency that yields a database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
