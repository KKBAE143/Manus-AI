"""Quiz cleaner API.

Workflow:

1. POST /api/v1/quiz/preview     - upload question paper (+ optional key),
                                   server inspects both files and returns the
                                   detected subject, ID match counts, missing
                                   IDs and any parser warnings. Files are kept
                                   in a temp staging area keyed by a job id.

2. POST /api/v1/quiz/confirm     - user confirms; server runs the cleaner with
                                   the staged files and writes the final PDF
                                   into the library.

3. GET  /api/v1/quiz/library     - list every cleaned PDF.
4. GET  /api/v1/quiz/{id}/download         - download a single result.
5. POST /api/v1/quiz/library/bulk-download - download a ZIP of selected (or all)
                                             results.
6. DELETE /api/v1/quiz/{id}      - delete a result.
"""

from __future__ import annotations

import io
import json
import shutil
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.core.config import settings
from app.services.answer_key_parser import (
    AnswerEntry,
    SubjectAnswers,
    format_answer_text,
    match_subject_for_qids,
    parse_answer_key,
)
from app.services.quiz_cleaner import clean_quiz_pdf, inspect_quiz_questions
from app.services import hf_storage_sync

router = APIRouter(prefix="/api/v1/quiz", tags=["quiz"])

QUIZ_ROOT = Path(settings.STORAGE_ROOT) / "quiz"
STAGING_DIR = QUIZ_ROOT / "_staging"
LIBRARY_DIR = QUIZ_ROOT / "library"
QUIZ_ROOT.mkdir(parents=True, exist_ok=True)
STAGING_DIR.mkdir(parents=True, exist_ok=True)
LIBRARY_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- helpers ---

def _safe_name(name: str) -> str:
    return Path(name).name


def _entry_to_payload(e: AnswerEntry) -> dict:
    return {"text": format_answer_text(e), "kind": e.kind, "raw": e.raw}


def _build_answer_map(subj: SubjectAnswers) -> dict[str, dict]:
    return {qid: _entry_to_payload(entry) for qid, entry in subj.entries.items()}


def _read_meta(job_dir: Path) -> dict:
    meta_path = job_dir / "meta.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="Result not found")
    return json.loads(meta_path.read_text(encoding="utf-8"))


def _write_meta(job_dir: Path, meta: dict) -> None:
    (job_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


# ------------------------------------------------------------- preview ----

@router.post("/preview")
async def preview_quiz(
    quiz_file: UploadFile = File(..., description="Question paper PDF"),
    key_file: Optional[UploadFile] = File(None, description="Answer key PDF (optional)"),
):
    if not quiz_file.filename or not quiz_file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Question paper must be a PDF.")
    if key_file and key_file.filename and not key_file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Answer key must be a PDF.")

    job_id = uuid.uuid4().hex[:12]
    job_dir = STAGING_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    quiz_name = _safe_name(quiz_file.filename)
    quiz_path = job_dir / f"quiz__{quiz_name}"
    with quiz_path.open("wb") as fh:
        shutil.copyfileobj(quiz_file.file, fh)

    key_path = None
    if key_file is not None and key_file.filename:
        key_name = _safe_name(key_file.filename)
        key_path = job_dir / f"key__{key_name}"
        with key_path.open("wb") as fh:
            shutil.copyfileobj(key_file.file, fh)

    # Inspect quiz to get question ids
    try:
        quiz_info = inspect_quiz_questions(quiz_path)
    except Exception as exc:  # noqa: BLE001
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"Could not parse quiz PDF: {exc}") from exc

    response: dict = {
        "job_id": job_id,
        "quiz_filename": quiz_name,
        "key_filename": _safe_name(key_file.filename) if key_file and key_file.filename else None,
        "quiz_stats": {
            "source_pages": quiz_info["source_pages"],
            "questions_kept": len(quiz_info["question_ids"]),
            "translations_removed": quiz_info["translations_removed"],
            "sections_detected": quiz_info["sections_detected"],
        },
        "answer_key": None,
    }

    # Persist preview metadata
    preview_meta = {
        "job_id": job_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "quiz_path": str(quiz_path),
        "key_path": str(key_path) if key_path else None,
        "quiz_filename": quiz_name,
        "key_filename": response["key_filename"],
        "quiz_stats": response["quiz_stats"],
        "question_ids": quiz_info["question_ids"],
    }

    if key_path is not None:
        try:
            parsed = parse_answer_key(key_path)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"Could not parse answer key PDF: {exc}") from exc

        best_subj, counts = match_subject_for_qids(parsed, quiz_info["question_ids"])
        if best_subj is None or counts.get(best_subj.subject_code, 0) == 0:
            response["answer_key"] = {
                "matched_subject": None,
                "subject_match_counts": counts,
                "warnings": parsed["warnings"]
                + ["No subject in the answer key matched any question id from the paper."],
                "missing_ids": [],
                "matched_count": 0,
                "subjects_in_key": [
                    {"code": parsed["subjects"][c].subject_code, "name": parsed["subjects"][c].subject_name}
                    for c in parsed["subject_order"]
                ],
            }
        else:
            qid_set = set(quiz_info["question_ids"])
            matched_ids = [q for q in quiz_info["question_ids"] if q in best_subj.entries]
            missing_ids = [q for q in quiz_info["question_ids"] if q not in best_subj.entries]
            extra_in_key = [q for q in best_subj.entries if q not in qid_set]
            response["answer_key"] = {
                "matched_subject": {
                    "code": best_subj.subject_code,
                    "name": best_subj.subject_name,
                    "total_entries": len(best_subj.entries),
                },
                "subject_match_counts": counts,
                "matched_count": len(matched_ids),
                "missing_ids": missing_ids,
                "extra_ids_in_key": extra_in_key[:50],
                "extra_ids_count": len(extra_in_key),
                "warnings": parsed["warnings"],
                "subjects_in_key": [
                    {"code": parsed["subjects"][c].subject_code, "name": parsed["subjects"][c].subject_name}
                    for c in parsed["subject_order"]
                ],
                "answer_kinds_breakdown": _kind_breakdown(best_subj),
                "preview_examples": _preview_examples(best_subj, quiz_info["question_ids"]),
            }
            preview_meta["selected_subject_code"] = best_subj.subject_code

    _write_meta(job_dir, preview_meta)
    return JSONResponse(response)


def _kind_breakdown(subj: SubjectAnswers) -> dict[str, int]:
    out: dict[str, int] = {}
    for e in subj.entries.values():
        out[e.kind] = out.get(e.kind, 0) + 1
    return out


def _preview_examples(subj: SubjectAnswers, qids: list[str], limit: int = 5) -> list[dict]:
    """Return a few example (qid, raw, formatted_text) tuples for UI confidence."""
    out: list[dict] = []
    for q in qids:
        e = subj.entries.get(q)
        if not e:
            continue
        out.append({"q_id": q, "raw": e.raw, "text": format_answer_text(e), "kind": e.kind})
        if len(out) >= limit:
            break
    return out


# ------------------------------------------------------------- confirm ----

class ConfirmRequest(BaseModel):
    job_id: str
    subject_code: Optional[str] = None  # override; default = auto-detected
    proceed_without_key: bool = False    # allow finishing without the key entirely


@router.post("/confirm")
async def confirm_quiz(payload: ConfirmRequest = Body(...)):
    job_dir = STAGING_DIR / payload.job_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="Preview job not found or expired")
    meta = _read_meta(job_dir)

    quiz_path = Path(meta["quiz_path"])
    key_path = Path(meta["key_path"]) if meta.get("key_path") else None

    if not quiz_path.exists():
        raise HTTPException(status_code=410, detail="Staged quiz file missing")

    answer_map: dict[str, dict] | None = None
    answer_subject_str: str | None = None

    if key_path is not None and not payload.proceed_without_key:
        if not key_path.exists():
            raise HTTPException(status_code=410, detail="Staged answer key file missing")
        parsed = parse_answer_key(key_path)
        if payload.subject_code:
            subj = parsed["subjects"].get(payload.subject_code)
            if subj is None:
                raise HTTPException(status_code=400, detail=f"Subject {payload.subject_code} not in key")
        else:
            subj, _ = match_subject_for_qids(parsed, meta["question_ids"])
            if subj is None:
                raise HTTPException(status_code=400, detail="No subject overlap in key")
        answer_map = _build_answer_map(subj)
        answer_subject_str = f"({subj.subject_code}) {subj.subject_name}"

    # Move to library
    result_id = uuid.uuid4().hex[:12]
    result_dir = LIBRARY_DIR / result_id
    result_dir.mkdir(parents=True, exist_ok=True)

    base_stem = Path(meta["quiz_filename"]).stem
    suffix = "_with_key" if answer_map is not None else "_cleaned"
    output_name = f"{base_stem}{suffix}.pdf"
    output_path = result_dir / output_name

    try:
        stats = clean_quiz_pdf(
            quiz_path,
            output_path,
            answer_map=answer_map,
            answer_subject=answer_subject_str,
        )
    except Exception as exc:  # noqa: BLE001
        shutil.rmtree(result_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Cleaner failed: {exc}") from exc

    record = {
        "id": result_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_filename": meta["quiz_filename"],
        "key_filename": meta.get("key_filename"),
        "output_filename": output_name,
        "answers_attached": stats["answers_attached"],
        "answer_subject": answer_subject_str,
        "stats": {
            "source_pages": stats["source_pages"],
            "questions_kept": stats["questions_kept"],
            "translations_removed": stats["translations_removed"],
            "sections_detected": stats["sections_detected"],
            "answers_matched": stats["answers_matched"],
            "answers_missing_count": len(stats["answers_missing"]),
            "answers_missing": stats["answers_missing"],
        },
    }
    _write_meta(result_dir, record)

    # Mirror this entry to the private HF dataset (no-op when sync is off).
    hf_storage_sync.upload_entry_async(result_dir, f"library/{result_id}")

    # Clean staging
    shutil.rmtree(job_dir, ignore_errors=True)

    return JSONResponse({**record, "download_url": f"/api/v1/quiz/{result_id}/download"})


# ------------------------------------------------------------- library ----

@router.get("/library")
def list_library():
    items: list[dict] = []
    for sub in sorted(LIBRARY_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True) if LIBRARY_DIR.exists() else []:
        if not sub.is_dir():
            continue
        meta_file = sub / "meta.json"
        if not meta_file.exists():
            continue
        try:
            rec = json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        out_file = sub / rec.get("output_filename", "")
        size = out_file.stat().st_size if out_file.exists() else 0
        items.append(
            {
                **rec,
                "size_bytes": size,
                "download_url": f"/api/v1/quiz/{rec['id']}/download",
            }
        )
    return {"items": items, "count": len(items)}


@router.get("/{result_id}/download")
def download_result(result_id: str):
    job_dir = LIBRARY_DIR / result_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="Result not found")
    rec = _read_meta(job_dir)
    out = job_dir / rec["output_filename"]
    if not out.exists():
        raise HTTPException(status_code=404, detail="Output PDF missing")
    return FileResponse(path=str(out), media_type="application/pdf", filename=rec["output_filename"])


@router.delete("/{result_id}")
def delete_result(result_id: str):
    job_dir = LIBRARY_DIR / result_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="Result not found")
    shutil.rmtree(job_dir, ignore_errors=True)
    # Mirror the delete to the HF dataset too (no-op when sync is off).
    hf_storage_sync.delete_entry_async(f"library/{result_id}")
    return {"status": "deleted", "id": result_id}


class BulkDownloadRequest(BaseModel):
    ids: Optional[List[str]] = None  # None or empty = all


@router.post("/library/bulk-download")
def bulk_download(payload: BulkDownloadRequest = Body(default=BulkDownloadRequest())):
    requested = set(payload.ids or [])
    candidates: list[Path] = []
    for sub in LIBRARY_DIR.iterdir() if LIBRARY_DIR.exists() else []:
        if not sub.is_dir():
            continue
        meta_file = sub / "meta.json"
        if not meta_file.exists():
            continue
        if requested and sub.name not in requested:
            continue
        candidates.append(sub)

    if not candidates:
        raise HTTPException(status_code=404, detail="No matching results to bundle")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for sub in candidates:
            try:
                rec = json.loads((sub / "meta.json").read_text(encoding="utf-8"))
            except Exception:
                continue
            out = sub / rec["output_filename"]
            if not out.exists():
                continue
            arcname = f"{rec['output_filename']}"
            # Avoid duplicates
            base, ext = arcname.rsplit(".", 1)
            n = 1
            while arcname in zf.namelist():
                arcname = f"{base}_{n}.{ext}"
                n += 1
            zf.write(out, arcname=arcname)

    buf.seek(0)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"quiz_library_{ts}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=\"{fname}\""},
    )
