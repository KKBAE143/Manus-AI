import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from app.core.database import SessionLocal
from app.models.document import Document, DocumentStatus, Job, JobStatus, MergeJob, MergeStatus

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=int(os.environ.get("PIPELINE_WORKERS", "8")), thread_name_prefix="pipeline")
_active_jobs: set[str] = set()
_lock = threading.Lock()
_active_merge_jobs: set[str] = set()
_merge_lock = threading.Lock()


def _run_pipeline_job(document_id: str, job_id: str) -> None:
    from app.services.manuscript_pipeline import flush_log_events, run_pipeline

    db = SessionLocal()
    try:
        run_pipeline(document_id, job_id, db)
    except Exception as exc:
        logger.exception("Pipeline failed for document %s job %s: %s", document_id, job_id, exc)
        try:
            flush_log_events(db)
            document = db.query(Document).filter(Document.id == document_id).first()
            job = db.query(Job).filter(Job.id == job_id).first()
            if document:
                document.status = DocumentStatus.failed
                document.error_log = str(exc)
            if job:
                job.status = JobStatus.failed
                job.error_log = str(exc)
            db.commit()
        except Exception:
            logger.exception("Failed to update error state for document %s", document_id)
    finally:
        db.close()
        with _lock:
            _active_jobs.discard(document_id)


def submit_pipeline_job(document_id: str, job_id: str) -> bool:
    with _lock:
        if document_id in _active_jobs:
            logger.warning("Pipeline job for document %s is already running; skipping duplicate submission", document_id)
            return False
        _active_jobs.add(document_id)

    _executor.submit(_run_pipeline_job, document_id, job_id)
    logger.info("Submitted pipeline job for document %s job %s", document_id, job_id)
    return True


def _run_rerun_chunk_job(document_id: str, chunk_id: str, stage_key: str) -> None:
    from app.services.manuscript_pipeline import flush_log_events, rerun_chunk

    db = SessionLocal()
    try:
        rerun_chunk(document_id, chunk_id, db, stage_key)
    except Exception as exc:
        logger.exception("Rerun chunk failed for document %s chunk %s: %s", document_id, chunk_id, exc)
        flush_log_events(db)
    finally:
        db.close()


def submit_rerun_chunk_job(document_id: str, chunk_id: str, stage_key: str = "extract") -> None:
    _executor.submit(_run_rerun_chunk_job, document_id, chunk_id, stage_key)
    logger.info("Submitted rerun chunk job for document %s chunk %s stage %s", document_id, chunk_id, stage_key)


def _run_merge_job(document_id: str, merge_job_id: str, part_ids: list[str]) -> None:
    from app.services.manuscript_pipeline import merge_parts_ordered
    from app.models.document import Document, ExportPart, ExportProfile

    db = SessionLocal()
    try:
        merge_job = db.query(MergeJob).filter(MergeJob.id == merge_job_id).first()
        if not merge_job:
            logger.error("MergeJob %s not found", merge_job_id)
            return

        merge_job.status = MergeStatus.in_progress
        merge_job.progress_percent = 0.0
        merge_job.progress_message = "Starting merge"
        db.commit()

        document = db.query(Document).filter(Document.id == document_id).first()
        if not document:
            merge_job.status = MergeStatus.failed
            merge_job.error_log = "Document not found"
            db.commit()
            return

        part_map = {p.id: p for p in document.parts}
        ordered = [part_map[pid] for pid in part_ids if pid in part_map]
        if not ordered:
            merge_job.status = MergeStatus.failed
            merge_job.error_log = "No valid parts found"
            db.commit()
            return

        profile = db.query(ExportProfile).filter(ExportProfile.document_id == document_id).first()

        def _progress(pct: float, msg: str) -> None:
            try:
                mj = db.query(MergeJob).filter(MergeJob.id == merge_job_id).first()
                if mj:
                    mj.progress_percent = pct
                    mj.progress_message = msg
                    db.commit()
            except Exception as inner_exc:
                logger.warning("Failed to update merge progress: %s", inner_exc)

        merged_path = merge_parts_ordered(document, ordered, profile=profile, progress_callback=_progress)

        document.merged_docx_path = str(merged_path)
        merge_job.status = MergeStatus.completed
        merge_job.progress_percent = 100.0
        merge_job.progress_message = "Merge complete"
        merge_job.output_path = str(merged_path)
        merge_job.completed_at = datetime.utcnow()
        db.commit()
        logger.info("Merge job %s completed for document %s", merge_job_id, document_id)

    except Exception as exc:
        logger.exception("Merge job %s failed for document %s: %s", merge_job_id, document_id, exc)
        try:
            mj = db.query(MergeJob).filter(MergeJob.id == merge_job_id).first()
            if mj:
                mj.status = MergeStatus.failed
                mj.error_log = str(exc)
                db.commit()
        except Exception:
            logger.exception("Failed to update merge error state for job %s", merge_job_id)
    finally:
        db.close()
        with _merge_lock:
            _active_merge_jobs.discard(merge_job_id)


def submit_merge_job(document_id: str, merge_job_id: str, part_ids: list[str]) -> bool:
    with _merge_lock:
        if merge_job_id in _active_merge_jobs:
            logger.warning("Merge job %s is already running; skipping duplicate", merge_job_id)
            return False
        _active_merge_jobs.add(merge_job_id)

    _executor.submit(_run_merge_job, document_id, merge_job_id, part_ids)
    logger.info("Submitted merge job %s for document %s", merge_job_id, document_id)
    return True
