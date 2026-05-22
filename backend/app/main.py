from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api.documents import router as documents_router
from app.api.test import router as test_router
from app.api.manuscript import router as manuscript_router
from app.api.quiz import router as quiz_router
from app.core.config import settings
from app.core.database import Base, engine
from sqlalchemy import text

Base.metadata.create_all(bind=engine)


def _run_migrations():
    with engine.connect() as conn:
        text_cols = [
            ("manuscript_sections", "flag_note", "TEXT"),
            ("manuscript_sections", "lock_reason", "TEXT"),
            ("chunks", "transformed_text_path", "TEXT"),
            ("chunks", "transformed_text", "TEXT"),
        ]
        for table, col, col_type in text_cols:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {col_type}"))
                conn.commit()
            except Exception:
                conn.rollback()

        json_cols = [
            ("chunks", "transform_stats", "JSONB"),
        ]
        for table, col, col_type in json_cols:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {col_type}"))
                conn.commit()
            except Exception:
                conn.rollback()

        enum_cols = [
            (
                "manuscript_sections",
                "approval_status",
                "approvalstatus",
                "'PENDING', 'REVIEWED', 'APPROVED', 'LOCKED'",
                "'PENDING'",
            ),
        ]
        for table, col, enum_name, enum_vals, default_val in enum_cols:
            try:
                conn.execute(text(f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = '{enum_name}') THEN CREATE TYPE {enum_name} AS ENUM ({enum_vals}); END IF; END $$"))
                conn.commit()
            except Exception:
                conn.rollback()
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {enum_name} NOT NULL DEFAULT {default_val}"))
                conn.commit()
            except Exception:
                conn.rollback()

        composite_indexes = [
            ("ix_chunks_document_id_chunk_index", "chunks", "document_id, chunk_index"),
            ("ix_manuscript_sections_draft_id_section_order", "manuscript_sections", "draft_id, section_order"),
            ("ix_project_event_logs_document_id_created_at", "project_event_logs", "document_id, created_at"),
        ]
        for idx_name, table, cols in composite_indexes:
            try:
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} ({cols})"))
                conn.commit()
            except Exception:
                conn.rollback()


_run_migrations()


def _cleanup_stale_jobs():
    """Reset any PROCESSING/QUEUED documents and IN_PROGRESS jobs left over from a previous crash."""
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "UPDATE documents SET status = 'FAILED', error_log = 'Server restarted while processing' "
                "WHERE status IN ('PROCESSING', 'QUEUED')"
            ))
            conn.execute(text(
                "UPDATE jobs SET status = 'FAILED', error_log = 'Server restarted while processing' "
                "WHERE status IN ('PENDING', 'IN_PROGRESS')"
            ))
            conn.execute(text(
                "UPDATE chunks SET status = 'FAILED', error_log = 'Server restarted while processing' "
                "WHERE status IN ('PROCESSING', 'QUEUED')"
            ))
            conn.execute(text(
                "UPDATE merge_jobs SET status = 'FAILED', error_log = 'Server restarted while processing' "
                "WHERE status IN ('PENDING', 'IN_PROGRESS')"
            ))
            conn.commit()
    except Exception:
        pass


_cleanup_stale_jobs()

app = FastAPI(title=settings.PROJECT_NAME, version="2.0.0")

app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents_router)
app.include_router(test_router)
app.include_router(manuscript_router)
app.include_router(quiz_router)


@app.get("/")
def read_root():
    return {"message": f"Welcome to the {settings.PROJECT_NAME} API"}


@app.get("/api/health")
def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
