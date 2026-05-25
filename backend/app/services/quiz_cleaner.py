"""Quiz / exam paper cleaner.

Removes assessment-platform metadata (Question Id, Question Type, Option Shuffling, ...),
de-duplicates Hindi translation copies of each question, and writes a clean PDF that
keeps only the question + options + diagrams.

Optionally, when an answer-key map is supplied, the correct option for each
question is rendered as a green box at the bottom of the question's page.
Questions whose IDs are not present in the key get a red warning box, and the
list of missing IDs is also printed on the cover.

Designed for PDFs exported from National Testing Agency / TCS iON style platforms,
where each question is rendered TWICE on disk (English meta + image, Hindi meta + image)
and the only "real" textual content on the page is metadata garbage. The actual question,
its options, and any diagram are baked into a raster image per language.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import fitz  # PyMuPDF


QUESTION_HEADER_RE = re.compile(r"Question\s+Number\s*:\s*(\d+)", re.IGNORECASE)
QUESTION_ID_RE = re.compile(r"Question\s+Id\s*:\s*(\d+)", re.IGNORECASE)

# --- Format 2: "PREVIEW QUESTION BANK(Dual)" / TCS internal preview ----------
# Each question header is two adjacent text blocks:
#   block N   : "Objective Question"
#   block N+1 : "<sr_no>" or "<sr_no> <question_id>" or "<question_id>"
# A single integer that is 5-7 digits long is treated as the question id.
OBJECTIVE_HEADER_RE = re.compile(r"Objective\s+Question\b", re.IGNORECASE)
QID_DIGIT_RE = re.compile(r"^(\d{5,7})$")
SR_NO_RE = re.compile(r"^(\d{1,4})$")
# Header text can be "1 703501" alone or "12 703512 2.0" with trailing marks.
SR_AND_QID_RE = re.compile(r"^(\d{1,4})\s+(\d{5,7})(?:\s|$)")
# Sometimes the qid arrives bundled with marks: "703512 2.0".
QID_AND_MARKS_RE = re.compile(r"^(\d{5,7})\s+\d+(?:\.\d+)?\s*$")
# Page chrome we want to skip while still expecting a question id (e.g. when
# the "Objective Question" marker sits at the bottom of a page and the
# numeric header is on the next page after a footer URL or page-break header).
PAGE_CHROME_RE = re.compile(
    r"^(file:///|https?://|"
    r"\d{1,2}/\d{1,2}/\d{2,4}[,\s]|"      # date stamp like "3/3/25, 1:39 PM..."
    r"3_Live_|"
    r"PREVIEW\s+QUESTION\s+BANK|"
    r"Module\s+Name\s*:|"
    r"Exam\s+Date\s*:|"
    r"Page\s+\d+\s*(of\s*\d+)?$)",
    re.IGNORECASE,
)
SECTION_HINTS = (
    "PART -",
    "PART-",
    "SECTION ID",
    "SECTION NUMBER",
    "GROUP NUMBER",
    "SUB-SECTION",
)
COVER_HINTS = (
    "QUESTION PAPER NAME",
    "TOTAL MARKS",
    "DURATION",
)
METADATA_NOISE_PATTERNS = (
    "Question Type",
    "Option Shuffling",
    "Display Question Number",
    "Is Question Mandatory",
    "Calculator",
    "Response Time",
    "Think Time",
    "Minimum Instruction Time",
    "Single Line",
    "Question Option",
    "Option Orientation",
    "Allowed Progression",
    "Number of Replay",
    "Play On Load",
    "Control Enable",
    "Time interval to replay",
    "Allow Volume Control",
    "Correct Marks",
    "Wrong Marks",
    "Notations :",
    "Options shown in green",
    "Options shown in red",
)


@dataclass
class _Block:
    kind: str  # "text" | "image"
    page_idx: int
    bbox: tuple[float, float, float, float]
    text: str = ""
    xref: int = 0
    width: int = 0
    height: int = 0


@dataclass
class _QuestionGroup:
    q_num: int
    q_id: str = ""
    images: list[_Block] = field(default_factory=list)


def _extract_blocks(doc: fitz.Document) -> list[_Block]:
    blocks: list[_Block] = []
    for page_idx in range(len(doc)):
        page = doc[page_idx]
        page_blocks: list[_Block] = []

        # Text blocks
        td = page.get_text("dict")
        for b in td.get("blocks", []):
            if b.get("type", 0) != 0:
                continue
            content_lines: list[str] = []
            for line in b.get("lines", []):
                line_text = "".join(span.get("text", "") for span in line.get("spans", []))
                if line_text:
                    content_lines.append(line_text)
            text = " ".join(content_lines).strip()
            if not text:
                continue
            page_blocks.append(
                _Block(
                    kind="text",
                    page_idx=page_idx,
                    bbox=tuple(b["bbox"]),
                    text=text,
                )
            )

        # Image blocks (via xref so we can extract bytes later)
        for info in page.get_image_info(xrefs=True):
            xref = info.get("xref", 0)
            if not xref:
                continue
            page_blocks.append(
                _Block(
                    kind="image",
                    page_idx=page_idx,
                    bbox=tuple(info.get("bbox", (0, 0, 0, 0))),
                    xref=xref,
                    width=info.get("width", 0) or 0,
                    height=info.get("height", 0) or 0,
                )
            )

        # Reading order on the page: top-to-bottom, then left-to-right
        page_blocks.sort(key=lambda b: (round(b.bbox[1], 1), round(b.bbox[0], 1)))
        blocks.extend(page_blocks)
    return blocks


def _is_pure_metadata(text: str) -> bool:
    """True when a text block is just exam-engine boilerplate (Question Id, Marks, ...)."""
    if not text:
        return True
    if QUESTION_HEADER_RE.search(text):
        return True
    hits = sum(1 for needle in METADATA_NOISE_PATTERNS if needle in text)
    if hits >= 2:
        return True
    if text.strip() in {"\xa0", "\xc2\xa0"}:
        return True
    return False


def _is_section_header(text: str) -> bool:
    upper = text.upper()
    return any(hint in upper for hint in SECTION_HINTS)


def _is_cover_text(text: str) -> bool:
    upper = text.upper()
    return any(hint in upper for hint in COVER_HINTS)


def _group_questions(blocks: Iterable[_Block]) -> tuple[list[_QuestionGroup], list[str]]:
    """Walk the block stream and group images per question header.

    Returns (question_groups, section_headers_in_order).
    """
    groups: list[_QuestionGroup] = []
    section_headers: list[str] = []
    current: _QuestionGroup | None = None

    for block in blocks:
        if block.kind == "text":
            text = block.text
            qmatch = QUESTION_HEADER_RE.search(text)
            if qmatch:
                if current is not None:
                    groups.append(current)
                qid_match = QUESTION_ID_RE.search(text)
                current = _QuestionGroup(
                    q_num=int(qmatch.group(1)),
                    q_id=qid_match.group(1) if qid_match else "",
                )
                continue
            # Pure metadata? Drop it entirely.
            if _is_pure_metadata(text):
                continue
            # Section / part headers we want to keep as visual dividers
            if _is_section_header(text) and current is None:
                section_headers.append(text.strip())
        elif block.kind == "image":
            if current is not None:
                current.images.append(block)
            # Pre-question images (logos, watermark) are intentionally dropped.

    if current is not None:
        groups.append(current)
    return groups, section_headers


def _group_questions_objective(
    blocks: list[_Block],
) -> tuple[list[_QuestionGroup], list[str]]:
    """Format 2 grouping (PREVIEW QUESTION BANK / "Objective Question" header).

    Each new question is signalled by a text block whose content matches
    "Objective Question". The very next text block (skipping the column-marks
    block on the right) carries the serial number and question id - either
    in one block ("1 703501") or split across two blocks ("1" then "703501").
    """
    groups: list[_QuestionGroup] = []
    section_headers: list[str] = []
    current: _QuestionGroup | None = None
    expecting_id = False  # True after we see "Objective Question"

    # Bring everything into a flat list so we can peek backwards if needed.
    bs = list(blocks)
    i = 0
    while i < len(bs):
        block = bs[i]
        if block.kind == "text":
            text = block.text.strip()
            if OBJECTIVE_HEADER_RE.search(text):
                # Commit the previous question and start a new one
                if current is not None:
                    groups.append(current)
                current = _QuestionGroup(q_num=len(groups) + 1, q_id="")
                expecting_id = True
                i += 1
                continue

            if expecting_id and current is not None:
                # Page chrome (URLs, timestamps, watermark lines) sometimes
                # appears between the "Objective Question" marker and the
                # actual numeric header when the question spans a page
                # boundary. Skip such lines without resetting expecting_id.
                if PAGE_CHROME_RE.match(text):
                    i += 1
                    continue

                # The header text might be "1 703501" in one block, or
                # "12 703512 2.0" with marks appended, or split as "1" then
                # later "703501". Look at this block first.
                m = SR_AND_QID_RE.match(text)
                if m:
                    current.q_num = int(m.group(1))
                    current.q_id = m.group(2)
                    expecting_id = False
                    i += 1
                    continue
                m = QID_AND_MARKS_RE.match(text)
                if m:
                    current.q_id = m.group(1)
                    expecting_id = False
                    i += 1
                    continue
                m = QID_DIGIT_RE.match(text)
                if m:
                    current.q_id = m.group(1)
                    expecting_id = False
                    i += 1
                    continue
                m = SR_NO_RE.match(text)
                if m:
                    # Save the serial number; keep waiting for the QID
                    # in a later block.
                    current.q_num = int(m.group(1))
                    i += 1
                    continue
                # Anything else means we've drifted past the header strip;
                # stop expecting an id.
                expecting_id = False

            # In format 2, lines like "A1", ":", "1", "2", "2.0" are all
            # noise that lives on the page chrome - ignore them silently.
        elif block.kind == "image":
            if current is not None:
                current.images.append(block)
        i += 1

    if current is not None:
        groups.append(current)
    return groups, section_headers


def _detect_format(blocks: list[_Block]) -> str:
    """Decide which question-paper format we're looking at.

    Returns "ntaion" for the 2025 NTA / TCS-iON style with explicit
    "Question Number : N Question Id : ..." lines, or "objective" for
    the "PREVIEW QUESTION BANK" / "Objective Question" table style used
    in some 2024 papers.
    """
    nta_hits = 0
    obj_hits = 0
    for b in blocks:
        if b.kind != "text":
            continue
        if QUESTION_HEADER_RE.search(b.text):
            nta_hits += 1
        if OBJECTIVE_HEADER_RE.search(b.text):
            obj_hits += 1
        if nta_hits >= 3 or obj_hits >= 3:
            break
    return "objective" if obj_hits > nta_hits else "ntaion"


def _dedupe_translations(groups: list[_QuestionGroup]) -> tuple[list[_QuestionGroup], int]:
    """Each question appears twice — English then Hindi. Keep the first."""
    seen: set[int] = set()
    kept: list[_QuestionGroup] = []
    dropped = 0
    for g in groups:
        if g.q_num in seen:
            dropped += 1
            continue
        # Skip "empty" groups that somehow have no images at all
        if not g.images:
            continue
        seen.add(g.q_num)
        kept.append(g)
    return kept, dropped


def _render_output_pdf(
    src: fitz.Document,
    kept: list[_QuestionGroup],
    section_headers: list[str],
    source_name: str,
    output_path: Path,
    answer_map: dict[str, dict] | None = None,
    answer_subject: str | None = None,
) -> dict:
    """Render the cleaned PDF.

    `answer_map` is an optional `{question_id: {"text": str, "kind": str}}` mapping.
    Returns extra stats: matched / missing question ids.
    """
    out = fitz.open()
    PAGE_W, PAGE_H = 595.0, 842.0  # A4 portrait, points
    MARGIN = 50.0
    AVAIL_W = PAGE_W - 2 * MARGIN

    matched: list[int] = []
    missing: list[tuple[int, str]] = []  # (q_num, q_id)

    # --- Cover ----------------------------------------------------------------
    cover = out.new_page(width=PAGE_W, height=PAGE_H)
    cover.insert_text(
        fitz.Point(MARGIN, MARGIN + 30),
        "Cleaned Quiz",
        fontsize=26,
        fontname="helv",
        color=(0.13, 0.13, 0.13),
    )
    cover.insert_text(
        fitz.Point(MARGIN, MARGIN + 60),
        source_name,
        fontsize=12,
        fontname="helv",
        color=(0.42, 0.42, 0.42),
    )
    summary_line = (
        f"{len(kept)} questions extracted - metadata removed - Hindi duplicates removed"
    )
    if answer_map is not None:
        summary_line += " - answer key attached"
    cover.insert_text(
        fitz.Point(MARGIN, MARGIN + 90),
        summary_line,
        fontsize=10,
        fontname="helv",
        color=(0.5, 0.5, 0.5),
    )
    if answer_subject:
        cover.insert_text(
            fitz.Point(MARGIN, MARGIN + 108),
            f"Answer key subject: {answer_subject}",
            fontsize=10,
            fontname="helv",
            color=(0.4, 0.55, 0.45),
        )
    y = MARGIN + 140
    if section_headers:
        cover.insert_text(
            fitz.Point(MARGIN, y),
            "Sections detected:",
            fontsize=11,
            fontname="helv",
            color=(0.13, 0.13, 0.13),
        )
        y += 18
        for header in section_headers[:20]:
            short = header.replace("\n", " ").strip()
            if len(short) > 90:
                short = short[:87] + "..."
            cover.insert_text(
                fitz.Point(MARGIN + 10, y),
                f"- {short}",
                fontsize=9,
                fontname="helv",
                color=(0.4, 0.4, 0.4),
            )
            y += 14
            if y > PAGE_H - MARGIN - 200:
                break

    # --- Question pages -------------------------------------------------------
    for g in kept:
        page = out.new_page(width=PAGE_W, height=PAGE_H)
        y = MARGIN
        page.insert_text(
            fitz.Point(MARGIN, y + 14),
            f"Question {g.q_num}",
            fontsize=14,
            fontname="helv",
            color=(0.13, 0.13, 0.13),
        )
        y += 28

        for img in g.images:
            try:
                data = src.extract_image(img.xref)
            except Exception:
                continue
            img_bytes = data.get("image")
            if not img_bytes:
                continue
            iw = data.get("width") or img.width or 1
            ih = data.get("height") or img.height or 1
            scale = min(1.0, AVAIL_W / iw) if iw else 1.0
            disp_w = iw * scale
            disp_h = ih * scale
            # Reserve space for the answer box (about 60pt) when an answer is expected
            reserve = 70 if answer_map is not None else 0
            if y + disp_h > PAGE_H - MARGIN - reserve:
                page = out.new_page(width=PAGE_W, height=PAGE_H)
                y = MARGIN
                page.insert_text(
                    fitz.Point(MARGIN, y + 12),
                    f"Question {g.q_num} (continued)",
                    fontsize=11,
                    fontname="helv",
                    color=(0.5, 0.5, 0.5),
                )
                y += 24
            rect = fitz.Rect(MARGIN, y, MARGIN + disp_w, y + disp_h)
            page.insert_image(rect, stream=img_bytes, keep_proportion=True)
            y += disp_h + 14

        # --- Answer footer on the last page of this question -----------------
        if answer_map is not None:
            ans = answer_map.get(g.q_id) if g.q_id else None
            if ans:
                matched.append(g.q_num)
                _draw_answer_box(page, MARGIN, AVAIL_W, ans["text"], found=True)
            else:
                missing.append((g.q_num, g.q_id or ""))
                _draw_answer_box(
                    page,
                    MARGIN,
                    AVAIL_W,
                    "Answer key not found for this question",
                    found=False,
                )

    # --- Append missing-IDs report onto the cover --------------------------
    if answer_map is not None and missing:
        # Re-fetch the cover page by index. PyMuPDF can invalidate the original
        # page reference once many subsequent pages have been written to the
        # same document.
        cover = out[0]
        cover.insert_text(
            fitz.Point(MARGIN, PAGE_H - MARGIN - 200),
            f"Warning: {len(missing)} question(s) had no entry in the answer key",
            fontsize=10,
            fontname="helv",
            color=(0.75, 0.2, 0.2),
        )
        ry = PAGE_H - MARGIN - 184
        for q_num, q_id in missing[:10]:
            cover.insert_text(
                fitz.Point(MARGIN + 10, ry),
                f"- Q{q_num} (id {q_id or 'unknown'})",
                fontsize=9,
                fontname="helv",
                color=(0.6, 0.2, 0.2),
            )
            ry += 13
        if len(missing) > 10:
            cover.insert_text(
                fitz.Point(MARGIN + 10, ry),
                f"... and {len(missing) - 10} more (see question pages)",
                fontsize=9,
                fontname="helv",
                color=(0.6, 0.2, 0.2),
            )

    out.save(str(output_path), deflate=True, garbage=4)
    out.close()

    return {
        "answers_matched": len(matched),
        "answers_missing": [{"q_num": n, "q_id": qid} for n, qid in missing],
    }


def _draw_answer_box(page, margin: float, avail_w: float, text: str, found: bool) -> None:
    """Draw a coloured answer box at the bottom of the current page."""
    box_h = 46.0
    page_rect = page.rect
    y_top = page_rect.height - margin - box_h
    rect = fitz.Rect(margin, y_top, margin + avail_w, y_top + box_h)
    if found:
        fill = (0.86, 0.96, 0.88)  # soft green
        border = (0.2, 0.55, 0.32)
        text_color = (0.08, 0.36, 0.18)
        title = "ANSWER KEY"
    else:
        fill = (0.99, 0.91, 0.91)  # soft red
        border = (0.78, 0.25, 0.25)
        text_color = (0.55, 0.13, 0.13)
        title = "ANSWER KEY NOT FOUND"
    page.draw_rect(rect, color=border, fill=fill, width=0.8, radius=0.06)
    page.insert_text(
        fitz.Point(rect.x0 + 12, rect.y0 + 16),
        title,
        fontsize=8,
        fontname="helv",
        color=border,
    )
    page.insert_text(
        fitz.Point(rect.x0 + 12, rect.y0 + 34),
        text,
        fontsize=12,
        fontname="hebo",
        color=text_color,
    )


def _parse_quiz(blocks: list[_Block]) -> tuple[list[_QuestionGroup], list[str], int, str]:
    """Detect the format and run the matching grouper.

    Returns (kept_groups, section_headers, translations_removed, format_name).
    For the "objective" format every question is unique, so there is nothing
    to dedupe; translations_removed is 0.
    """
    fmt = _detect_format(blocks)
    if fmt == "objective":
        groups, section_headers = _group_questions_objective(blocks)
        # No Hindi duplicates in this format - just drop empty groups.
        kept = [g for g in groups if g.images]
        # In the "PREVIEW QUESTION BANK(Dual)" format each question is rendered
        # as TWO stacked raster images: the English version on top, the Hindi
        # translation directly below it. The question text + options + any
        # diagram are baked INTO each image (the "A1: 1, A2: 2, ..." block at
        # the right is just label glyphs, the real options are inside the
        # raster). So for "Hindi-removed" output we keep just the FIRST image
        # of each question and drop everything below it.
        translations_removed = 0
        for g in kept:
            if len(g.images) >= 2:
                # Sort by vertical position so "first" really means top-most.
                g.images.sort(key=lambda im: (im.page_idx, round(im.bbox[1], 1)))
                translations_removed += len(g.images) - 1
                g.images = [g.images[0]]
        # Keep "kept" sequential numbering so answers stay aligned with q_ids.
        for idx, g in enumerate(kept, start=1):
            g.q_num = idx
        return kept, section_headers, translations_removed, fmt

    # Default: NTA / TCS-iON 2025 format with explicit "Question Number :" headers.
    groups, section_headers = _group_questions(blocks)
    kept, dropped = _dedupe_translations(groups)
    return kept, section_headers, dropped, fmt


class UnsupportedFormatError(Exception):
    """Raised when the question paper PDF cannot be parsed by any of our
    cleaners (e.g. it is a scanned/image-only PDF with no selectable text).
    The frontend surfaces the message to the user.
    """


def _looks_image_only(src: fitz.Document, sample_pages: int = 8) -> bool:
    """True when the first few pages have no selectable text at all but
    contain raster images. Used to refuse scanned PDFs early with a clear
    error instead of producing an empty cleaned file.
    """
    n = min(sample_pages, len(src))
    if n == 0:
        return False
    text_chars = 0
    images = 0
    for i in range(n):
        text_chars += len(src[i].get_text())
        images += len(src[i].get_images())
    # If first 8 pages have ZERO text but any images at all, treat as scanned.
    return text_chars == 0 and images > 0


def inspect_quiz_questions(input_path: str | Path) -> dict:
    """Lightweight pass over the quiz PDF that returns just the metadata needed
    for the preview step.

    Does NOT render the output PDF — used so the user can confirm subject /
    matching before paying for the heavier render pass.

    Raises UnsupportedFormatError when the PDF is a pure scan with no
    selectable text. A scanned PDF needs OCR before our cleaner can do
    anything reliable, and silently producing a wrong cleaned file would be
    actively harmful for exam material.
    """
    input_path = Path(input_path)

    # The CSIR text-PDF format has selectable text (no image-baked questions).
    # Detect it before opening the heavy block-extraction pipeline.
    src = fitz.open(str(input_path))
    try:
        if _looks_image_only(src):
            raise UnsupportedFormatError(
                "This PDF appears to be a scan or image-only PDF with no "
                "selectable text. Our cleaner needs the source PDF to "
                "contain at least the question metadata or option markers "
                "as text. Please upload the original text-based PDF, or "
                "run OCR on the file first."
            )

        from app.services import quiz_textpdf_cleaner

        if quiz_textpdf_cleaner.looks_like_textpdf_format(src):
            src.close()
            return quiz_textpdf_cleaner.inspect(input_path)

        blocks = _extract_blocks(src)
        kept, section_headers, dropped, fmt = _parse_quiz(blocks)
        return {
            "source_pages": len(src),
            "question_ids": [g.q_id for g in kept if g.q_id],
            "questions_kept": len(kept),
            "translations_removed": dropped,
            "sections_detected": len(section_headers),
            "format": fmt,
        }
    finally:
        if not src.is_closed:
            src.close()


def clean_quiz_pdf(
    input_path: str | Path,
    output_path: str | Path,
    answer_map: dict[str, dict] | None = None,
    answer_subject: str | None = None,
) -> dict:
    """Clean an exam-paper PDF.

    Removes metadata noise, drops Hindi translation duplicates of each question,
    and writes a new PDF containing only question images (with their options and
    embedded diagrams) one question per page.

    When `answer_map` is supplied (mapping question_id -> {"text": str, "kind": str}),
    a green answer box is drawn at the bottom of every matched question; missing
    questions get a red "Answer key not found" box and are listed on the cover.

    Returns a dict with stats.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    src = fitz.open(str(input_path))
    try:
        if _looks_image_only(src):
            raise UnsupportedFormatError(
                "This PDF appears to be a scan or image-only PDF with no "
                "selectable text. Our cleaner needs the source PDF to "
                "contain at least the question metadata or option markers "
                "as text. Please upload the original text-based PDF, or "
                "run OCR on the file first."
            )

        from app.services import quiz_textpdf_cleaner

        if quiz_textpdf_cleaner.looks_like_textpdf_format(src):
            src.close()
            return quiz_textpdf_cleaner.clean(
                input_path, output_path,
                answer_map=answer_map, answer_subject=answer_subject,
            )

        blocks = _extract_blocks(src)
        kept, section_headers, dropped, fmt = _parse_quiz(blocks)
        render_stats = _render_output_pdf(
            src, kept, section_headers, input_path.stem, output_path,
            answer_map=answer_map, answer_subject=answer_subject,
        )

        return {
            "input": str(input_path),
            "output": str(output_path),
            "source_pages": len(src),
            "questions_detected": len(kept),
            "questions_kept": len(kept),
            "translations_removed": dropped,
            "sections_detected": len(section_headers),
            "format": fmt,
            "answers_attached": answer_map is not None,
            "answers_matched": render_stats["answers_matched"],
            "answers_missing": render_stats["answers_missing"],
        }
    finally:
        if not src.is_closed:
            src.close()


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python -m app.services.quiz_cleaner <input.pdf> <output.pdf>")
        raise SystemExit(2)
    stats = clean_quiz_pdf(sys.argv[1], sys.argv[2])
    for k, v in stats.items():
        print(f"{k}: {v}")
