import json
import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

import fitz

logger = logging.getLogger(__name__)

CHAPTER_PATTERNS = [
    re.compile(r"^\s*CHAPTER\s+\d+", re.I),
    re.compile(r"^\s*SECTION\s+\d+", re.I),
    re.compile(r"^\s*MODULE\s+\d+", re.I),
    re.compile(r"^\s*UNIT\s+\d+", re.I),
    re.compile(r"^\s*PART\s+(?:[IVXLCDM]+|\d+)\b", re.I),
]


@dataclass
class ChapterBoundary:
    page: int
    title: str
    confidence: float


def _get_median_body_size(page) -> float:
    sizes = []
    try:
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        for block in blocks:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    size = span.get("size", 0)
                    text = span.get("text", "").strip()
                    if size > 0 and len(text) > 3:
                        sizes.append(size)
    except Exception:
        pass
    if not sizes:
        return 12.0
    sizes.sort()
    return sizes[len(sizes) // 2]


def _is_heading_span(text: str, size: float, body_size: float, y_rel: float):
    if not text.strip():
        return False, 0.0

    size_ratio = size / body_size if body_size > 0 else 1.0
    pattern_match = any(p.match(text.strip()) for p in CHAPTER_PATTERNS)
    if pattern_match:
        return True, 0.95
    if y_rel < 0.4 and size_ratio >= 1.3:
        return True, 0.7
    if y_rel < 0.2 and size_ratio >= 1.5:
        return True, 0.65
    return False, 0.0


def detect_chapter_boundaries(pdf, start_page: int, end_page: int, max_pages: int = None) -> List[ChapterBoundary]:
    total_to_scan = end_page - start_page + 1
    step = 1
    if max_pages and total_to_scan > max_pages:
        step = max(1, total_to_scan // max_pages)

    pages_to_scan = list(range(start_page, end_page + 1, step))

    sample_pages = pages_to_scan[:: max(1, len(pages_to_scan) // 20)][:20]
    body_sizes = []
    for pg_num in sample_pages:
        if 1 <= pg_num <= len(pdf):
            s = _get_median_body_size(pdf[pg_num - 1])
            if s > 0:
                body_sizes.append(s)
    body_size = sorted(body_sizes)[len(body_sizes) // 2] if body_sizes else 12.0

    boundaries: List[ChapterBoundary] = []

    for pg_num in pages_to_scan:
        if not (1 <= pg_num <= len(pdf)):
            continue
        page = pdf[pg_num - 1]
        page_height = page.rect.height or 1.0

        try:
            blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        except Exception:
            continue

        best_title = None
        best_conf = 0.0

        for block in blocks:
            block_y = block.get("bbox", [0, 0, 0, 0])[1]
            y_rel = block_y / page_height

            for line in block.get("lines", []):
                line_text = " ".join(span.get("text", "") for span in line.get("spans", [])).strip()
                if not line_text:
                    continue
                for span in line.get("spans", []):
                    size = span.get("size", body_size)
                    is_h, conf = _is_heading_span(line_text, size, body_size, y_rel)
                    if is_h and conf > best_conf:
                        best_conf = conf
                        best_title = line_text[:120]

        if best_title and best_conf >= 0.6:
            if not boundaries or boundaries[-1].page != pg_num:
                boundaries.append(ChapterBoundary(page=pg_num, title=best_title, confidence=best_conf))

    return sorted(boundaries, key=lambda b: b.page)


def group_chapters_into_chunks(
    boundaries: List[ChapterBoundary],
    start_page: int,
    end_page: int,
    max_pages: int,
) -> List[Tuple[int, int, str]]:
    if not boundaries:
        ranges = []
        cursor = start_page
        while cursor <= end_page:
            chunk_end = min(end_page, cursor + max_pages - 1)
            ranges.append((cursor, chunk_end, ""))
            cursor = chunk_end + 1
        return ranges

    chapters = []
    for i, b in enumerate(boundaries):
        ch_start = max(b.page, start_page)
        ch_end = min(boundaries[i + 1].page - 1 if i + 1 < len(boundaries) else end_page, end_page)
        if ch_start <= ch_end:
            chapters.append((ch_start, ch_end, b.title))

    if chapters and chapters[0][0] > start_page:
        chapters.insert(0, (start_page, chapters[0][0] - 1, "Preamble"))
    elif not chapters:
        chapters = [(start_page, end_page, "")]

    result = []
    cur_start = None
    cur_end = None
    cur_first_title = None
    cur_last_title = None
    cur_size = 0

    for ch_start, ch_end, title in chapters:
        ch_size = ch_end - ch_start + 1
        if cur_start is None:
            cur_start, cur_end = ch_start, ch_end
            cur_first_title, cur_last_title = title, title
            cur_size = ch_size
        elif cur_size + ch_size <= max_pages:
            cur_end = ch_end
            cur_last_title = title
            cur_size += ch_size
        else:
            first = cur_first_title or ""
            last = cur_last_title or ""
            label = f"{first} \u2013 {last}" if first != last and first and last else (first or last)
            result.append((cur_start, cur_end, label))
            cur_start, cur_end = ch_start, ch_end
            cur_first_title, cur_last_title = title, title
            cur_size = ch_size

    if cur_start is not None:
        first = cur_first_title or ""
        last = cur_last_title or ""
        label = f"{first} \u2013 {last}" if first != last and first and last else (first or last)
        result.append((cur_start, cur_end, label))

    final = []
    for s, e, t in result:
        size = e - s + 1
        if size <= max_pages:
            final.append((s, e, t))
        else:
            cursor = s
            first_chunk = True
            while cursor <= e:
                chunk_end = min(e, cursor + max_pages - 1)
                final.append((cursor, chunk_end, t if first_chunk else f"{t} (continued)"))
                cursor = chunk_end + 1
                first_chunk = False

    return final


def _page_starts_with_table_continuation(pdf, page_num: int) -> bool:
    """Return True if page_num (1-based) starts with a table that appears to
    continue from the previous page (table top is within the top 10% of the
    page AND the previous page also ends with a table)."""
    if page_num < 2 or page_num > len(pdf):
        return False
    try:
        prev_page = pdf[page_num - 2]
        curr_page = pdf[page_num - 1]
        tables_curr = curr_page.find_tables()
        if not tables_curr:
            return False
        tables_prev = prev_page.find_tables()
        if not tables_prev:
            return False
        first_table = tables_curr[0]
        if hasattr(first_table, "bbox"):
            table_top = first_table.bbox[1] / (curr_page.rect.height or 1.0)
        else:
            table_top = first_table.rect.y0 / (curr_page.rect.height or 1.0)
        return table_top < 0.1
    except Exception:
        return False


_AI_CHAPTER_PROMPT = """
You are a document structure expert. Given sample text from the first {sample_pages} pages of a clinical nutrition textbook, identify the main chapter boundaries.

Return a JSON array of objects with keys:
  - "page": integer page number where the chapter starts (1-based)
  - "title": string title of the chapter or major section

Rules:
- Only identify major chapters / sections (not sub-sections).
- A chapter must be at least 10 pages long.
- Return between 3 and 50 entries.
- Sort by page number ascending.

Sample text (pages 1-{sample_pages}):
---
{text_sample}
---

Return JSON only, no explanations.
""".strip()


def detect_chapters_with_ai(
    pdf,
    start_page: int,
    end_page: int,
    pool,
    sample_pages: int = 60,
) -> List[ChapterBoundary]:
    """
    Use AI (via AIKeyPool) to detect chapter boundaries by sending a text sample
    from the beginning of the document. Used as fallback when font-size heuristics
    return < 3 boundaries per 100 pages.
    """
    total_pages = end_page - start_page + 1
    pages_to_sample = min(sample_pages, total_pages)

    lines: list[str] = []
    for pg_num in range(start_page, start_page + pages_to_sample):
        if pg_num > len(pdf):
            break
        try:
            text = pdf[pg_num - 1].get_text("text").strip()
            if text:
                lines.append(f"=== Page {pg_num} ===\n{text[:500]}")
        except Exception:
            pass

    if not lines:
        return []

    text_sample = "\n\n".join(lines)[:12000]
    prompt = _AI_CHAPTER_PROMPT.format(
        sample_pages=pages_to_sample,
        text_sample=text_sample,
    )

    try:
        raw = pool.call_with_retry(prompt, json_mode=True)
        data = json.loads(raw)
        if not isinstance(data, list):
            return []

        boundaries: List[ChapterBoundary] = []
        for item in data:
            pg = item.get("page")
            title = item.get("title", "")
            if isinstance(pg, (int, float)) and title:
                pg = int(pg)
                if start_page <= pg <= end_page:
                    boundaries.append(ChapterBoundary(page=pg, title=str(title)[:120], confidence=0.80))

        boundaries.sort(key=lambda b: b.page)
        logger.info("AI chapter detection found %d boundaries", len(boundaries))
        return boundaries

    except Exception as exc:
        logger.warning("AI chapter detection failed: %s", exc)
        return []


def detect_chapter_boundaries_with_fallback(
    pdf,
    start_page: int,
    end_page: int,
    max_pages: Optional[int] = None,
    pool=None,
) -> List[ChapterBoundary]:
    """
    Run font-size heuristic chapter detection. If the result yields fewer than
    3 boundaries per 100 pages and an AI pool is provided, fall back to AI
    semantic detection.
    """
    boundaries = detect_chapter_boundaries(pdf, start_page, end_page, max_pages)

    total_pages = max(1, end_page - start_page + 1)
    threshold = max(3, total_pages // 100 * 3)

    if len(boundaries) < threshold and pool is not None:
        logger.info(
            "Font heuristics found only %d boundaries for %d pages — falling back to AI detection",
            len(boundaries), total_pages,
        )
        ai_boundaries = detect_chapters_with_ai(pdf, start_page, end_page, pool)
        if ai_boundaries:
            return ai_boundaries

    return boundaries


def check_table_safety(
    pdf,
    split_pages: List[int],
    chapter_boundary_pages: set = None,
) -> List[int]:
    """Advance each split boundary past any table-continuation pages.

    Nudging stops at a chapter boundary page so we never cross into the
    next chapter during the adjustment loop.  The chapter boundary itself
    is still checked for table continuations; if it is one we leave the
    split at the boundary rather than crossing it (the alternative of
    merging chunks is handled at a higher level).
    """
    if chapter_boundary_pages is None:
        chapter_boundary_pages = set()
    adjusted = []
    for sp in split_pages:
        safe_page = sp
        candidate = sp
        while _page_starts_with_table_continuation(pdf, candidate):
            next_candidate = min(candidate + 1, len(pdf))
            if next_candidate == candidate:
                break
            if next_candidate in chapter_boundary_pages:
                break
            candidate = next_candidate
        safe_page = candidate
        adjusted.append(safe_page)
    return adjusted
