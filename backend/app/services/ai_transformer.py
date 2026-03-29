"""
ai_transformer.py - Two-pass AI content transformation pipeline.

Pass 1: Structural labeling (H1/H2/H3/BODY/LIST/TABLE + NR flag)
         Processes 100% of content in word-limited batches.
         Table paragraphs are detected before batching and kept as atomic
         units — they are never split across batch boundaries.

Pass 2: Academic rewriting — only on NR-flagged blocks (typically 25-35%).
         TABLE blocks bypass Pass 2 entirely; their raw text is preserved.
         After each rewrite, an entity-preserving integrity check verifies:
           (a) every numeric value present in the original appears in the
               rewritten text (100% required);
           (b) every measurement unit (mg, kcal, mmol/L, etc.) is preserved;
           (c) every capitalised medical/technical term is present (100% required).
         If any check fails the original block text is used as fallback.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

logger = logging.getLogger(__name__)

WORDS_PER_BATCH = 3000
PASS2_BATCH_SIZE = 12
_TOKENS_PER_WORD = 1.33
_MAX_TOKENS_PER_BATCH = 6000

BLOCK_TYPES = {"H1", "H2", "H3", "BODY", "LIST", "TABLE"}

PASS1_SYSTEM = (
    "You are a manuscript structure analyzer for an academic clinical nutrition textbook. "
    "Analyze text blocks extracted from PDF pages and classify + flag them for rewriting."
)

PASS1_PROMPT_TEMPLATE = """
Classify each paragraph/block below. Output one line per block in this exact format:
  [TYPE] text
  [TYPE|NR] text   (add |NR only if the block NEEDS academic rewriting)

TYPE must be one of: H1, H2, H3, BODY, LIST, TABLE

Add |NR (Needs Rewrite) when the block contains ANY of:
- Conversational phrases ("So basically", "Let me explain", "You can see that", "Buddy")
- First-person narration from ChatGPT ("I'll now", "We've covered", "As I mentioned")
- Incomplete or abruptly cut-off sentences
- Very short non-heading fragments (under 15 words that are not headings)
- Informal or unprofessional register

RULES:
- Output EVERY block. Do not skip, merge, or split blocks.
- Preserve every word of the original text exactly.
- TABLE rows must use " | " between cells.
- Headings are typically short (under 15 words), bold, or start with numbers/Chapter/Section.

TEXT BLOCKS:
---
{text}
---
""".strip()

PASS2_SYSTEM = (
    "You are an academic writing editor specializing in Indian university health sciences textbooks. "
    "Rewrite conversational text into formal academic prose suitable for B.Sc./M.Sc. dietetics programmes."
)

PASS2_PROMPT_TEMPLATE = """
TASK: Rewrite the TEXT TO REWRITE section into formal academic prose.

STRICT RULES:
1. Preserve ALL factual content: every number, measurement, medical term, formula, and definition must appear in output.
2. Remove conversational language ("So basically", "Let me tell you", "Buddy", ChatGPT meta-commentary).
3. Complete any sentence that appears cut off or incomplete.
4. Use formal academic register appropriate for university-level health sciences textbooks.
5. Merge very short related fragments into coherent paragraphs.
6. Do NOT add new information not present in the original.
7. Maintain the same logical structure and sequence.
8. Output ONLY the rewritten text. No labels, no explanations.

SURROUNDING CONTEXT (for reference only — do NOT include in output):
<<<
{context}
>>>

TEXT TO REWRITE:
<<<
{text}
>>>
""".strip()


@dataclass
class TransformedBlock:
    block_type: str
    text: str
    needs_rewrite: bool = False
    rewritten: bool = False
    fallback: bool = False
    original_text: str = ""
    spans: list = field(default_factory=list)


@dataclass
class TransformStats:
    total_blocks: int = 0
    flagged_blocks: int = 0
    rewritten_blocks: int = 0
    fallback_blocks: int = 0
    table_blocks: int = 0
    pass1_batches: int = 0
    pass2_batches: int = 0
    provider_calls: int = 0
    skipped: bool = False
    error: str = ""


def _count_words(text: str) -> int:
    return len(text.split())


def _parse_pass1_output(raw_output: str) -> list[TransformedBlock]:
    """
    Parse Pass 1 output lines like '[H1] text' or '[BODY|NR] text'.

    Continuation lines (lines without a leading [TYPE] tag) are:
    - Joined with '\\n' when the current block is a TABLE so that row
      boundaries are preserved exactly.
    - Joined with ' ' for all other block types (normal prose).
    """
    blocks: list[TransformedBlock] = []
    for line in raw_output.splitlines():
        raw_line = line
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^\[([A-Z1-3|]+)\]\s+(.*)", line, re.DOTALL)
        if not m:
            if blocks:
                if blocks[-1].block_type == "TABLE":
                    blocks[-1].text += "\n" + raw_line.rstrip()
                else:
                    blocks[-1].text += " " + line
            else:
                blocks.append(TransformedBlock(block_type="BODY", text=line))
            continue

        tag_part = m.group(1)
        text = m.group(2).strip()

        parts = tag_part.split("|")
        block_type = parts[0].strip().upper()
        if block_type not in BLOCK_TYPES:
            block_type = "BODY"
        needs_rewrite = "NR" in [p.strip().upper() for p in parts[1:]]

        blocks.append(TransformedBlock(
            block_type=block_type,
            text=text,
            needs_rewrite=needs_rewrite,
        ))
    return blocks


_TABLE_ROW_RE = re.compile(r"[\|│]")


def _is_table_row(paragraph: str) -> bool:
    """Heuristic: detect table rows by presence of pipe/column separators."""
    stripped = paragraph.strip()
    return bool(_TABLE_ROW_RE.search(stripped)) and stripped.count("|") >= 1


def _group_table_rows(paragraphs: list[str]) -> list[list[str]]:
    """
    Group consecutive table rows into single atomic units so they are never
    split across Pass 1 batches. Non-table paragraphs become single-element
    groups. Returns a list of groups, each group being a list of paragraphs
    that must stay together.
    """
    groups: list[list[str]] = []
    i = 0
    while i < len(paragraphs):
        p = paragraphs[i]
        if _is_table_row(p):
            table_group = [p]
            j = i + 1
            while j < len(paragraphs) and _is_table_row(paragraphs[j]):
                table_group.append(paragraphs[j])
                j += 1
            groups.append(table_group)
            i = j
        else:
            groups.append([p])
            i += 1
    return groups


def _consolidate_paragraphs(text_chunks: list[str]) -> list[str]:
    """
    Pre-process paragraphs before batching:
    - Consecutive table rows are joined into a single paragraph so the model
      always sees a complete table as one atomic unit (never split).
    - Non-table paragraphs are passed through unchanged.
    Returns a new list of paragraphs ready for batching.
    """
    groups = _group_table_rows(text_chunks)
    consolidated: list[str] = []
    for group in groups:
        if len(group) == 1:
            consolidated.append(group[0])
        else:
            consolidated.append("\n".join(group))
    return consolidated


def _estimate_tokens(text: str) -> int:
    """Estimate token count using word-count × 1.33 heuristic."""
    return int(len(text.split()) * _TOKENS_PER_WORD) + 1


def _build_batches(text_chunks: list[str], words_per_batch: int) -> list[list[str]]:
    """
    Group text paragraphs into token-aware batches for Pass 1.

    Uses a token estimate (words × 1.33) capped at _MAX_TOKENS_PER_BATCH to
    keep each batch safely under the model's 8192-token output limit. Falls
    back to the words_per_batch ceiling if the token limit isn't the binding
    constraint. Consecutive table rows are consolidated into atomic units.
    """
    consolidated = _consolidate_paragraphs(text_chunks)

    batches: list[list[str]] = []
    current_batch: list[str] = []
    current_tokens = 0

    for para in consolidated:
        t = _estimate_tokens(para)
        if (current_tokens + t > _MAX_TOKENS_PER_BATCH or
                _count_words(para) + sum(_count_words(p) for p in current_batch) > words_per_batch) \
                and current_batch:
            batches.append(current_batch)
            current_batch = [para]
            current_tokens = t
        else:
            current_batch.append(para)
            current_tokens += t

    if current_batch:
        batches.append(current_batch)

    return batches


_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)*\b")
_MEDICAL_TERM_RE = re.compile(
    r"\b(?:[A-Z][a-z]{2,}(?:[- ][A-Z][a-z]{2,})*|[A-Z]{2,})\b"
)
_UNIT_RE = re.compile(
    r"\b(?:mg|g|kg|mcg|ug|iu|mmol|mol|mEq|mOsm|kcal|cal|ml|dl|L|dL|"
    r"mg\/dl|g\/dl|mmHg|mmol\/L|mEq\/L|IU\/L|U\/L|ng\/ml|pg\/ml|"
    r"cm|mm|m|bmi|BMI)\b",
    re.IGNORECASE,
)


def _integrity_check(original: str, rewritten: str) -> bool:
    """
    Entity-preserving integrity check:
    1. All numeric values must be present in rewritten text (100% tolerance).
    2. All measurement units must appear in rewritten text.
    3. At least 75% of capitalised medical/technical terms must be preserved.

    Returns True if the rewritten text passes all checks.
    """
    if not rewritten.strip():
        return False

    orig_numbers = _NUMBER_RE.findall(original)
    if orig_numbers:
        for num in orig_numbers:
            if num not in rewritten:
                return False

    orig_units = set(m.group(0) for m in _UNIT_RE.finditer(original))
    rewritten_lower = rewritten.lower()
    for unit in orig_units:
        if unit.lower() not in rewritten_lower:
            return False

    orig_terms = set(_MEDICAL_TERM_RE.findall(original))
    stop_caps = {"I", "The", "A", "An", "In", "Of", "And", "Or", "With",
                 "For", "To", "As", "At", "By", "From", "On", "Its", "Be",
                 "Is", "Are", "Was", "Were", "Has", "Have", "Had", "This",
                 "That", "These", "Those", "Such", "Each", "Both", "All",
                 "Any", "Some", "No", "Not", "But", "If", "So", "Yet"}
    orig_terms -= stop_caps
    if orig_terms:
        for term in orig_terms:
            if term not in rewritten:
                return False

    return True


def _extract_table_cells(text: str) -> set[str]:
    """
    Extract non-empty cell values from a table-formatted text block.
    Splits on pipe characters and returns a set of stripped cell strings
    with length >= 2 (to ignore empty/separator-only cells).
    """
    cells: set[str] = set()
    for line in text.splitlines():
        for cell in line.split("|"):
            c = cell.strip()
            if len(c) >= 2:
                cells.add(c)
    return cells


def _count_table_rows(text: str) -> int:
    """Count the number of non-empty table rows (lines containing a pipe)."""
    return sum(
        1 for line in text.splitlines()
        if "|" in line and line.strip()
    )


def _verify_table_block(original_para: str, block: TransformedBlock) -> None:
    """
    Structural and cell-by-cell verification for TABLE blocks after Pass 1.

    Checks performed:
    1. Cell membership: every cell value from the original must appear in
       the output (100% required — any missing cell triggers reversion).
    2. Row structure: the output must have at least as many table rows as the
       original. Fewer rows means the AI collapsed row boundaries.

    If either check fails: the block text is reverted to the original paragraph
    text (preserving exact structure) and needs_rewrite is forced to False.
    """
    block.needs_rewrite = False

    if block.block_type != "TABLE":
        return

    orig_cells = _extract_table_cells(original_para)
    out_cells = _extract_table_cells(block.text)

    missing = orig_cells - out_cells
    if missing:
        logger.debug(
            "TABLE cell-check: %d cell(s) missing after Pass 1 — reverting to original",
            len(missing),
        )
        block.text = original_para
        block.fallback = True
        return

    orig_rows = _count_table_rows(original_para)
    out_rows = _count_table_rows(block.text)
    if orig_rows > 0 and out_rows < orig_rows:
        logger.debug(
            "TABLE row-check: original has %d rows, output has %d — reverting to original",
            orig_rows, out_rows,
        )
        block.text = original_para
        block.fallback = True


def _find_original_table(block_text: str, batch: list[str]) -> str:
    """
    Find the original paragraph in the batch that best matches a TABLE block.

    Matching strategy (in order of precision):
    1. Exact match (block_text is already the original).
    2. First paragraph in the batch that contains a pipe separator AND whose
       cells are a superset of the cells found in block_text (robust against
       header rewrites by the AI).
    3. First table-row paragraph in the batch (last resort).
    4. block_text itself as a fallback (no reversion possible).

    This avoids the brittle first-80-chars key used previously.
    """
    block_cells = _extract_table_cells(block_text)

    table_paras = [p for p in batch if _is_table_row(p)]

    for para in batch:
        if para == block_text:
            return para

    best: str | None = None
    best_overlap = -1
    for para in table_paras:
        orig_cells = _extract_table_cells(para)
        if not orig_cells:
            continue
        overlap = len(orig_cells & block_cells)
        if overlap > best_overlap:
            best_overlap = overlap
            best = para

    if best is not None:
        return best

    if table_paras:
        return table_paras[0]

    return block_text


def run_pass1(
    paragraphs: list[str],
    pool,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> list[TransformedBlock]:
    """
    Run Pass 1 (structural labeling) on all paragraphs.

    Consecutive table rows are consolidated into single paragraph strings before
    batching so the model always receives a complete table as one atomic block.
    After parsing, each TABLE block is validated cell-by-cell; any missing cell
    causes the original (consolidated) text to be restored and Pass 2 is
    suppressed for that block.

    Returns a list of TransformedBlock objects.
    """
    batches = _build_batches(paragraphs, WORDS_PER_BATCH)

    all_blocks: list[TransformedBlock] = []

    for i, batch in enumerate(batches):
        if progress_cb:
            progress_cb(i, len(batches))

        batch_text = "\n\n".join(batch)
        prompt = PASS1_PROMPT_TEMPLATE.format(text=batch_text)

        try:
            raw = pool.call_with_retry(prompt, system=PASS1_SYSTEM)
            parsed = _parse_pass1_output(raw)

            for blk in parsed:
                if blk.block_type == "TABLE":
                    orig_para = _find_original_table(blk.text, batch)
                    _verify_table_block(orig_para, blk)

            all_blocks.extend(parsed)
        except Exception as exc:
            logger.warning("Pass 1 batch %d failed: %s — using plain text fallback", i, exc)
            for para in batch:
                all_blocks.append(TransformedBlock(
                    block_type="BODY",
                    text=para,
                    needs_rewrite=False,
                    fallback=True,
                ))

    return all_blocks


def run_pass2(
    blocks: list[TransformedBlock],
    pool,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> list[TransformedBlock]:
    """
    Run Pass 2 (academic rewriting) on flagged non-TABLE blocks.
    Mutates blocks in-place (sets text, rewritten, fallback).
    Returns the modified list.
    """
    flagged_indices = [
        i for i, b in enumerate(blocks)
        if b.needs_rewrite and b.block_type != "TABLE"
    ]

    for batch_start in range(0, len(flagged_indices), PASS2_BATCH_SIZE):
        batch_idx = flagged_indices[batch_start: batch_start + PASS2_BATCH_SIZE]
        if progress_cb:
            progress_cb(batch_start, len(flagged_indices))

        for bi in batch_idx:
            block = blocks[bi]
            context_before = " ".join(
                b.text for b in blocks[max(0, bi - 2): bi]
                if b.block_type not in ("H1", "H2", "H3")
            )
            context_after = " ".join(
                b.text for b in blocks[bi + 1: min(len(blocks), bi + 3)]
                if b.block_type not in ("H1", "H2", "H3")
            )
            context = " ".join(filter(None, [context_before, context_after]))

            prompt = PASS2_PROMPT_TEMPLATE.format(
                context=context[:1000] if context else "(none)",
                text=block.text,
            )

            block.original_text = block.text
            try:
                rewritten = pool.call_with_retry(prompt, system=PASS2_SYSTEM)
                rewritten = rewritten.strip()

                if rewritten and _integrity_check(block.original_text, rewritten):
                    block.text = rewritten
                    block.rewritten = True
                else:
                    logger.debug(
                        "Pass 2 integrity check failed for block %d — keeping original", bi
                    )
                    block.text = block.original_text
                    block.fallback = True

            except Exception as exc:
                logger.warning("Pass 2 block %d failed: %s — keeping original", bi, exc)
                block.text = block.original_text
                block.fallback = True

    return blocks


def build_transformed_text(blocks: list[TransformedBlock]) -> str:
    """
    Produce a human-readable plain-text representation with heading markers.
    This is stored as the transformed_text artifact for review in the workspace.
    """
    lines: list[str] = []
    for block in blocks:
        if block.block_type == "H1":
            lines.append(f"\n{'=' * 60}")
            lines.append(block.text.upper())
            lines.append('=' * 60)
        elif block.block_type == "H2":
            lines.append(f"\n{block.text}")
            lines.append('-' * min(len(block.text), 60))
        elif block.block_type == "H3":
            lines.append(f"\n### {block.text}")
        elif block.block_type == "LIST":
            if not block.text.startswith("-"):
                lines.append(f"- {block.text}")
            else:
                lines.append(block.text)
        elif block.block_type == "TABLE":
            lines.append(block.text)
        else:
            lines.append(f"\n{block.text}")
    return "\n".join(lines).strip()


def transform_chunk_text(
    cleaned_text: str,
    pool,
    progress_cb: Optional[Callable[[str, float], None]] = None,
) -> tuple[list[TransformedBlock], TransformStats]:
    """
    Full two-pass transformation of a chunk's cleaned text.

    Args:
        cleaned_text: The cleaned text from the pipeline (may contain
                      "===== PAGE N =====" markers which are stripped).
        pool:         AIKeyPool instance.
        progress_cb:  Optional callback(stage_label, pct_0_to_100).

    Returns:
        (blocks, stats) tuple.
    """
    stats = TransformStats()

    paragraphs: list[str] = []
    for line in cleaned_text.splitlines():
        if re.match(r"^=====\s*PAGE\s+\d+\s*=====", line):
            continue
        paragraphs.append(line.strip())

    text_blob = "\n".join(paragraphs)
    raw_paragraphs = [p.strip() for p in re.split(r"\n{2,}", text_blob) if p.strip()]

    if not raw_paragraphs:
        stats.skipped = True
        return [], stats

    total_pass1_batches = len(_build_batches(raw_paragraphs, WORDS_PER_BATCH))

    if progress_cb:
        progress_cb(f"Pass 1: Batch 0/{total_pass1_batches}", 0.0)

    def pass1_progress(i: int, total: int) -> None:
        if progress_cb and total > 0:
            progress_cb(f"Pass 1: Batch {i+1}/{total}", (i / total) * 50.0)

    blocks = run_pass1(raw_paragraphs, pool, progress_cb=pass1_progress)
    stats.pass1_batches = total_pass1_batches
    stats.total_blocks = len(blocks)
    stats.table_blocks = sum(1 for b in blocks if b.block_type == "TABLE")
    stats.flagged_blocks = sum(1 for b in blocks if b.needs_rewrite)

    if progress_cb:
        progress_cb(f"Pass 2: Rewriting {stats.flagged_blocks} flagged blocks", 50.0)

    def pass2_progress(i: int, total: int) -> None:
        if progress_cb and total > 0:
            progress_cb(f"Pass 2: Rewriting block {i+1}/{total}", 50.0 + (i / total) * 45.0)

    blocks = run_pass2(blocks, pool, progress_cb=pass2_progress)
    stats.rewritten_blocks = sum(1 for b in blocks if b.rewritten)
    stats.fallback_blocks = sum(1 for b in blocks if b.fallback)
    stats.pass2_batches = (stats.flagged_blocks + PASS2_BATCH_SIZE - 1) // max(1, PASS2_BATCH_SIZE)

    if progress_cb:
        progress_cb(f"Done: {stats.rewritten_blocks} rewritten, {stats.fallback_blocks} fallbacks", 100.0)

    return blocks, stats
