import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.document import (
    AssemblyMode,
    Chunk,
    ChunkStatus,
    Document,
    DocumentConfig,
    DraftStatus,
    ExportPart,
    ExportProfile,
    ManuscriptDraft,
    ManuscriptSection,
    ReviewStatus,
    SectionVersion,
)


HEADING_PATTERNS = [
    re.compile(r"^(CHAPTER\s+\d+[\.\:]?\s*.*)$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^(PART\s+[IVXLCDM\d]+[\.\:]?\s*.*)$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^(SECTION\s+\d+[\.\:]?\s*.*)$", re.IGNORECASE | re.MULTILINE),
]

APPENDIX_PATTERNS = [
    re.compile(r"^(APPENDIX\s*[A-Z]?[\.\:]?\s*.*)$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^(BIBLIOGRAPHY|REFERENCES|INDEX|GLOSSARY|NOTES)[\.\:]?\s*$", re.IGNORECASE | re.MULTILINE),
]


def _read_chunk_text(chunk: Chunk) -> Optional[str]:
    if chunk.cleaned_text_path and Path(chunk.cleaned_text_path).exists():
        return Path(chunk.cleaned_text_path).read_text(encoding="utf-8", errors="ignore")
    if chunk.raw_text_path and Path(chunk.raw_text_path).exists():
        return Path(chunk.raw_text_path).read_text(encoding="utf-8", errors="ignore")
    return None


def _is_appendix_content(text: str) -> bool:
    for pattern in APPENDIX_PATTERNS:
        if pattern.search(text):
            return True
    return False


def _normalize_headings(text: str) -> str:
    lines = text.splitlines()
    normalized = []
    for line in lines:
        stripped = line.strip()
        is_heading = any(p.match(stripped) for p in HEADING_PATTERNS)
        if is_heading:
            normalized.append(stripped.upper())
        else:
            normalized.append(line)
    return "\n".join(normalized)


def _extract_heading_title(text: str) -> Optional[str]:
    for pattern in HEADING_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1).strip()
    first_line = text.strip().splitlines()[0] if text.strip() else None
    if first_line and len(first_line) < 120:
        return first_line
    return None


def _add_chapter_break(text: str, chapter_number: int) -> str:
    heading = _extract_heading_title(text)
    if heading:
        header_line = f"\n{'=' * 60}\nCHAPTER {chapter_number}: {heading}\n{'=' * 60}\n"
    else:
        header_line = f"\n{'=' * 60}\nCHAPTER {chapter_number}\n{'=' * 60}\n"
    return header_line + text


def _add_numbered_headings(text: str, chapter_number: int) -> str:
    lines = text.splitlines()
    result = []
    subheading_counter = 0
    for line in lines:
        stripped = line.strip()
        is_heading = any(p.match(stripped) for p in HEADING_PATTERNS)
        if is_heading and subheading_counter == 0:
            result.append(line)
        elif is_heading:
            subheading_counter += 1
            result.append(f"{chapter_number}.{subheading_counter} {stripped}")
        else:
            result.append(line)
    return "\n".join(result)


def _build_front_matter_placeholder(document: Document, config: Optional[DocumentConfig]) -> str:
    title = (config.book_title if config else None) or document.filename
    lines = [
        "=" * 60,
        "FRONT MATTER",
        "=" * 60,
        "",
        f"[TITLE PAGE]",
        f"Title: {title}",
        "Author: [AUTHOR]",
        "Publisher: [PUBLISHER]",
        "Year: [YEAR]",
        "",
        "[COPYRIGHT PAGE]",
        "Copyright © [YEAR] [AUTHOR]. All rights reserved.",
        "",
        "[DEDICATION PAGE]",
        "For [DEDICATION]",
        "",
        "[TABLE OF CONTENTS]",
        "[TOC will be generated here]",
        "",
        "=" * 60,
    ]
    return "\n".join(lines)


def _build_back_matter(texts: List[str]) -> str:
    lines = [
        "",
        "=" * 60,
        "BACK MATTER",
        "=" * 60,
        "",
    ]
    for text in texts:
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def _get_chunk_part_map(db: Session, document_id: str) -> dict:
    parts = db.query(ExportPart).filter(ExportPart.document_id == document_id).all()
    return {part.part_number: part.id for part in parts}


def assemble_raw_merge(
    db: Session,
    document: Document,
    draft: ManuscriptDraft,
    chunks: List[Chunk],
    chunk_to_part: dict,
) -> None:
    order = 1
    for chunk in sorted(chunks, key=lambda c: c.chunk_index):
        text = _read_chunk_text(chunk)
        if text is None:
            text = f"[Chunk {chunk.chunk_index}: content not available]"

        section = ManuscriptSection(
            draft_id=draft.id,
            chunk_id=chunk.id,
            part_id=chunk_to_part.get(chunk.chunk_index),
            section_order=order,
            section_type="body",
            title=f"Chunk {chunk.chunk_index} (pages {chunk.page_start}-{chunk.page_end})",
            review_status=ReviewStatus.pending,
        )
        db.add(section)
        db.flush()

        version = SectionVersion(
            section_id=section.id,
            version_number=1,
            content=text,
            is_edited=False,
            edit_note="Machine-generated (raw merge)",
        )
        db.add(version)
        order += 1

    db.commit()


def assemble_structured(
    db: Session,
    document: Document,
    draft: ManuscriptDraft,
    chunks: List[Chunk],
    config: Optional[DocumentConfig],
    chunk_to_part: dict,
) -> None:
    order = 1

    front_matter_text = _build_front_matter_placeholder(document, config)
    front_section = ManuscriptSection(
        draft_id=draft.id,
        chunk_id=None,
        part_id=None,
        section_order=order,
        section_type="front_matter",
        title="Front Matter",
        review_status=ReviewStatus.pending,
    )
    db.add(front_section)
    db.flush()
    db.add(SectionVersion(
        section_id=front_section.id,
        version_number=1,
        content=front_matter_text,
        is_edited=False,
        edit_note="Machine-generated placeholder",
    ))
    order += 1

    body_chunks = []
    appendix_chunks = []

    for chunk in sorted(chunks, key=lambda c: c.chunk_index):
        text = _read_chunk_text(chunk)
        if text is None:
            text = f"[Chunk {chunk.chunk_index}: content not available]"
        if _is_appendix_content(text):
            appendix_chunks.append((chunk, text))
        else:
            body_chunks.append((chunk, text))

    for chunk, text in body_chunks:
        normalized_text = _normalize_headings(text)
        title = _extract_heading_title(normalized_text)

        section = ManuscriptSection(
            draft_id=draft.id,
            chunk_id=chunk.id,
            part_id=chunk_to_part.get(chunk.chunk_index),
            section_order=order,
            section_type="body",
            title=title or f"Section {order - 1}",
            review_status=ReviewStatus.pending,
        )
        db.add(section)
        db.flush()
        db.add(SectionVersion(
            section_id=section.id,
            version_number=1,
            content=normalized_text,
            is_edited=False,
            edit_note="Machine-generated (structured)",
        ))
        order += 1

    for chunk, text in appendix_chunks:
        normalized_text = _normalize_headings(text)
        title = _extract_heading_title(normalized_text) or "Appendix"

        section = ManuscriptSection(
            draft_id=draft.id,
            chunk_id=chunk.id,
            part_id=chunk_to_part.get(chunk.chunk_index),
            section_order=order,
            section_type="appendix",
            title=title,
            review_status=ReviewStatus.pending,
        )
        db.add(section)
        db.flush()
        db.add(SectionVersion(
            section_id=section.id,
            version_number=1,
            content=normalized_text,
            is_edited=False,
            edit_note="Machine-generated (appendix separation)",
        ))
        order += 1

    db.commit()


def assemble_publication_ready(
    db: Session,
    document: Document,
    draft: ManuscriptDraft,
    chunks: List[Chunk],
    config: Optional[DocumentConfig],
    chunk_to_part: dict,
) -> None:
    order = 1

    front_matter_text = _build_front_matter_placeholder(document, config)
    front_section = ManuscriptSection(
        draft_id=draft.id,
        chunk_id=None,
        part_id=None,
        section_order=order,
        section_type="front_matter",
        title="Front Matter",
        review_status=ReviewStatus.pending,
    )
    db.add(front_section)
    db.flush()
    db.add(SectionVersion(
        section_id=front_section.id,
        version_number=1,
        content=front_matter_text,
        is_edited=False,
        edit_note="Machine-generated placeholder",
    ))
    order += 1

    body_chunks = []
    appendix_chunks = []

    for chunk in sorted(chunks, key=lambda c: c.chunk_index):
        text = _read_chunk_text(chunk)
        if text is None:
            text = f"[Chunk {chunk.chunk_index}: content not available]"
        if _is_appendix_content(text):
            appendix_chunks.append((chunk, text))
        else:
            body_chunks.append((chunk, text))

    chapter_number = 1
    for chunk, text in body_chunks:
        normalized_text = _normalize_headings(text)
        normalized_text = _add_numbered_headings(normalized_text, chapter_number)
        chapter_text = _add_chapter_break(normalized_text, chapter_number)
        title = _extract_heading_title(text) or f"Chapter {chapter_number}"

        section = ManuscriptSection(
            draft_id=draft.id,
            chunk_id=chunk.id,
            part_id=chunk_to_part.get(chunk.chunk_index),
            section_order=order,
            section_type="chapter",
            title=title,
            review_status=ReviewStatus.pending,
        )
        db.add(section)
        db.flush()
        db.add(SectionVersion(
            section_id=section.id,
            version_number=1,
            content=chapter_text,
            is_edited=False,
            edit_note=f"Machine-generated (publication-ready, chapter {chapter_number})",
        ))
        order += 1
        chapter_number += 1

    if appendix_chunks:
        appendix_label = "A"
        for chunk, text in appendix_chunks:
            normalized_text = _normalize_headings(text)
            title = _extract_heading_title(normalized_text) or f"Appendix {appendix_label}"
            back_text = _build_back_matter([normalized_text])

            section = ManuscriptSection(
                draft_id=draft.id,
                chunk_id=chunk.id,
                part_id=chunk_to_part.get(chunk.chunk_index),
                section_order=order,
                section_type="back_matter",
                title=title,
                review_status=ReviewStatus.pending,
            )
            db.add(section)
            db.flush()
            db.add(SectionVersion(
                section_id=section.id,
                version_number=1,
                content=back_text,
                is_edited=False,
                edit_note=f"Machine-generated (back matter, Appendix {appendix_label})",
            ))
            order += 1
            appendix_label = chr(ord(appendix_label) + 1)

    db.commit()


def create_export_profile_defaults(db: Session, document: Document, config: Optional[DocumentConfig]) -> ExportProfile:
    existing = db.query(ExportProfile).filter(ExportProfile.document_id == document.id).first()
    if existing:
        return existing

    title = (config.book_title if config else None) or Path(document.filename).stem

    profile = ExportProfile(
        document_id=document.id,
        page_size="A4",
        margin_top_cm=2.54,
        margin_bottom_cm=2.54,
        margin_left_cm=2.54,
        margin_right_cm=2.54,
        heading_mapping={
            "H1": "Heading 1",
            "H2": "Heading 2",
            "H3": "Heading 3",
        },
        book_title=title,
        subtitle=None,
        author=None,
        institution=None,
        copyright_text=None,
        disclaimer=None,
        dedication=None,
        preface=None,
        acknowledgements=None,
        include_toc=True,
        toc_heading_levels=2,
        page_number_start=1,
        page_number_format="arabic",
        front_matter_sections={"copyright": True, "disclaimer": False, "dedication": False, "preface": False, "acknowledgements": False},
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def assemble_manuscript(
    db: Session,
    document: Document,
    mode: AssemblyMode,
) -> ManuscriptDraft:
    config = db.query(DocumentConfig).filter(DocumentConfig.document_id == document.id).first()

    create_export_profile_defaults(db, document, config)

    draft = ManuscriptDraft(
        document_id=document.id,
        assembly_mode=mode,
        status=DraftStatus.assembling,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)

    try:
        chunks = (
            db.query(Chunk)
            .filter(Chunk.document_id == document.id, Chunk.status == ChunkStatus.completed)
            .order_by(Chunk.chunk_index.asc())
            .all()
        )

        chunk_to_part = _get_chunk_part_map(db, document.id)

        if mode == AssemblyMode.raw_merge:
            assemble_raw_merge(db, document, draft, chunks, chunk_to_part)
        elif mode == AssemblyMode.structured:
            assemble_structured(db, document, draft, chunks, config, chunk_to_part)
        elif mode == AssemblyMode.publication_ready:
            assemble_publication_ready(db, document, draft, chunks, config, chunk_to_part)

        draft.status = DraftStatus.ready
        draft.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(draft)
    except Exception as exc:
        draft.status = DraftStatus.failed
        draft.error_log = str(exc)
        db.commit()
        raise

    return draft
