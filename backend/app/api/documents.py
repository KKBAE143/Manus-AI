import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.database import get_db
from app.models.document import Artifact, Chunk, Document, DocumentConfig, DocumentStatus, ExportPart, Job, JobStatus, MergeJob, MergeStatus
from app.schemas.document import (
    ChunkRerunRequest,
    DocumentConfigCreate,
    DocumentCreateResponse,
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentResponse,
    ExportPartResponse,
    JobStatusResponse,
    MergeJobAccepted,
    MergeJobStatusResponse,
    MergeRequest,
    MergeResponse,
)
from app.services.manuscript_pipeline import build_manifest_summary, build_system_health, inspect_pdf, merge_document_parts, merge_parts_ordered, validate_merge

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

_SYSTEM_HEALTH_CACHE: dict[str, object] = {"value": None, "expires_at": 0.0}
_MANIFEST_SUMMARY_CACHE: dict[str, tuple[int, dict | None]] = {}


def _cached_manifest_summary(document: Document):
    if not document.manifest_path:
        return None

    manifest_path = Path(document.manifest_path)
    if not manifest_path.exists():
        return None

    try:
        mtime_ns = manifest_path.stat().st_mtime_ns
    except OSError:
        return None

    cached = _MANIFEST_SUMMARY_CACHE.get(document.manifest_path)
    if cached and cached[0] == mtime_ns:
        return cached[1]

    summary = build_manifest_summary(document)
    _MANIFEST_SUMMARY_CACHE[document.manifest_path] = (mtime_ns, summary)
    return summary


def _build_job_response(job: Job) -> JobStatusResponse:
    return JobStatusResponse(
        job_id=job.id,
        document_id=job.document_id,
        status=job.status.value if hasattr(job.status, "value") else str(job.status),
        current_stage=job.stage,
        stage_key=job.stage_key,
        stage_name=job.stage_name,
        progress_percent=job.progress_percent,
        progress_message=job.progress_message,
        error_log=job.error_log,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _build_part_response(part: ExportPart) -> ExportPartResponse:
    return ExportPartResponse(
        id=part.id,
        part_number=part.part_number,
        page_start=part.page_start,
        page_end=part.page_end,
        page_count=part.page_count,
        filename=part.filename,
        status=part.status.value if hasattr(part.status, "value") else str(part.status),
        download_url=f"/api/v1/documents/parts/{part.id}/download",
    )


def _build_document_response(document: Document) -> DocumentResponse:
    latest_job = document.jobs[0] if document.jobs else None
    return DocumentResponse(
        id=document.id,
        filename=document.filename,
        status=document.status.value if hasattr(document.status, "value") else str(document.status),
        page_count=document.page_count or 0,
        created_at=document.created_at,
        updated_at=document.updated_at,
        manifest_available=bool(document.manifest_path),
        merged_docx_available=bool(document.merged_docx_path),
        latest_job=_build_job_response(latest_job) if latest_job else None,
        part_count=len(document.parts),
    )


@router.post("/upload", response_model=DocumentCreateResponse)
async def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db)):
    filename = file.filename or "upload.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    document_id = str(uuid.uuid4())
    safe_filename = f"{document_id}_{filename}"
    upload_path = Path(settings.UPLOAD_DIR)
    upload_path.mkdir(parents=True, exist_ok=True)
    file_path = upload_path / safe_filename

    try:
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        inspection = inspect_pdf(str(file_path))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save or inspect file: {exc}") from exc

    document = Document(
        id=document_id,
        filename=filename,
        local_storage_path=str(file_path),
        page_count=inspection["page_count"],
        status=DocumentStatus.uploaded,
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    return DocumentCreateResponse(
        id=document.id,
        filename=document.filename,
        status=document.status.value,
        page_count=document.page_count or 0,
        message="Document uploaded successfully.",
    )


@router.post("/{document_id}/process")
def process_document(document_id: str, config: DocumentConfigCreate, db: Session = Depends(get_db)):
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")

    db_config = db.query(DocumentConfig).filter(DocumentConfig.document_id == document_id).first()
    config_data = config.model_dump()
    if db_config:
        for key, value in config_data.items():
            setattr(db_config, key, value)
    else:
        db_config = DocumentConfig(document_id=document_id, **config_data)
        db.add(db_config)

    job = Job(
        document_id=document_id,
        status=JobStatus.pending,
        stage=1,
        stage_key="queued",
        stage_name="Queued",
        progress_percent=0.0,
        progress_message="Waiting for worker",
    )
    db.add(job)
    document.status = DocumentStatus.queued
    db.commit()
    db.refresh(job)

    from app.core.thread_runner import submit_pipeline_job

    submitted = submit_pipeline_job(document_id, job.id)
    if not submitted:
        job.status = JobStatus.failed
        job.error_log = "A pipeline job for this document is already running"
        document.status = DocumentStatus.failed
        document.error_log = "A pipeline job for this document is already running"
        db.commit()
        raise HTTPException(status_code=409, detail="A pipeline job for this document is already running")

    document.status = DocumentStatus.processing
    db.commit()

    return {"message": "Processing started", "job_id": job.id, "document_id": document_id}


@router.post("/{document_id}/archive")
def archive_document(document_id: str, db: Session = Depends(get_db)):
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")
    document.status = DocumentStatus.archived
    db.commit()
    return {"status": "success"}


@router.post("/{document_id}/clone-config")
def clone_document_config(document_id: str, source_document_id: str, db: Session = Depends(get_db)):
    document = db.query(Document).filter(Document.id == document_id).first()
    source = db.query(DocumentConfig).filter(DocumentConfig.document_id == source_document_id).first()
    if not document or not source:
        raise HTTPException(status_code=404, detail="Document or source config not found.")
    target = db.query(DocumentConfig).filter(DocumentConfig.document_id == document_id).first()
    payload = {
        "book_title": source.book_title,
        "split_mode": source.split_mode,
        "pages_per_docx": source.pages_per_docx,
        "start_page": source.start_page,
        "end_page": source.end_page,
        "keep_page_markers": source.keep_page_markers,
        "generate_appendix_reference": source.generate_appendix_reference,
    }
    if target:
        for key, value in payload.items():
            setattr(target, key, value)
    else:
        db.add(DocumentConfig(document_id=document_id, **payload))
    db.commit()
    return {"status": "success"}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    job.status = JobStatus.failed
    job.error_log = "Cancelled by user"
    if job.document:
        job.document.status = DocumentStatus.failed
    db.commit()
    return {"status": "success"}


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return _build_job_response(job)


@router.get("/", response_model=DocumentListResponse)
def list_documents(
    db: Session = Depends(get_db),
    status: str | None = Query(default=None),
    q: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
):
    query = db.query(Document).options(
        selectinload(Document.jobs),
        selectinload(Document.parts),
    )
    if status and status.upper() != "ALL":
        query = query.filter(Document.status == status.upper())
    if q:
        query = query.filter(Document.filename.ilike(f"%{q}%"))
    total = query.count()
    documents = query.order_by(Document.updated_at.desc()).offset(offset).limit(limit).all()
    return DocumentListResponse(items=[_build_document_response(document) for document in documents], total=total, offset=offset, limit=limit)


@router.get("/{document_id}", response_model=DocumentDetailResponse)
def get_document(document_id: str, db: Session = Depends(get_db)):
    document = db.query(Document).options(
        selectinload(Document.jobs),
        selectinload(Document.parts),
        selectinload(Document.config),
    ).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")

    latest_job = document.jobs[0] if document.jobs else None
    base_response = _build_document_response(document).model_dump()
    return DocumentDetailResponse(
        **base_response,
        local_storage_path=document.local_storage_path,
        storage_root=document.storage_root,
        manifest_path=document.manifest_path,
        merged_docx_path=document.merged_docx_path,
        config=document.config,
        parts=[_build_part_response(part) for part in document.parts],
        manifest_summary=_cached_manifest_summary(document),
    )


@router.get("/{document_id}/parts", response_model=List[ExportPartResponse])
def list_document_parts(document_id: str, db: Session = Depends(get_db)):
    parts = db.query(ExportPart).filter(ExportPart.document_id == document_id).order_by(ExportPart.part_number.asc()).all()
    return [_build_part_response(part) for part in parts]


@router.get("/{document_id}/manifest")
def get_document_manifest(document_id: str, db: Session = Depends(get_db)):
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document or not document.manifest_path:
        raise HTTPException(status_code=404, detail="Manifest not found.")
    manifest_path = Path(document.manifest_path)
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Manifest file missing.")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


@router.get("/{document_id}/manifest/preview")
def get_document_manifest_preview(document_id: str, db: Session = Depends(get_db), q: str | None = Query(default=None), limit: int = Query(default=20, ge=1, le=200)):
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document or not document.manifest_path:
        raise HTTPException(status_code=404, detail="Manifest not found.")
    manifest_path = Path(document.manifest_path)
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Manifest file missing.")
    lines = manifest_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if q:
        lowered = q.lower()
        lines = [line for line in lines if lowered in line.lower()]
    return {"lines": lines[:limit], "total": len(lines)}


@router.get("/{document_id}/chunks")
def get_document_chunks(document_id: str, db: Session = Depends(get_db)):
    document = (
        db.query(Document)
        .options(selectinload(Document.chunks))
        .filter(Document.id == document_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")
    return [
        {
            "id": chunk.id,
            "chunk_index": chunk.chunk_index,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "page_count": chunk.page_count,
            "status": getattr(chunk.status, "value", str(chunk.status)),
            "current_stage": chunk.current_stage,
            "retry_count": chunk.retry_count,
            "progress_percent": chunk.progress_percent,
            "error_log": chunk.error_log,
            "raw_text_path": chunk.raw_text_path,
            "cleaned_text_path": chunk.cleaned_text_path,
            "output_part_path": chunk.output_part_path,
            "chapter_title": chunk.chapter_title,
            "started_at": chunk.started_at,
            "finished_at": chunk.finished_at,
        }
        for chunk in document.chunks
    ]


@router.post("/{document_id}/preview-chapters")
def preview_chapters(document_id: str, db: Session = Depends(get_db)):
    import fitz

    from app.services.chapter_detector import detect_chapter_boundaries

    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")
    if not document.local_storage_path or not Path(document.local_storage_path).exists():
        raise HTTPException(status_code=404, detail="Source PDF not found.")

    config = db.query(DocumentConfig).filter(DocumentConfig.document_id == document_id).first()
    start_page = config.start_page if config else 1
    end_page = config.end_page if config else (document.page_count or 10000)

    try:
        pdf = fitz.open(document.local_storage_path)
        total_pages = len(pdf)
        end_page = min(end_page, total_pages)
        boundaries = detect_chapter_boundaries(pdf, start_page, end_page, max_pages=500)
        pdf.close()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Chapter detection failed: {exc}") from exc

    return {
        "boundaries": [{"page": b.page, "title": b.title, "confidence": round(b.confidence, 2)} for b in boundaries],
        "total": len(boundaries),
    }


@router.get("/{document_id}/events")
def get_document_events(document_id: str, db: Session = Depends(get_db)):
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")
    return [
        {
            "id": event.id,
            "level": event.level,
            "event_type": event.event_type,
            "message": event.message,
            "stage_key": event.stage_key,
            "chunk_id": event.chunk_id,
            "created_at": event.created_at,
        }
        for event in document.events
    ]


@router.get("/{document_id}/artifacts")
def get_document_artifacts(document_id: str, db: Session = Depends(get_db)):
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")
    return [
        {
            "id": artifact.id,
            "chunk_id": artifact.chunk_id,
            "type": getattr(artifact.artifact_type, "value", str(artifact.artifact_type)),
            "label": artifact.label,
            "path": artifact.path,
            "size_bytes": artifact.size_bytes,
            "created_at": artifact.created_at,
        }
        for artifact in document.artifacts
    ]


@router.get("/artifacts/{artifact_id}/preview")
def preview_artifact(artifact_id: str, db: Session = Depends(get_db), q: str | None = Query(default=None), limit: int = Query(default=40, ge=1, le=200)):
    artifact = db.query(Artifact).filter(Artifact.id == artifact_id).first()
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found.")
    artifact_path = Path(artifact.path)
    if not artifact_path.exists():
        raise HTTPException(status_code=404, detail="Artifact file missing.")
    if artifact_path.suffix.lower() not in {".txt", ".json", ".log"}:
        return {"lines": [artifact_path.name], "total": 1}
    lines = artifact_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if q:
        lowered = q.lower()
        lines = [line for line in lines if lowered in line.lower()]
    return {"lines": lines[:limit], "total": len(lines)}


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: str, db: Session = Depends(get_db)):
    artifact = db.query(Artifact).filter(Artifact.id == artifact_id).first()
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found.")
    artifact_path = Path(artifact.path)
    if not artifact_path.exists():
        raise HTTPException(status_code=404, detail="Artifact file missing.")
    return FileResponse(path=str(artifact_path), filename=artifact_path.name)


@router.post("/{document_id}/chunks/{chunk_id}/rerun")
def rerun_document_chunk(document_id: str, chunk_id: str, db: Session = Depends(get_db)):
    from app.models.document import Chunk
    from app.core.thread_runner import submit_rerun_chunk_job

    chunk = db.query(Chunk).filter(Chunk.id == chunk_id, Chunk.document_id == document_id).first()
    if not chunk:
        raise HTTPException(status_code=404, detail="Chunk not found.")
    submit_rerun_chunk_job(document_id, chunk_id)
    return {"message": "Rerun queued", "chunk_id": chunk_id, "document_id": document_id}


@router.post("/{document_id}/chunks/rerun")
def rerun_document_chunks(document_id: str, payload: ChunkRerunRequest, db: Session = Depends(get_db)):
    from app.models.document import Chunk
    from app.core.thread_runner import submit_rerun_chunk_job

    results = []
    for chunk_id in payload.chunk_ids:
        chunk = db.query(Chunk).filter(Chunk.id == chunk_id, Chunk.document_id == document_id).first()
        if not chunk:
            results.append({"status": "not_found", "chunk_id": chunk_id})
            continue
        submit_rerun_chunk_job(document_id, chunk_id, payload.stage_key)
        results.append({"status": "queued", "chunk_id": chunk_id})
    return {"items": results, "stage_key": payload.stage_key}


@router.get("/{document_id}/source")
def download_source_pdf(document_id: str, db: Session = Depends(get_db)):
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")
    if not os.path.exists(document.local_storage_path):
        raise HTTPException(status_code=404, detail="Source PDF missing.")
    return FileResponse(path=document.local_storage_path, filename=document.filename, media_type="application/pdf")


@router.get("/parts/{part_id}/download")
def download_part(part_id: str, db: Session = Depends(get_db)):
    part = db.query(ExportPart).filter(ExportPart.id == part_id).first()
    if not part:
        raise HTTPException(status_code=404, detail="Part not found.")
    if not os.path.exists(part.local_docx_path):
        raise HTTPException(status_code=404, detail="Part file missing.")
    return FileResponse(
        path=part.local_docx_path,
        filename=part.filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@router.get("/parts/{part_id}/preview")
def preview_part(part_id: str, db: Session = Depends(get_db), q: str | None = Query(default=None), limit: int = Query(default=5000, ge=1, le=50000)):
    part = db.query(ExportPart).filter(ExportPart.id == part_id).first()
    if not part:
        raise HTTPException(status_code=404, detail="Part not found.")
    if not os.path.exists(part.local_docx_path):
        raise HTTPException(status_code=404, detail="Part file missing.")

    file_ext = os.path.splitext(part.local_docx_path)[1].lower()
    lines: list[str] = []

    if file_ext == ".typ":
        with open(part.local_docx_path, "r", encoding="utf-8") as f:
            for line in f:
                text = line.strip()
                if text:
                    lines.append(text)
    else:
        try:
            from docx import Document as DocxDocument
            doc = DocxDocument(part.local_docx_path)
            from docx.oxml.table import CT_Tbl
            from docx.oxml.text.paragraph import CT_P
            from docx.table import Table
            from docx.text.paragraph import Paragraph as DocxParagraph

            for child in doc.element.body.iterchildren():
                if isinstance(child, CT_P):
                    para = DocxParagraph(child, doc)
                    text = para.text.strip()
                    if text:
                        lines.append(text)
                elif isinstance(child, CT_Tbl):
                    tbl = Table(child, doc)
                    for row in tbl.rows:
                        row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                        if row_text:
                            lines.append(row_text)
        except ImportError:
            lines.append("Cannot preview legacy DOCX files. Python-docx is not installed.")

    if q:
        lowered = q.lower()
        lines = [line for line in lines if lowered in line.lower()]
    return {"lines": lines[:limit], "total": len(lines)}


@router.post("/{document_id}/merge", response_model=MergeResponse)
def merge_document(document_id: str, merge_request: MergeRequest, db: Session = Depends(get_db)):
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")

    query = db.query(ExportPart).filter(ExportPart.document_id == document_id)
    part_ids = list(merge_request.part_ids or [])
    if part_ids:
        query = query.filter(ExportPart.id.in_(part_ids))
    parts = query.order_by(ExportPart.part_number.asc()).all()
    if not parts:
        raise HTTPException(status_code=400, detail="No export parts available to merge.")

    validation = validate_merge(document, parts, document.chunks)
    if not validation["ok"]:
        raise HTTPException(status_code=400, detail=validation)

    try:
        merged_path = merge_document_parts(document, parts)
        document.merged_docx_path = str(merged_path)
        db.commit()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to merge document: {exc}") from exc

    return MergeResponse(
        status="success",
        filename=merged_path.name,
        download_url=f"/api/v1/documents/{document_id}/merged/download",
    )


@router.post("/{document_id}/merge-parts")
def merge_parts_endpoint(document_id: str, body: MergeRequest, db: Session = Depends(get_db)):
    from app.core.thread_runner import submit_merge_job

    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")

    part_map = {p.id: p for p in document.parts}
    part_ids = list(body.part_ids or [])
    if part_ids:
        ordered_ids = [pid for pid in part_ids if pid in part_map]
    else:
        ordered_ids = [p.id for p in sorted(document.parts, key=lambda p: p.part_number)]

    if not ordered_ids:
        raise HTTPException(status_code=400, detail="No valid parts to merge.")

    merge_job = MergeJob(
        document_id=document_id,
        status=MergeStatus.pending,
        part_count=len(ordered_ids),
        progress_percent=0.0,
        progress_message="Queued",
    )
    db.add(merge_job)
    db.commit()
    db.refresh(merge_job)

    submit_merge_job(document_id, merge_job.id, ordered_ids)

    return JSONResponse(
        status_code=202,
        content={
            "merge_job_id": merge_job.id,
            "status": "accepted",
            "message": "Merge started in background",
        },
    )


@router.get("/{document_id}/merge-status", response_model=MergeJobStatusResponse | None)
def get_merge_status(document_id: str, db: Session = Depends(get_db)):
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")

    merge_job = (
        db.query(MergeJob)
        .filter(MergeJob.document_id == document_id)
        .order_by(MergeJob.created_at.desc())
        .first()
    )

    if not merge_job:
        return None

    status_val = merge_job.status.value if hasattr(merge_job.status, "value") else str(merge_job.status)
    download_url = None
    if status_val == "COMPLETED" and merge_job.output_path:
        download_url = f"/api/v1/documents/{document_id}/merged/download"

    return MergeJobStatusResponse(
        merge_job_id=merge_job.id,
        document_id=document_id,
        status=status_val,
        progress_percent=merge_job.progress_percent or 0.0,
        progress_message=merge_job.progress_message,
        error_log=merge_job.error_log,
        download_url=download_url,
        created_at=merge_job.created_at,
        completed_at=merge_job.completed_at,
    )


@router.get("/{document_id}/merge-validation")
def get_merge_validation(document_id: str, db: Session = Depends(get_db)):
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")
    return validate_merge(document, document.parts, document.chunks)


@router.get("/system/health")
def get_system_health(db: Session = Depends(get_db)):
    now = time.monotonic()
    cached_value = _SYSTEM_HEALTH_CACHE.get("value")
    expires_at = _SYSTEM_HEALTH_CACHE.get("expires_at", 0.0)
    if cached_value is not None and isinstance(expires_at, float) and now < expires_at:
        return cached_value

    health = build_system_health(db)
    _SYSTEM_HEALTH_CACHE["value"] = health
    _SYSTEM_HEALTH_CACHE["expires_at"] = now + 15.0
    return health


@router.get("/{document_id}/merged/download")
def download_merged_document(document_id: str, db: Session = Depends(get_db)):
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document or not document.merged_docx_path:
        raise HTTPException(status_code=404, detail="Merged document not found.")
    merged_path = Path(document.merged_docx_path)
    if not merged_path.exists():
        raise HTTPException(status_code=404, detail="Merged file missing.")
    return FileResponse(
        path=str(merged_path),
        filename=merged_path.name,
        media_type="application/pdf",
    )


@router.get("/{document_id}/chunks/{chunk_id}/transformed")
def get_chunk_transformed(document_id: str, chunk_id: str, db: Session = Depends(get_db)):
    chunk = db.query(Chunk).filter(Chunk.id == chunk_id, Chunk.document_id == document_id).first()
    if not chunk:
        raise HTTPException(status_code=404, detail="Chunk not found.")

    result: dict = {
        "chunk_id": chunk_id,
        "chunk_index": chunk.chunk_index,
        "has_transform": False,
        "transform_stats": chunk.transform_stats,
        "transformed_text": None,
        "cleaned_text": None,
    }

    if chunk.cleaned_text_path:
        cp = Path(chunk.cleaned_text_path)
        if cp.exists():
            result["cleaned_text"] = cp.read_text(encoding="utf-8", errors="ignore")

    if chunk.transformed_text:
        result["has_transform"] = True
        result["transformed_text"] = chunk.transformed_text
    elif chunk.transformed_text_path:
        tp = Path(chunk.transformed_text_path)
        if tp.exists():
            result["has_transform"] = True
            result["transformed_text"] = tp.read_text(encoding="utf-8", errors="ignore")

    return result


@router.delete("/{document_id}")
def delete_document(document_id: str, db: Session = Depends(get_db)):
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")

    file_paths: list[Path] = []
    dir_paths: list[Path] = []

    if document.local_storage_path:
        file_paths.append(Path(document.local_storage_path))
    if document.manifest_path:
        file_paths.append(Path(document.manifest_path))
    if document.merged_docx_path:
        file_paths.append(Path(document.merged_docx_path))
    if document.storage_root:
        dir_paths.append(Path(document.storage_root))

    for part in document.parts:
        if part.local_docx_path:
            file_paths.append(Path(part.local_docx_path))

    db.delete(document)
    db.commit()

    for file_path in file_paths:
        try:
            if file_path.exists() and file_path.is_file():
                file_path.unlink()
        except OSError:
            pass

    for dir_path in dir_paths:
        try:
            if dir_path.exists() and dir_path.is_dir():
                shutil.rmtree(dir_path, ignore_errors=True)
        except OSError:
            pass

    return {"status": "success", "message": "Document deleted."}

@router.get("/test_escape")
def test_escape():
    from build_typst_book import escape_typst
    return {"escaped": escape_typst("<test>")}

@router.get("/test_escape_route")
def test_escape_route():
    import sys, os
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../..")))
    try:
        from build_typst_book import escape_typst
        return {"result": repr(escape_typst("<1 minute"))}
    except Exception as e:
        return {"error": str(e)}

@router.get("/test/escape-typst-now")
def test_escape_now():
    import sys, os
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../..")))
    try:
        from build_typst_book import escape_typst
        return {"result": repr(escape_typst("<1 minute"))}
    except Exception as e:
        return {"error": str(e)}
