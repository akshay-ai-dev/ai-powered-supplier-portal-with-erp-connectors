"""Database engine and sessions: SQLite in WAL mode via SQLModel (SRS §2.1).

Switching to PostgreSQL later only changes DATABASE_URL.
TODO (team): replace `create_tables()` with Alembic migrations once the shared schema settles.
"""

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings

_engine: Engine | None = None


def _enable_sqlite_wal(dbapi_connection, _record) -> None:  # noqa: ANN001
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, connect_args={"check_same_thread": False})
        event.listen(engine, "connect", _enable_sqlite_wal)
        return engine
    return create_engine(url)


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = make_engine(get_settings().database_url)
    return _engine


def set_engine(engine: Engine) -> None:
    """Used by tests to point the app at a temporary database."""
    global _engine
    _engine = engine


def create_tables() -> None:
    from app.db import models  # noqa: F401  (register tables)

    SQLModel.metadata.create_all(get_engine())


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
