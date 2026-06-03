"""Cleaner for the *text-PDF* CSIR / TCS-iON exam format.

This is the third format we support, after the 2025 NTA image-export
("ntaion") and the 2024 PREVIEW QUESTION BANK ("objective") formats.

What the source looks like
==========================

The questions are real selectable text in the PDF. Each question follows
this template, with English text immediately followed by the Hindi
translation:

    <english stem>
    <hindi stem>
    [Question ID = N][Question Description = ...]
    1. <english option text>
    <hindi option text> [Option ID = X]
    2. <english option text>
    <hindi option text> [Option ID = X+1]
    3. ...
    4. ...

Some questions also have one or more raster images (graphs, diagrams) that
sit between the stem and the options.

The matching answer key references **Option IDs** rather than option
numbers, e.g. ``Question 126 -> Option ID 503`` which means option 3 (the
3rd option of question 126 has [Option ID = 503] in the source).

What we produce
===============

A clean A4 PDF with:
  * Sequential question numbering (Question 1, Question 2, ...)
  * English question stem only - Hindi text is best-effort stripped
  * English options only, numbered 1-4
  * Any embedded diagram/image preserved verbatim
  * A green "ANSWER KEY" footer per page when an answer map is provided.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import fitz


# ---------------------------------------------------------------------------
# Format-detection
# ---------------------------------------------------------------------------

_QID_TAG_RE = re.compile(r"\[Question\s*ID\s*=\s*\d+\]", re.IGNORECASE)
_OPT_TAG_RE = re.compile(r"\[Option\s*ID\s*=\s*\d+\]", re.IGNORECASE)


def looks_like_textpdf_format(doc: fitz.Document) -> bool:
    """True when the PDF is the CSIR text-PDF format we handle here.

    We require at least 3 ``[Question ID = N]`` markers and 6 ``[Option ID
    = N]`` markers in the first 5 pages of plain-text content.
    """
    sample = "\n".join(doc[i].get_text() for i in range(min(5, len(doc))))
    if len(_QID_TAG_RE.findall(sample)) < 3:
        return False
    if len(_OPT_TAG_RE.findall(sample)) < 6:
        return False
    return True


# ---------------------------------------------------------------------------
# Best-effort Hindi stripping
# ---------------------------------------------------------------------------

# Devanagari unicode block
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F\u0A8D-\u0A8F]")


def _is_mostly_hindi(s: str) -> bool:
    """Return True when more than 30% of letters in `s` are Devanagari.

    We count letters only - whitespace, punctuation and digits are ignored
    so a label like "1. " followed by Hindi-only text reliably reports True.
    """
    if not s:
        return False
    devs = _DEVANAGARI_RE.findall(s)
    letters = [c for c in s if c.isalpha() or _DEVANAGARI_RE.match(c)]
    if not letters:
        return False
    return (len(devs) / len(letters)) > 0.30


def _strip_hindi(text: str) -> str:
    """Remove Hindi-dominant lines.

    Keeps mixed lines (option label + minor Hindi tokens) so we don't
    accidentally strip valid English option text. Conservative.
    """
    out: list[str] = []
    for line in text.splitlines():
        if _is_mostly_hindi(line):
            continue
        out.append(line)
    return "\n".join(out).strip()


def _strip_leading_symbol_lines(s: str) -> str:
    """Remove orphan 'junk' lines around the real text of a stem.

    Two kinds of leak happen in these text PDFs:

      * A lone degree sign / stray digit from the previous question's
        superscripts lands at the TOP of the next stem::

            °
            °
            A gas is heated ...

      * A stacked power tower (e.g. ``2^(2^2)``) emits its upper levels on
        their own baselines, so a fragment like ``2^2`` ends up on a line of
        its own ABOVE and BELOW the real sentence::

            2^2
            Which of the following values is same as 2^2 ?
            2^2

    We strip leading AND trailing lines that carry NO letters and are short
    "symbol/math" fragments (digits, ``^``, operators, parentheses, a lone
    symbol). Scanning stops as soon as a line containing a letter is reached,
    so the real stem text is never touched. If the stem has NO letter line at
    all (a pure-math stem) we leave it untouched so nothing is ever lost.
    Intentionally conservative: when unsure about a line, keep it.
    """
    if not s:
        return s
    lines = s.splitlines()
    if not any(any(ch.isalpha() for ch in ln) for ln in lines):
        # No alphabetic anchor anywhere - don't risk deleting real content.
        return s

    def _is_orphan(stripped: str) -> bool:
        if not stripped:
            return True
        if any(ch.isalpha() for ch in stripped):
            return False
        # Lone non-alphanumeric symbol (e.g. "°", "*", "•").
        if len(stripped) == 1 and not stripped.isalnum():
            return True
        # Short math/symbol fragment with no letters: digits, ^, operators,
        # parentheses, slashes, dots, commas. Keep it short to stay safe.
        if len(stripped) <= 6 and re.fullmatch(r"[0-9^()<>=+\-*/.,\u2010\s]+", stripped):
            return True
        return False

    start = 0
    while start < len(lines):
        stripped = lines[start].strip()
        if any(ch.isalpha() for ch in stripped):
            break
        if _is_orphan(stripped):
            start += 1
        else:
            break

    end = len(lines)
    while end > start:
        stripped = lines[end - 1].strip()
        if any(ch.isalpha() for ch in stripped):
            break
        if _is_orphan(stripped):
            end -= 1
        else:
            break

    return "\n".join(lines[start:end]).strip()


def _normalize_text(s: str) -> str:
    """Tidy up the residue left after stripping Hindi:

    - Collapse non-breaking spaces (U+00A0) into normal spaces
    - Collapse runs of whitespace
    - Fix the common '\xad' (soft hyphen) used by some PDFs as a word-break
    - Trim
    """
    if not s:
        return s
    # U+00A0 non-breaking space -> normal space
    s = s.replace("\u00a0", " ")
    # U+00AD soft hyphen -> nothing (we already broke the word)
    s = s.replace("\u00ad", "")
    # U+200B-U+200F invisible / zero-width chars -> nothing
    s = re.sub(r"[\u200b-\u200f\ufeff]", "", s)
    # Collapse runs of internal whitespace into one space, preserving newlines
    s = re.sub(r"[ \t]+", " ", s)
    # Trim leading/trailing whitespace per line
    s = "\n".join(line.strip() for line in s.splitlines())
    return s.strip()


# ---------------------------------------------------------------------------
# Per-page extraction in reading order
# ---------------------------------------------------------------------------


@dataclass
class _Span:
    page_idx: int
    bbox: tuple[float, float, float, float]
    text: str = ""
    is_image: bool = False
    xref: int = 0
    width: int = 0
    height: int = 0


def _reflow_page_text(blocks: list[dict]) -> list[tuple[tuple, str]]:
    """Rebuild page text, re-attaching sub/superscript glyphs inline.

    PyMuPDF emits sub/superscript digits (the ``1 2 3`` of ``A1 A2 A3`` or the
    ``2`` of ``10^2``) as small-font spans, often in their OWN block on a
    slightly shifted baseline. Joined naively they drop onto separate lines and
    produce garbage like::

        A < A < A
        1
        2
        3

    Strategy (page-wide so it works even when the digits are in a different
    block than their base text):

      1. Collect every text span with geometry (x range, baseline, font size).
      2. ``body_size`` = the most common font size on the page. A span whose
         size is clearly smaller (< 85% of body) and whose text is short
         (<= 4 chars) is treated as a sub/superscript "script" glyph.
      3. Attach each script glyph to the nearest BASE span that sits on the
         same baseline and just to its left, concatenated with no space so
         ``A`` + ``1`` -> ``A1``.
      4. Rebuild each block's text from its base spans (rows clustered by
         baseline, ordered left-to-right) with the attached scripts inlined.

    Returns a list of ``(block_bbox, text)`` in original block order.
    """
    # --- 1. collect spans -------------------------------------------------
    all_spans: list[dict] = []
    sizes: list[float] = []
    for bi, b in enumerate(blocks):
        for ln in b.get("lines", []):
            for s in ln.get("spans", []):
                txt = s.get("text", "")
                if txt == "":
                    continue
                bbox = s.get("bbox", (0.0, 0.0, 0.0, 0.0))
                org = s.get("origin", (0.0, 0.0))
                rec = {
                    "block": bi,
                    "text": txt,
                    "x0": float(bbox[0]),
                    "x1": float(bbox[2]),
                    "baseline": float(org[1]),
                    "size": float(s.get("size", 0.0) or 0.0),
                }
                all_spans.append(rec)
                if txt.strip():
                    sizes.append(rec["size"])

    if not all_spans:
        return []

    body_size = max(set(sizes), key=sizes.count) if sizes else 0.0
    line_tol = max(body_size * 0.6, 4.0)

    def _is_script(s: dict) -> bool:
        if body_size <= 0:
            return False
        t = s["text"].strip()
        if not t:
            return False
        return s["size"] < body_size * 0.85 and len(t) <= 4

    base_spans = [s for s in all_spans if not _is_script(s)]
    script_spans = [s for s in all_spans if _is_script(s)]

    # --- 3. attach scripts to the base span immediately to their left -----
    attach: dict[int, list[dict]] = {id(b): [] for b in base_spans}
    for sc in script_spans:
        best: dict | None = None
        for b in base_spans:
            if abs(b["baseline"] - sc["baseline"]) > line_tol:
                continue
            # base must begin at or to the left of the script glyph
            if b["x0"] <= sc["x0"] + 1.0:
                if best is None or b["x0"] > best["x0"]:
                    best = b  # rightmost base still left of the script
        if best is not None:
            # Decide super vs subscript by comparing baselines. A superscript
            # sits ABOVE the base (smaller y); a subscript sits BELOW (larger
            # y). Superscripts are exponents -> mark with "^" so "2" + "6"
            # renders as "2^6", never the ambiguous "26". Subscripts (e.g. the
            # "1" in "A1") read fine attached directly.
            sc["is_super"] = sc["baseline"] < best["baseline"] - 0.5
            attach[id(best)].append(sc)
        else:
            # No base to the left on this baseline: treat as a normal base span
            # so the glyph is never silently lost (exam accuracy matters).
            base_spans.append(sc)
            attach[id(sc)] = []

    # --- 4. rebuild per-block text ---------------------------------------
    block_bases: dict[int, list[dict]] = {}
    for b in base_spans:
        block_bases.setdefault(b["block"], []).append(b)

    out: list[tuple[tuple, str]] = []
    for bi, b in enumerate(blocks):
        bases = block_bases.get(bi)
        if not bases:
            continue
        rows: list[dict] = []
        for sp in sorted(bases, key=lambda s: (round(s["baseline"], 1), s["x0"])):
            placed = False
            for row in rows:
                if abs(sp["baseline"] - row["baseline"]) <= line_tol:
                    row["items"].append(sp)
                    placed = True
                    break
            if not placed:
                rows.append({"baseline": sp["baseline"], "items": [sp]})
        rows.sort(key=lambda r: r["baseline"])

        out_lines: list[str] = []
        for row in rows:
            parts = sorted(row["items"], key=lambda s: s["x0"])
            buf = ""
            for sp in parts:
                buf += sp["text"]
                for sc in sorted(attach.get(id(sp), []), key=lambda s: s["x0"]):
                    glyph = sc["text"].strip()
                    if sc.get("is_super") and any(ch.isalnum() for ch in glyph):
                        # Real exponent (digits/letters): use caret so
                        # "2"+"6" -> "2^6", never the ambiguous "26".
                        buf = buf.rstrip() + "^" + glyph
                    else:
                        # Subscript ("A"+"1" -> "A1") or a superscript SYMBOL
                        # such as a degree sign ("2.5"+"°" -> "2.5°"): attach
                        # directly without a caret.
                        buf = buf.rstrip() + glyph
            if buf.strip():
                out_lines.append(buf)
        joined = "\n".join(out_lines).strip()
        if joined:
            out.append((tuple(b["bbox"]), joined))
    return out


def _flatten_pages(doc: fitz.Document) -> list[_Span]:
    """Return every text block + image in reading order across all pages.

    Reading order is per-page top-to-bottom then left-to-right; pages are
    concatenated in their natural order.
    """
    spans: list[_Span] = []
    for pi in range(len(doc)):
        page = doc[pi]
        page_spans: list[_Span] = []

        # text blocks (with sub/superscript glyphs re-attached inline)
        text_blocks = [
            b for b in page.get_text("dict").get("blocks", [])
            if b.get("type", 0) == 0
        ]
        for bbox, text in _reflow_page_text(text_blocks):
            page_spans.append(_Span(page_idx=pi, bbox=bbox, text=text))

        # images
        for info in page.get_image_info(xrefs=True):
            xref = info.get("xref", 0)
            if not xref:
                continue
            page_spans.append(
                _Span(
                    page_idx=pi,
                    bbox=tuple(info.get("bbox", (0, 0, 0, 0))),
                    is_image=True,
                    xref=xref,
                    width=info.get("width", 0) or 0,
                    height=info.get("height", 0) or 0,
                )
            )

        page_spans.sort(key=lambda s: (round(s.bbox[1], 1), round(s.bbox[0], 1)))
        spans.extend(page_spans)
    return spans


# ---------------------------------------------------------------------------
# Question parsing
# ---------------------------------------------------------------------------


_QID_RE = re.compile(r"\[Question\s*ID\s*=\s*(\d+)\]", re.IGNORECASE)
_QDESC_RE = re.compile(r"\[Question\s*Description\s*=\s*[^\]]+\]", re.IGNORECASE)
_OID_RE = re.compile(r"\[Option\s*ID\s*=\s*(\d+)\]", re.IGNORECASE)
_OPTION_NUM_RE = re.compile(r"^\s*(\d)\s*\.\s*", re.MULTILINE)
# Page-chrome lines like "1) " "2) " "Topic:- ..." "CSIR LIFE SCIENCES SHIFT 1 BIL"
_PAGE_CHROME_RE = re.compile(
    r"^(\s*\d+\s*\)\s*$|Topic\s*[\u2010\-:]\s*\S.*$|CSIR\s+[A-Z\s]+SHIFT.*$|Page\s+\d+\s*(of\s*\d+)?$)",
    re.IGNORECASE,
)


@dataclass
class _Option:
    number: int            # 1-4 (or whatever appears in the source)
    text: str = ""         # English-only after stripping
    option_id: str = ""    # The "Option ID = N" value


@dataclass
class _Question:
    q_id: str
    q_num: int = 0
    stem_text: str = ""           # English-only
    images: list[_Span] = field(default_factory=list)
    options: list[_Option] = field(default_factory=list)


def _split_into_questions(spans: list[_Span]) -> list[_Question]:
    """Split the flat span list into one Question per [Question ID = N] marker.

    Approach: build a single concatenated text stream with a position->image
    mapping, then locate the [Question ID = N] markers and the [Option ID = N]
    markers. Each question owns:
      - stem: text between the previous question's last [Option ID] and this
              question's [Question ID] marker
      - options: text starting at the [Question ID] marker, ending at the
                 last [Option ID] before the next [Question ID]

    For the very first question the stem starts at byte 0; for the last
    question the option block ends at end-of-document.
    """
    # Build one big text + image-anchor list
    text_chunks: list[str] = []
    cursor = 0
    image_anchors: list[tuple[int, _Span]] = []  # (char position, image span)
    for s in spans:
        if s.is_image:
            image_anchors.append((cursor, s))
            continue
        text = s.text
        cleaned_lines = []
        for line in text.splitlines():
            if _PAGE_CHROME_RE.match(line.strip()):
                continue
            cleaned_lines.append(line)
        cleaned = "\n".join(cleaned_lines)
        if not cleaned.strip():
            continue
        text_chunks.append(cleaned)
        cursor += len(cleaned) + 1  # +1 for the joiner newline below
    big_text = "\n".join(text_chunks)

    # Locate every [Question ID = N] anchor with its character position
    qid_anchors: list[tuple[int, int, str]] = []  # (start_pos, end_pos, qid)
    for m in re.finditer(r"\[Question\s*ID\s*=\s*(\d+)\]", big_text, re.IGNORECASE):
        qid_anchors.append((m.start(), m.end(), m.group(1)))

    if not qid_anchors:
        return []

    # Locate every [Option ID = N] with position
    opt_anchors: list[tuple[int, int, str]] = []  # (start_pos, end_pos, oid)
    for m in re.finditer(r"\[Option\s*ID\s*=\s*(\d+)\]", big_text, re.IGNORECASE):
        opt_anchors.append((m.start(), m.end(), m.group(1)))

    # For each question:
    #   stem_range = ( end_of_previous_options_or_zero, qid_start )
    #   options_range = ( qid_end, last_option_anchor_end_before_next_qid )
    questions: list[_Question] = []
    for i, (qid_start, qid_end, qid) in enumerate(qid_anchors):
        next_qid_start = qid_anchors[i + 1][0] if i + 1 < len(qid_anchors) else len(big_text)

        # Find option anchors that fall between qid_end and next_qid_start
        opts_in_q = [(s, e, oid) for (s, e, oid) in opt_anchors if qid_end <= s < next_qid_start]

        # Stem: from end of last option of PREVIOUS question (or 0 for the first
        # question) up to this qid_start.
        if i == 0:
            stem_start = 0
        else:
            # find the last opt anchor before this qid_start
            prev_opts = [(s, e, oid) for (s, e, oid) in opt_anchors if e <= qid_start]
            stem_start = prev_opts[-1][1] if prev_opts else qid_anchors[i - 1][1]
        stem_text_raw = big_text[stem_start:qid_start]

        # Strip [Question Description = ...] tags from stem
        stem_clean = _QDESC_RE.sub("", stem_text_raw)
        # Strip stray [Option ID = N] (none should appear in stem normally)
        stem_clean = _OID_RE.sub("", stem_clean)
        stem_clean = _normalize_text(_strip_hindi(stem_clean.strip()))
        # Remove orphan leading glyphs (e.g. a degree sign or lone digit that
        # leaked from the previous question's superscripts). Applied to the
        # STEM ONLY so real trailing superscripts in options are preserved.
        stem_clean = _strip_leading_symbol_lines(stem_clean)

        # Options: walk the question's option region
        if opts_in_q:
            options_region_end = opts_in_q[-1][1]
        else:
            options_region_end = next_qid_start
        options_text = big_text[qid_end:options_region_end]

        # Drop any [Question Description = ...] block right after the qid
        options_text = _QDESC_RE.sub("", options_text)

        options = _parse_option_text(options_text)

        # Images: any image anchor whose position falls between stem_start
        # and qid_start (preceding the question text, often a diagram) OR
        # between qid_start and the question's options end (mid-question
        # diagram). Most diagrams precede the qid marker because the source
        # places stem -> images -> qid_marker -> options.
        imgs_for_q = [
            sp for (pos, sp) in image_anchors
            if stem_start <= pos < options_region_end
        ]

        if not options and not stem_clean and not imgs_for_q:
            # Nothing useful - skip
            continue

        questions.append(_Question(
            q_id=qid,
            stem_text=stem_clean,
            options=options,
            images=imgs_for_q,
        ))

    # Re-number sequentially
    for n, q in enumerate(questions, start=1):
        q.q_num = n
    return questions


def _parse_option_text(text: str) -> list[_Option]:
    """Parse a chunk of text containing one question's options.

    Each option starts with "1.", "2.", etc. at the START OF A LINE, followed
    by English text, then optionally Hindi text, then a "[Option ID = N]" tag.

    Care is taken NOT to split on decimal numbers like "1.250" (which also
    start a line as "1." followed by digits). A real option marker is a digit
    1-4 followed by a dot and then a SPACE or non-digit, and the markers must
    appear in increasing order.
    """
    options: list[_Option] = []
    # An option marker: start-of-line, digit 1-4, optional spaces, a dot,
    # then NOT immediately another digit (so "1.250" is not a marker).
    marker_re = re.compile(r"(?m)^\s*([1-4])\s*\.(?!\d)\s*")

    matches = list(marker_re.finditer(text))
    if not matches:
        return options

    # Keep only markers that appear in increasing numeric order (1,2,3,4),
    # which filters out stray "1." inside option bodies or trailing junk.
    valid = []
    expected = 1
    for m in matches:
        num = int(m.group(1))
        if num == expected:
            valid.append((num, m.start(), m.end()))
            expected += 1
        # allow the same expected number to be retried if a false hit slipped
    if not valid:
        return options

    for i, (num, mstart, mend) in enumerate(valid):
        body_end = valid[i + 1][1] if i + 1 < len(valid) else len(text)
        body = text[mend:body_end]
        oid_match = _OID_RE.search(body)
        oid = oid_match.group(1) if oid_match else ""
        body_no_tag = _OID_RE.sub("", body).strip()
        cleaned = _strip_hindi(body_no_tag)
        cleaned = re.sub(r"\n{2,}", "\n", cleaned).strip()
        cleaned = _normalize_text(cleaned)
        options.append(_Option(number=num, text=cleaned, option_id=oid))
    return options


# ---------------------------------------------------------------------------
# Output rendering
# ---------------------------------------------------------------------------


_PAGE_W, _PAGE_H = 595.0, 842.0  # A4
_MARGIN = 50.0
_AVAIL_W = _PAGE_W - 2 * _MARGIN
_FONT_BODY = "helv"
_FONT_BOLD = "hebo"


def _measure_text_height(text: str, fontsize: float, max_width: float) -> float:
    """Estimate height in points for `text` wrapped to max_width.

    Uses fitz's get_text_length() to break by words. Conservative:
    overestimates slightly so we never overflow.
    """
    if not text:
        return 0.0
    line_height = fontsize * 1.35
    total = 0.0
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            total += line_height * 0.6
            continue
        words = paragraph.split()
        line = ""
        for w in words:
            tentative = (line + " " + w).strip()
            if fitz.get_text_length(tentative, fontname=_FONT_BODY, fontsize=fontsize) > max_width:
                total += line_height
                line = w
            else:
                line = tentative
        if line:
            total += line_height
    return total


def _estimate_options_height(options: list[_Option]) -> float:
    """Approximate vertical space the options block will need.

    Returns a generous estimate so the renderer can decide whether to
    start a fresh page before placing a tall image.
    """
    if not options:
        return 0.0
    total = 0.0
    for o in options:
        total += _measure_text_height(f"{o.number}. {o.text}", fontsize=11, max_width=_AVAIL_W) + 4
    return total + 10  # small buffer


def _draw_wrapped_text(
    page: fitz.Page,
    x: float,
    y: float,
    width: float,
    text: str,
    fontsize: float,
    color: tuple[float, float, float] = (0.13, 0.13, 0.13),
    fontname: str = _FONT_BODY,
) -> float:
    """Render `text` wrapped at `width`. Returns the y-position after."""
    if not text:
        return y
    line_height = fontsize * 1.35
    cur_y = y
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            cur_y += line_height * 0.6
            continue
        words = paragraph.split()
        line = ""
        for w in words:
            tentative = (line + " " + w).strip()
            if fitz.get_text_length(tentative, fontname=fontname, fontsize=fontsize) > width:
                if line:
                    page.insert_text(
                        fitz.Point(x, cur_y),
                        line,
                        fontsize=fontsize,
                        fontname=fontname,
                        color=color,
                    )
                    cur_y += line_height
                line = w
            else:
                line = tentative
        if line:
            page.insert_text(
                fitz.Point(x, cur_y),
                line,
                fontsize=fontsize,
                fontname=fontname,
                color=color,
            )
            cur_y += line_height
    return cur_y


def _draw_answer_box(page: fitz.Page, text: str, found: bool) -> None:
    box_h = 46.0
    rect = fitz.Rect(
        _MARGIN, _PAGE_H - _MARGIN - box_h, _PAGE_W - _MARGIN, _PAGE_H - _MARGIN
    )
    if found:
        fill = (0.86, 0.96, 0.88)
        border = (0.2, 0.55, 0.32)
        text_color = (0.08, 0.36, 0.18)
        title = "ANSWER KEY"
    else:
        fill = (0.99, 0.91, 0.91)
        border = (0.78, 0.25, 0.25)
        text_color = (0.55, 0.13, 0.13)
        title = "ANSWER KEY NOT FOUND"
    page.draw_rect(rect, color=border, fill=fill, width=0.8, radius=0.06)
    page.insert_text(
        fitz.Point(rect.x0 + 12, rect.y0 + 16),
        title,
        fontsize=8,
        fontname=_FONT_BODY,
        color=border,
    )
    page.insert_text(
        fitz.Point(rect.x0 + 12, rect.y0 + 34),
        text,
        fontsize=12,
        fontname=_FONT_BOLD,
        color=text_color,
    )


def _resolve_answer(q: _Question, raw_answer_payload: dict) -> tuple[str, bool]:
    """Translate an answer-key entry into "Correct Option: N" text.

    The CSIR text-PDF answer keys reference Option IDs, so we look up the
    option in the question whose Option ID matches.
    Returns (display_text, ok_flag).
    """
    raw_value = raw_answer_payload.get("raw", "").strip() if raw_answer_payload else ""
    kind = raw_answer_payload.get("kind", "") if raw_answer_payload else ""

    if not raw_value:
        return ("Answer key not found for this question", False)

    # The key sometimes pre-formats its text as "Correct Option: 3" already
    # (when the source was a numeric option key). If so, just pass through.
    if kind == "single" and raw_value.isdigit() and 1 <= int(raw_value) <= 9:
        # Heuristic: if it's a small integer, it might be either an option
        # number OR a small Option ID. For text-PDF we expect Option IDs
        # which are usually bigger. Treat 1-4 as option-number-style.
        if int(raw_value) <= 4:
            return (f"Correct Option: {raw_value}", True)
        # else fall through to Option ID lookup

    # Otherwise, the raw value is a (possibly multi-part) Option ID list.
    # Examples: "503", "503,504", "503 or 504"
    pieces = re.split(r"[,\s]+|\bor\b", raw_value, flags=re.IGNORECASE)
    pieces = [p.strip() for p in pieces if p.strip().isdigit()]
    if not pieces:
        return (f"Answer key (raw): {raw_value}", True)

    # Build Option ID -> option number map for this question
    oid_to_num: dict[str, int] = {opt.option_id: opt.number for opt in q.options if opt.option_id}
    nums: list[int] = []
    unmatched: list[str] = []
    for p in pieces:
        n = oid_to_num.get(p)
        if n is None:
            unmatched.append(p)
        else:
            nums.append(n)

    if not nums:
        return (
            f"Answer key references unknown Option ID: {', '.join(unmatched)} "
            f"(raw: {raw_value})",
            True,
        )

    if len(nums) == 1:
        return (f"Correct Option: {nums[0]}", True)
    nums_str = ", ".join(str(n) for n in sorted(set(nums)))
    label = "either accepted" if "or" in raw_value.lower() else "multiple correct"
    return (f"Correct Options: {nums_str}  ({label})", True)


def _render(
    src: fitz.Document,
    questions: list[_Question],
    output_path: Path,
    answer_map: Optional[dict[str, dict]],
    answer_subject: Optional[str],
) -> dict:
    """Render the cleaned PDF. Returns render stats."""
    out = fitz.open()
    matched: list[int] = []
    missing: list[tuple[int, str]] = []
    hindi_imgs_removed = 0  # incremented when we drop a Hindi twin image

    # ---------- Cover ------------------------------------------------------
    cover = out.new_page(width=_PAGE_W, height=_PAGE_H)
    cover.insert_text(
        fitz.Point(_MARGIN, _MARGIN + 30),
        "Cleaned Quiz",
        fontsize=26,
        fontname=_FONT_BODY,
        color=(0.13, 0.13, 0.13),
    )
    cover.insert_text(
        fitz.Point(_MARGIN, _MARGIN + 60),
        "CSIR text-PDF format - English only - Hindi removed",
        fontsize=10,
        fontname=_FONT_BODY,
        color=(0.4, 0.4, 0.4),
    )
    cover.insert_text(
        fitz.Point(_MARGIN, _MARGIN + 80),
        f"{len(questions)} questions extracted"
        + (" - answer key attached" if answer_map is not None else ""),
        fontsize=10,
        fontname=_FONT_BODY,
        color=(0.5, 0.5, 0.5),
    )
    if answer_subject:
        cover.insert_text(
            fitz.Point(_MARGIN, _MARGIN + 100),
            f"Answer key subject: {answer_subject}",
            fontsize=10,
            fontname=_FONT_BODY,
            color=(0.4, 0.55, 0.45),
        )

    # ---------- Per-question pages ----------------------------------------
    for q in questions:
        page = out.new_page(width=_PAGE_W, height=_PAGE_H)
        y = _MARGIN

        # Title
        page.insert_text(
            fitz.Point(_MARGIN, y + 14),
            f"Question {q.q_num}",
            fontsize=14,
            fontname=_FONT_BODY,
            color=(0.13, 0.13, 0.13),
        )
        y += 28

        # Stem
        if q.stem_text:
            y = _draw_wrapped_text(page, _MARGIN, y, _AVAIL_W, q.stem_text, fontsize=11)
            y += 10

        # Diagrams. Cleanup steps:
        #  0. De-duplicate by xref. A tall diagram that straddles a page break
        #     is reported once per page it touches, so the SAME xref can appear
        #     2+ times for one question. That is one image, not a twin.
        #  1. Drop "junk" images: very thin separator lines and tiny inline
        #     glyph images (degree symbols, math fragments) that carry no
        #     question content. We keep only images with a meaningful area.
        #  2. Drop the Hindi twin: in this format a diagram-bearing question
        #     often renders the SAME diagram twice (English on top, Hindi
        #     version directly below) as DIFFERENT xrefs. When two similar-sized
        #     content images remain we keep only the topmost (English) one.
        diagrams_dropped = 0
        # Step 0: collapse repeated xrefs, keeping the first (top-most) anchor.
        seen_xrefs: set[int] = set()
        deduped: list[_Span] = []
        for im in sorted(q.images, key=lambda im: (im.page_idx, round(im.bbox[1], 1))):
            if im.xref and im.xref in seen_xrefs:
                continue
            seen_xrefs.add(im.xref)
            deduped.append(im)

        content_imgs = []
        for im in deduped:
            w = im.width or 0
            h = im.height or 0
            # Skip separator lines (extremely wide-and-short or tall-and-thin)
            if h <= 14 or w <= 14:
                diagrams_dropped += 1
                continue
            # Skip tiny inline glyph images (e.g. 27x25 degree symbols)
            if w < 60 and h < 60:
                diagrams_dropped += 1
                continue
            content_imgs.append(im)

        content_imgs.sort(key=lambda im: (im.page_idx, round(im.bbox[1], 1)))

        # If 2+ real content images remain and they are similar in size,
        # treat the lower one(s) as the Hindi twin and drop them.
        if len(content_imgs) >= 2:
            first = content_imgs[0]
            kept_imgs = [first]
            for other in content_imgs[1:]:
                fw, fh = first.width or 1, first.height or 1
                ow, oh = other.width or 1, other.height or 1
                # "similar size" = within 35% on both dimensions
                similar = (
                    abs(fw - ow) <= 0.35 * max(fw, ow)
                    and abs(fh - oh) <= 0.35 * max(fh, oh)
                )
                if similar:
                    diagrams_dropped += 1  # Hindi twin
                else:
                    kept_imgs.append(other)  # genuinely different diagram
            diagrams = kept_imgs
        else:
            diagrams = content_imgs

        hindi_imgs_removed += diagrams_dropped

        # If the question has no stem text but does have a diagram, that
        # means the actual question is rendered inside the image. Show a
        # short hint so readers know to look at the image, not blame our
        # cleaner.
        if not q.stem_text and diagrams:
            y = _draw_wrapped_text(
                page, _MARGIN, y, _AVAIL_W,
                "(question content is rendered as the image below)",
                fontsize=10,
                color=(0.55, 0.55, 0.55),
            )
            y += 8

        for img in diagrams:
            try:
                data = src.extract_image(img.xref)
            except Exception:
                continue
            img_bytes = data.get("image")
            if not img_bytes:
                continue
            iw = data.get("width") or img.width or 1
            ih = data.get("height") or img.height or 1

            # Reserve room for answer box if attaching answers, plus
            # an estimate of how much vertical room the options will need.
            reserve = (70 if answer_map is not None else 0) + _estimate_options_height(q.options)

            # If the current page does not have enough room left, start a
            # fresh page first.
            avail_h_here = _PAGE_H - _MARGIN - reserve - y
            if avail_h_here < 80:
                page = out.new_page(width=_PAGE_W, height=_PAGE_H)
                y = _MARGIN
                page.insert_text(
                    fitz.Point(_MARGIN, y + 12),
                    f"Question {q.q_num} (continued)",
                    fontsize=11,
                    fontname=_FONT_BODY,
                    color=(0.5, 0.5, 0.5),
                )
                y += 24
                avail_h_here = _PAGE_H - _MARGIN - reserve - y

            # Scale to fit BOTH width and height of the available space.
            scale_w = _AVAIL_W / iw if iw else 1.0
            scale_h = avail_h_here / ih if ih else 1.0
            scale = min(1.0, scale_w, scale_h)
            disp_w = iw * scale
            disp_h = ih * scale
            rect = fitz.Rect(_MARGIN, y, _MARGIN + disp_w, y + disp_h)
            page.insert_image(rect, stream=img_bytes, keep_proportion=True)
            y += disp_h + 12

        # Options
        for opt in q.options:
            line_text = f"{opt.number}. {opt.text}"
            est_h = _measure_text_height(line_text, fontsize=11, max_width=_AVAIL_W) + 6
            reserve = 70 if answer_map is not None else 0
            if y + est_h > _PAGE_H - _MARGIN - reserve:
                page = out.new_page(width=_PAGE_W, height=_PAGE_H)
                y = _MARGIN
                page.insert_text(
                    fitz.Point(_MARGIN, y + 12),
                    f"Question {q.q_num} (continued)",
                    fontsize=11,
                    fontname=_FONT_BODY,
                    color=(0.5, 0.5, 0.5),
                )
                y += 24
            y = _draw_wrapped_text(page, _MARGIN, y, _AVAIL_W, line_text, fontsize=11)
            y += 4

        # Answer footer
        if answer_map is not None:
            payload = answer_map.get(q.q_id)
            if payload:
                text, ok = _resolve_answer(q, payload)
                if ok:
                    matched.append(q.q_num)
                    _draw_answer_box(page, text, found=True)
                else:
                    missing.append((q.q_num, q.q_id))
                    _draw_answer_box(page, text, found=False)
            else:
                missing.append((q.q_num, q.q_id))
                _draw_answer_box(page, "Answer key not found for this question", found=False)

    # ---------- Missing-IDs report on the cover ---------------------------
    if answer_map is not None and missing:
        cover = out[0]
        cover.insert_text(
            fitz.Point(_MARGIN, _PAGE_H - _MARGIN - 200),
            f"Warning: {len(missing)} question(s) had no entry in the answer key",
            fontsize=10,
            fontname=_FONT_BODY,
            color=(0.75, 0.2, 0.2),
        )
        ry = _PAGE_H - _MARGIN - 184
        for q_num, q_id in missing[:10]:
            cover.insert_text(
                fitz.Point(_MARGIN + 10, ry),
                f"- Q{q_num} (id {q_id})",
                fontsize=9,
                fontname=_FONT_BODY,
                color=(0.6, 0.2, 0.2),
            )
            ry += 13
        if len(missing) > 10:
            cover.insert_text(
                fitz.Point(_MARGIN + 10, ry),
                f"... and {len(missing) - 10} more",
                fontsize=9,
                fontname=_FONT_BODY,
                color=(0.6, 0.2, 0.2),
            )

    out.save(str(output_path), deflate=True, garbage=4)
    out.close()

    return {
        "answers_matched": len(matched),
        "answers_missing": [{"q_num": n, "q_id": qid} for n, qid in missing],
        "hindi_imgs_removed": hindi_imgs_removed,
    }


# ---------------------------------------------------------------------------
# Public API matching the existing image-format cleaner
# ---------------------------------------------------------------------------


def inspect(input_path: str | Path) -> dict:
    """Cheap pass: just enumerate question IDs and counts (no rendering)."""
    src = fitz.open(str(input_path))
    try:
        spans = _flatten_pages(src)
        questions = _split_into_questions(spans)
        return {
            "source_pages": len(src),
            "question_ids": [q.q_id for q in questions if q.q_id],
            "questions_kept": len(questions),
            "translations_removed": 0,  # inline-stripped per-line, not deduped
            "sections_detected": 0,
            "format": "textpdf",
        }
    finally:
        src.close()


def clean(
    input_path: str | Path,
    output_path: str | Path,
    answer_map: Optional[dict[str, dict]] = None,
    answer_subject: Optional[str] = None,
) -> dict:
    """Full cleaner: produces the cleaned PDF on disk."""
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    src = fitz.open(str(input_path))
    try:
        spans = _flatten_pages(src)
        questions = _split_into_questions(spans)
        render_stats = _render(
            src, questions, output_path,
            answer_map=answer_map, answer_subject=answer_subject,
        )
        return {
            "input": str(input_path),
            "output": str(output_path),
            "source_pages": len(src),
            "questions_detected": len(questions),
            "questions_kept": len(questions),
            "translations_removed": render_stats.get("hindi_imgs_removed", 0),
            "sections_detected": 0,
            "format": "textpdf",
            "answers_attached": answer_map is not None,
            "answers_matched": render_stats["answers_matched"],
            "answers_missing": render_stats["answers_missing"],
        }
    finally:
        src.close()
