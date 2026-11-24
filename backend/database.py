"""RepoCrew database setup.

SQLAlchemy + SQLite (file ``repocrew.db``). The schema in ``models.py``
deliberately sticks to portable types (Integer, String, Text, DateTime,
generic JSON) so it can be pointed at PostgreSQL in production simply by
changing the connection URL — see README "production swap notes".
"""
from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

from . import config

engine = create_engine(
    f"sqlite:///{config.RC_DB_PATH}",
    connect_args={"check_same_thread": False},
    future=True,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
Base = declarative_base()


def init_db() -> None:
    from . import models  # noqa: F401  (ensure models are registered)
    Base.metadata.create_all(engine)
