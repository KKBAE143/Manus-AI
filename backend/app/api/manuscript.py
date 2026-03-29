import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.models.document import (
    ApprovalStatus,
    AssemblyMode,
    Chunk,
    Document,
    DraftStatus,
    ExportProfile,
    ManuscriptDraft,
    ManuscriptSection,
    ReviewStatus,
    SectionVersion,
    UserEditAction,
)
from app.services.manuscript_assembler import assemble_manuscript, create_export_profile_defaults
from app.services.docx_exporter import export_manuscript_docx

router = APIRouter(tags=["manuscript"])


class AssembleRequest(BaseModel):
    mode: AssemblyMode = AssemblyMode.structured
    override_warnings: bool = False


class SectionUpdateRequest(BaseModel):
    content: str
    edit_note: Optional[str] = None


class FlagRequest(BaseModel):
    note: str


class UnlockRequest(BaseModel):
    reason: str


class ExportProfileUpdate(BaseModel):
    page_size: Optional[str] = None
    margin_top_cm: Optional[float] = None
    margin_bottom_cm: Optional[float] = None
    margin_left_cm: Optional[float] = None
    margin_right_cm: Optional[float] = None
    heading_mapping: Optional[Dict[str, str]] = None
    book_title: Optional[str] = None
    subtitle: Optional[str] = None
    author: Optional[str] = None
    edition: Optional[str] = None
    institution: Optional[str] = None
    isbn: Optional[str] = None
    copyright_year: Optional[int] = None
    copyright_text: Optional[str] = None
    disclaimer: Optional[str] = None
    dedication: Optional[str] = None
    preface: Optional[str] = None
    acknowledgements: Optional[str] = None
    include_toc: Optional[bool] = None
    toc_heading_levels: Optional[int] = None
    page_number_start: Optional[int] = None
    page_number_format: Optional[str] = None
    front_matter_sections: Optional[Dict[str, bool]] = None


class ExportRequest(BaseModel):
    format: str = "docx"
    section_order: Optional[List[str]] = None


def _section_version_dict(v: SectionVersion) -> Dict[str, Any]:
    return {
        "id": v.id,
        "version_number": v.version_number,
        "content": v.content,
        "is_edited": v.is_edited,
        "edit_note": v.edit_note,
        "created_at": v.created_at,
    }


def _section_dict(section: ManuscriptSection, include_content: bool = True, chunk: Optional[Any] = None) -> Dict[str, Any]:
    current = section.current_version
    result = {
        "id": section.id,
        "draft_id": section.draft_id,
        "chunk_id": section.chunk_id,
        "part_id": section.part_id,
        "section_order": section.section_order,
        "section_type": section.section_type,
        "title": section.title,
        "review_status": section.review_status.value if hasattr(section.review_status, "value") else str(section.review_status),
        "approval_status": section.approval_status.value if hasattr(section, "approval_status") and section.approval_status and hasattr(section.approval_status, "value") else (str(section.approval_status) if hasattr(section, "approval_status") and section.approval_status else "PENDING"),
        "flag_note": section.flag_note,
        "lock_reason": section.lock_reason,
        "version_count": len(section.versions),
        "created_at": section.created_at,
        "updated_at": section.updated_at,
    }
    if chunk:
        result["chunk_index"] = chunk.chunk_index
        result["chunk_stage"] = chunk.current_stage
        result["chunk_status"] = chunk.status.value if hasattr(chunk.status, "value") else str(chunk.status)
    if include_content and current:
        result["current_content"] = current.content
        result["current_version_number"] = current.version_number
    elif include_content:
        result["current_content"] = None
        result["current_version_number"] = None
    return result


def _draft_dict(draft: ManuscriptDraft, include_sections: bool = False) -> Dict[str, Any]:
    result = {
        "id": draft.id,
        "document_id": draft.document_id,
        "assembly_mode": draft.assembly_mode.value if hasattr(draft.assembly_mode, "value") else str(draft.assembly_mode),
        "status": draft.status.value if hasattr(draft.status, "value") else str(draft.status),
        "section_count": len(draft.sections),
        "error_log": draft.error_log,
        "created_at": draft.created_at,
        "updated_at": draft.updated_at,
    }
    if include_sections:
        result["sections"] = [_section_dict(s) for s in draft.sections]
    return result


def _profile_dict(profile: ExportProfile) -> Dict[str, Any]:
    return {
        "id": profile.id,
        "document_id": profile.document_id,
        "page_size": profile.page_size,
        "margin_top_cm": profile.margin_top_cm,
        "margin_bottom_cm": profile.margin_bottom_cm,
        "margin_left_cm": profile.margin_left_cm,
        "margin_right_cm": profile.margin_right_cm,
        "heading_mapping": profile.heading_mapping,
        "book_title": profile.book_title,
        "subtitle": profile.subtitle,
        "author": profile.author,
        "edition": profile.edition,
        "institution": profile.institution,
        "isbn": profile.isbn,
        "copyright_year": profile.copyright_year,
        "copyright_text": profile.copyright_text,
        "disclaimer": profile.disclaimer,
        "dedication": profile.dedication,
        "preface": profile.preface,
        "acknowledgements": profile.acknowledgements,
        "include_toc": profile.include_toc,
        "toc_heading_levels": profile.toc_heading_levels,
        "page_number_start": profile.page_number_start,
        "page_number_format": profile.page_number_format,
        "front_matter_sections": profile.front_matter_sections,
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }


@router.post("/api/v1/documents/{document_id}/assemble")
def start_assembly(document_id: str, request: AssembleRequest, db: Session = Depends(get_db)):
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")

    existing_draft = (
        db.query(ManuscriptDraft)
        .filter(ManuscriptDraft.document_id == document_id)
        .order_by(ManuscriptDraft.created_at.desc())
        .first()
    )
    if existing_draft and not request.override_warnings:
        sections = existing_draft.sections
        not_approved = [s for s in sections if s.review_status not in (ReviewStatus.approved, ReviewStatus.locked)]
        if not_approved:
            return {
                "warning": True,
                "pending_review_count": len(not_approved),
                "total_sections": len(sections),
                "message": f"{len(not_approved)} of {len(sections)} sections are not yet approved. Pass override_warnings=true to assemble anyway.",
            }

    draft = assemble_manuscript(db, document, request.mode)
    return _draft_dict(draft)


@router.get("/api/v1/documents/{document_id}/draft")
def get_draft(document_id: str, db: Session = Depends(get_db)):
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")

    draft = (
        db.query(ManuscriptDraft)
        .options(selectinload(ManuscriptDraft.sections).selectinload(ManuscriptSection.versions))
        .filter(ManuscriptDraft.document_id == document_id)
        .order_by(ManuscriptDraft.created_at.desc())
        .first()
    )
    if not draft:
        raise HTTPException(status_code=404, detail="No draft found for this document.")
    return _draft_dict(draft, include_sections=True)


@router.get("/api/v1/documents/{document_id}/draft/status")
def get_draft_assembly_status(document_id: str, db: Session = Depends(get_db)):
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")

    draft = (
        db.query(ManuscriptDraft)
        .filter(ManuscriptDraft.document_id == document_id)
        .order_by(ManuscriptDraft.created_at.desc())
        .first()
    )
    if not draft:
        return {"has_draft": False, "status": None, "draft_id": None}

    sections = draft.sections
    pending = sum(1 for s in sections if s.review_status == ReviewStatus.pending)
    reviewed = sum(1 for s in sections if s.review_status == ReviewStatus.reviewed)
    approved = sum(1 for s in sections if s.review_status == ReviewStatus.approved)
    locked = sum(1 for s in sections if s.review_status == ReviewStatus.locked)

    return {
        "has_draft": True,
        "draft_id": draft.id,
        "status": draft.status.value if hasattr(draft.status, "value") else str(draft.status),
        "assembly_mode": draft.assembly_mode.value if hasattr(draft.assembly_mode, "value") else str(draft.assembly_mode),
        "section_count": len(sections),
        "pending": pending,
        "reviewed": reviewed,
        "approved": approved,
        "locked": locked,
        "error_log": draft.error_log,
        "created_at": draft.created_at,
        "updated_at": draft.updated_at,
    }


@router.get("/api/v1/drafts/{draft_id}/sections")
def list_sections(draft_id: str, db: Session = Depends(get_db)):
    draft = db.query(ManuscriptDraft).filter(ManuscriptDraft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found.")
    sections = (
        db.query(ManuscriptSection)
        .options(selectinload(ManuscriptSection.versions))
        .filter(ManuscriptSection.draft_id == draft_id)
        .order_by(ManuscriptSection.section_order.asc())
        .all()
    )
    return [_section_dict(s) for s in sections]


@router.get("/api/v1/sections/{section_id}")
def get_section(section_id: str, db: Session = Depends(get_db)):
    section = (
        db.query(ManuscriptSection)
        .options(selectinload(ManuscriptSection.versions))
        .filter(ManuscriptSection.id == section_id)
        .first()
    )
    if not section:
        raise HTTPException(status_code=404, detail="Section not found.")
    return _section_dict(section, include_content=True)


@router.put("/api/v1/sections/{section_id}")
def update_section(section_id: str, request: SectionUpdateRequest, db: Session = Depends(get_db)):
    section = db.query(ManuscriptSection).filter(ManuscriptSection.id == section_id).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section not found.")

    if section.review_status == ReviewStatus.locked:
        raise HTTPException(status_code=409, detail="Section is locked and cannot be edited.")

    current = section.current_version
    previous_content = current.content if current else None
    next_version_number = (max(v.version_number for v in section.versions) + 1) if section.versions else 1

    new_version = SectionVersion(
        section_id=section.id,
        version_number=next_version_number,
        content=request.content,
        is_edited=True,
        edit_note=request.edit_note or "User edit",
    )
    db.add(new_version)

    action = UserEditAction(
        section_id=section.id,
        version_id=None,
        action_type="update",
        previous_content=previous_content,
        new_content=request.content,
        note=request.edit_note,
    )
    db.add(action)

    if section.review_status == ReviewStatus.approved:
        section.review_status = ReviewStatus.reviewed

    section.updated_at = datetime.utcnow()
    db.commit()
    db.flush()

    action.version_id = new_version.id
    db.commit()

    return _section_dict(section, include_content=True)


@router.get("/api/v1/sections/{section_id}/history")
def get_section_history(section_id: str, db: Session = Depends(get_db)):
    section = db.query(ManuscriptSection).filter(ManuscriptSection.id == section_id).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section not found.")
    return {
        "section_id": section_id,
        "versions": [_section_version_dict(v) for v in section.versions],
    }


@router.post("/api/v1/sections/{section_id}/approve")
def approve_section(section_id: str, db: Session = Depends(get_db)):
    section = db.query(ManuscriptSection).filter(ManuscriptSection.id == section_id).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section not found.")

    if section.review_status == ReviewStatus.locked:
        raise HTTPException(status_code=409, detail="Section is locked.")

    section.review_status = ReviewStatus.approved
    section.flag_note = None
    section.updated_at = datetime.utcnow()

    action = UserEditAction(
        section_id=section.id,
        action_type="approve",
        note="Section approved",
    )
    db.add(action)
    db.commit()
    return {"section_id": section_id, "review_status": "APPROVED"}


@router.post("/api/v1/sections/{section_id}/lock")
def lock_section(section_id: str, db: Session = Depends(get_db)):
    section = db.query(ManuscriptSection).filter(ManuscriptSection.id == section_id).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section not found.")

    action = UserEditAction(
        section_id=section.id,
        action_type="lock",
        note="Section locked",
    )
    db.add(action)
    section.review_status = ReviewStatus.locked
    section.updated_at = datetime.utcnow()
    db.commit()
    return {"section_id": section_id, "review_status": "LOCKED"}


@router.post("/api/v1/sections/{section_id}/flag")
def flag_section(section_id: str, request: FlagRequest, db: Session = Depends(get_db)):
    section = db.query(ManuscriptSection).filter(ManuscriptSection.id == section_id).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section not found.")

    if section.review_status == ReviewStatus.locked:
        raise HTTPException(status_code=409, detail="Section is locked and cannot be flagged.")

    section.review_status = ReviewStatus.reviewed
    section.flag_note = request.note
    section.updated_at = datetime.utcnow()

    action = UserEditAction(
        section_id=section.id,
        action_type="flag",
        note=request.note,
    )
    db.add(action)
    db.commit()
    return _section_dict(section, include_content=False)


@router.post("/api/v1/sections/{section_id}/unlock")
def unlock_section(section_id: str, request: UnlockRequest, db: Session = Depends(get_db)):
    section = db.query(ManuscriptSection).filter(ManuscriptSection.id == section_id).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section not found.")

    section.review_status = ReviewStatus.reviewed
    section.lock_reason = request.reason
    section.updated_at = datetime.utcnow()

    action = UserEditAction(
        section_id=section.id,
        action_type="unlock",
        note=request.reason,
    )
    db.add(action)
    db.commit()
    return _section_dict(section, include_content=False)


@router.get("/api/v1/documents/{document_id}/review-queue")
def get_document_review_queue(document_id: str, db: Session = Depends(get_db)):
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")

    draft = (
        db.query(ManuscriptDraft)
        .filter(ManuscriptDraft.document_id == document_id)
        .order_by(ManuscriptDraft.created_at.desc())
        .first()
    )
    if not draft:
        return {"document_id": document_id, "filename": document.filename, "sections": [], "total": 0}

    sections = (
        db.query(ManuscriptSection)
        .options(selectinload(ManuscriptSection.versions))
        .filter(ManuscriptSection.draft_id == draft.id)
        .order_by(ManuscriptSection.section_order.asc())
        .all()
    )

    chunk_map: Dict[str, Any] = {}
    chunk_ids = [s.chunk_id for s in sections if s.chunk_id]
    if chunk_ids:
        chunks = db.query(Chunk).filter(Chunk.id.in_(chunk_ids)).all()
        chunk_map = {c.id: c for c in chunks}

    return {
        "document_id": document_id,
        "filename": document.filename,
        "draft_id": draft.id,
        "sections": [_section_dict(s, include_content=False, chunk=chunk_map.get(s.chunk_id) if s.chunk_id else None) for s in sections],
        "total": len(sections),
        "approved_count": sum(1 for s in sections if s.review_status in (ReviewStatus.approved, ReviewStatus.locked)),
    }


@router.get("/api/v1/review-queue")
def get_global_review_queue(db: Session = Depends(get_db)):
    drafts = (
        db.query(ManuscriptDraft)
        .options(selectinload(ManuscriptDraft.sections).selectinload(ManuscriptSection.versions))
        .order_by(ManuscriptDraft.created_at.desc())
        .all()
    )
    seen_docs: set = set()
    items = []
    for draft in drafts:
        if draft.document_id in seen_docs:
            continue
        seen_docs.add(draft.document_id)
        document = draft.document
        if not document:
            continue

        sections = draft.sections
        chunk_map: Dict[str, Any] = {}
        if sections:
            chunk_ids = [s.chunk_id for s in sections if s.chunk_id]
            if chunk_ids:
                chunks = db.query(Chunk).filter(Chunk.id.in_(chunk_ids)).all()
                chunk_map = {c.id: c for c in chunks}

        for section in sections:
            chunk = chunk_map.get(section.chunk_id) if section.chunk_id else None
            items.append({
                **_section_dict(section, include_content=False, chunk=chunk),
                "document_id": document.id,
                "document_filename": document.filename,
            })

    return {
        "items": items,
        "total": len(items),
        "approved_count": sum(1 for it in items if it["review_status"] in ("APPROVED", "LOCKED")),
    }


@router.get("/api/v1/documents/{document_id}/export-profile")
def get_export_profile(document_id: str, db: Session = Depends(get_db)):
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")

    profile = db.query(ExportProfile).filter(ExportProfile.document_id == document_id).first()
    if not profile:
        from app.models.document import DocumentConfig
        config = db.query(DocumentConfig).filter(DocumentConfig.document_id == document_id).first()
        profile = create_export_profile_defaults(db, document, config)

    return _profile_dict(profile)


@router.put("/api/v1/documents/{document_id}/export-profile")
def update_export_profile(document_id: str, request: ExportProfileUpdate, db: Session = Depends(get_db)):
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")

    profile = db.query(ExportProfile).filter(ExportProfile.document_id == document_id).first()
    if not profile:
        from app.models.document import DocumentConfig
        config = db.query(DocumentConfig).filter(DocumentConfig.document_id == document_id).first()
        profile = create_export_profile_defaults(db, document, config)

    update_data = request.model_dump(exclude_none=True)
    for key, value in update_data.items():
        setattr(profile, key, value)

    profile.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(profile)
    return _profile_dict(profile)


@router.post("/api/v1/documents/{document_id}/assemble-sections")
def reorder_sections(document_id: str, request: ExportRequest, db: Session = Depends(get_db)):
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")

    draft = (
        db.query(ManuscriptDraft)
        .filter(ManuscriptDraft.document_id == document_id)
        .order_by(ManuscriptDraft.created_at.desc())
        .first()
    )
    if not draft:
        raise HTTPException(status_code=404, detail="No draft found for this document.")

    if request.section_order:
        sections = {s.id: s for s in draft.sections}
        for i, section_id in enumerate(request.section_order):
            if section_id in sections:
                sections[section_id].section_order = i + 1
                sections[section_id].updated_at = datetime.utcnow()
        db.commit()

    db.refresh(draft)
    return _draft_dict(draft, include_sections=True)


@router.post("/api/v1/documents/{document_id}/export")
def export_document(document_id: str, request: ExportRequest, db: Session = Depends(get_db)):
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")

    draft = (
        db.query(ManuscriptDraft)
        .filter(ManuscriptDraft.document_id == document_id)
        .order_by(ManuscriptDraft.created_at.desc())
        .first()
    )
    if not draft:
        raise HTTPException(status_code=404, detail="No draft found for this document.")

    profile = db.query(ExportProfile).filter(ExportProfile.document_id == document_id).first()
    if not profile:
        from app.models.document import DocumentConfig
        config = db.query(DocumentConfig).filter(DocumentConfig.document_id == document_id).first()
        profile = create_export_profile_defaults(db, document, config)

    try:
        docx_path = export_manuscript_docx(document, draft, profile, request.section_order)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Export failed: {exc}")

    if request.format == "pdf":
        libreoffice_bin = shutil.which("libreoffice") or shutil.which("soffice")
        if not libreoffice_bin:
            raise HTTPException(
                status_code=422,
                detail="PDF export requires LibreOffice to be installed on the server. Please export as DOCX instead."
            )
        pdf_dir = Path(docx_path).parent
        try:
            result = subprocess.run(
                [libreoffice_bin, "--headless", "--convert-to", "pdf", "--outdir", str(pdf_dir), str(docx_path)],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode != 0:
                raise HTTPException(status_code=500, detail=f"LibreOffice conversion failed: {result.stderr}")
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=500, detail="PDF conversion timed out.")

        pdf_path = pdf_dir / (Path(docx_path).stem + ".pdf")
        if not pdf_path.exists():
            raise HTTPException(status_code=500, detail="PDF file not found after conversion.")

        safe_filename = (profile.book_title or document.filename).replace(" ", "_") + ".pdf"
        return FileResponse(
            path=str(pdf_path),
            media_type="application/pdf",
            filename=safe_filename,
        )

    safe_filename = (profile.book_title or document.filename).replace(" ", "_") + ".docx"
    return FileResponse(
        path=str(docx_path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=safe_filename,
    )
