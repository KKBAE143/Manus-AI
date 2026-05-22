import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

_is_sqlite = settings.SQLALCHEMY_DATABASE_URI.startswith("sqlite")

connect_args = {"check_same_thread": False, "timeout": 30} if _is_sqlite else {}

_pipeline_workers = int(os.environ.get("PIPELINE_WORKERS", "8"))
_pool_size = int(os.environ.get("DB_POOL_SIZE", str(_pipeline_workers + 2)))
_max_overflow = int(os.environ.get("DB_MAX_OVERFLOW", str(_pipeline_workers * 2)))

_engine_kwargs = dict(
    connect_args=connect_args,
    pool_pre_ping=True,
)

if not _is_sqlite:
    _engine_kwargs["pool_size"] = _pool_size
    _engine_kwargs["max_overflow"] = _max_overflow

engine = create_engine(settings.SQLALCHEMY_DATABASE_URI, **_engine_kwargs)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
