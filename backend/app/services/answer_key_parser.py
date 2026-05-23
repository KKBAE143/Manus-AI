"""Parse NTA / CSIR-UGC NET style answer-key PDFs.

The PDFs are multi-subject. Each page starts with a header like:

    Subject: (703) LIFE SCIENCES   CSIR-UGC NET JUNE 2025  FINAL ANSWER KEY

followed by a flat alternating stream:

    <question_id>
    <answer>
    <question_id>
    <answer>
    ...

Where <answer> can be:
  - "2"             -> single correct option
  - "1,2,3"         -> multiple correct options (comma list)
  - "3 or 4"        -> either accepted
  - "Drop"          -> question dropped (all candidates awarded marks)

We never guess. If a token doesn't match any known shape we record it as
"unrecognised" and surface that in the UI so a human can review the document
before relying on it for an exam.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import fitz


# --- Patterns ---------------------------------------------------------------

# Subject header. Captures the code in parens and the subject name.
# Accepts both NTA formats:
#   2025 final answer key: "Subject: (703) LIFE SCIENCES"
#   2024 final answer key: "Subject : (703 ) Life Sciences"
SUBJECT_RE = re.compile(
    r"Subject\s*:\s*\(\s*(\d+)\s*\)\s*([A-Za-z][A-Za-z &,/\-]+?)(?:\s{2,}|\n|CSIR|FINAL|QUESTION\s*ID|$)",
    re.IGNORECASE,
)

# A token that looks like a question id: standalone integer, 6+ digits.
QID_RE = re.compile(r"^\d{6,}$")

# Answer shapes, in priority order.
ANS_SINGLE_RE = re.compile(r"^[1-9]$")
ANS_MULTI_RE = re.compile(r"^[1-9](?:\s*,\s*[1-9])+$")
ANS_OR_RE = re.compile(r"^[1-9]\s+or\s+[1-9]$", re.IGNORECASE)
ANS_DROP_RE = re.compile(r"^drop$", re.IGNORECASE)

# Tokens that always belong to the page chrome and should never be treated as data.
HEADER_NOISE = (
    "NATIONAL TESTING AGENCY",
    "Question ID",
    "Correct Option No.",
    "CORRECT ANSWER",
    "QUESTION ID",
    "Exam Date",
    "Exam Shift",
    "FINAL ANSWER KEY",
    "CSIR-UGC",
    "Page:",
    "of 6",
    "of 5",
    "of 4",
)


@dataclass
class AnswerEntry:
    question_id: str
    raw: str          # exactly what was printed
    kind: str         # "single" | "multi" | "or" | "drop" | "unknown"
    options: list[int] = field(default_factory=list)  # parsed numeric options when applicable


@dataclass
class SubjectAnswers:
    subject_code: str
    subject_name: str
    entries: dict[str, AnswerEntry] = field(default_factory=dict)
    page_indices: list[int] = field(default_factory=list)
    unrecognised: list[tuple[str, str]] = field(default_factory=list)
    duplicates: list[tuple[str, str, str]] = field(default_factory=list)  # (qid, prev_raw, new_raw)


def _classify_answer(raw: str) -> AnswerEntry | None:
    s = raw.strip()
    if not s:
        return None
    if ANS_SINGLE_RE.match(s):
        return AnswerEntry(question_id="", raw=s, kind="single", options=[int(s)])
    if ANS_MULTI_RE.match(s):
        opts = sorted({int(x.strip()) for x in s.split(",")})
        return AnswerEntry(question_id="", raw=s, kind="multi", options=opts)
    if ANS_OR_RE.match(s):
        nums = [int(x) for x in re.findall(r"[1-9]", s)]
        return AnswerEntry(question_id="", raw=s, kind="or", options=nums)
    if ANS_DROP_RE.match(s):
        return AnswerEntry(question_id="", raw="Drop", kind="drop")
    # Unknown shape — record it as-is for human review.
    return AnswerEntry(question_id="", raw=s, kind="unknown")


def _is_noise(token: str) -> bool:
    upper = token.upper()
    return any(needle.upper() in upper for needle in HEADER_NOISE)


def _tokenise(page_text: str) -> list[str]:
    """Split a page into the same tokens the renderer laid out, line by line."""
    tokens: list[str] = []
    for line in page_text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Tokens like "Question ID" with multi-spaces should stay as one logical token,
        # so split on runs of 2+ spaces. Single-space sequences keep things like "3 or 4".
        for chunk in re.split(r"\s{2,}", line):
            chunk = chunk.strip()
            if chunk:
                tokens.append(chunk)
    return tokens


def parse_answer_key(pdf_path: str | Path) -> dict:
    """Parse the entire key PDF.

    Returns a dict:
        {
          "subjects": {
             "703": SubjectAnswers(...),
             ...
          },
          "subject_order": ["703", "704", ...],
          "total_entries": int,
          "warnings": [str, ...]
        }
    """
    pdf_path = Path(pdf_path)
    doc = fitz.open(str(pdf_path))
    subjects: dict[str, SubjectAnswers] = {}
    subject_order: list[str] = []
    warnings: list[str] = []

    current: SubjectAnswers | None = None

    try:
        for page_idx in range(len(doc)):
            page_text = doc[page_idx].get_text()

            # A page can carry over the previous subject. Look for a fresh subject header.
            subj_match = SUBJECT_RE.search(page_text)
            if subj_match:
                code = subj_match.group(1).strip()
                name = subj_match.group(2).strip(" ,;:-")
                if code not in subjects:
                    subjects[code] = SubjectAnswers(subject_code=code, subject_name=name)
                    subject_order.append(code)
                current = subjects[code]
                current.page_indices.append(page_idx)
            elif current is not None:
                current.page_indices.append(page_idx)

            if current is None:
                # No subject yet — nothing to attach answers to.
                continue

            tokens = _tokenise(page_text)

            # Walk tokens; pair every QID with the next answer-shaped token.
            i = 0
            while i < len(tokens):
                tok = tokens[i]
                if _is_noise(tok):
                    i += 1
                    continue
                if QID_RE.match(tok):
                    qid = tok
                    # Find next answer token that isn't noise
                    j = i + 1
                    answer_entry: AnswerEntry | None = None
                    while j < len(tokens):
                        cand = tokens[j]
                        if _is_noise(cand):
                            j += 1
                            continue
                        # If the next token is itself another QID, the current one
                        # has no answer paired with it -> protocol violation.
                        if QID_RE.match(cand):
                            break
                        answer_entry = _classify_answer(cand)
                        j += 1
                        break
                    if answer_entry is None:
                        current.unrecognised.append((qid, ""))
                        i += 1
                        continue
                    answer_entry.question_id = qid
                    if qid in current.entries:
                        prev = current.entries[qid].raw
                        current.duplicates.append((qid, prev, answer_entry.raw))
                    if answer_entry.kind == "unknown":
                        current.unrecognised.append((qid, answer_entry.raw))
                    current.entries[qid] = answer_entry
                    i = j
                    continue
                i += 1

        total = sum(len(s.entries) for s in subjects.values())
        for s in subjects.values():
            if s.unrecognised:
                warnings.append(
                    f"Subject {s.subject_code} ({s.subject_name}): "
                    f"{len(s.unrecognised)} unrecognised answer token(s)"
                )
            if s.duplicates:
                warnings.append(
                    f"Subject {s.subject_code}: "
                    f"{len(s.duplicates)} duplicate question id(s) overwritten"
                )

        return {
            "subjects": subjects,
            "subject_order": subject_order,
            "total_entries": total,
            "warnings": warnings,
        }
    finally:
        doc.close()


def match_subject_for_qids(
    parsed: dict, question_ids: Iterable[str]
) -> tuple[SubjectAnswers | None, dict[str, int]]:
    """Find the subject whose IDs overlap most with the supplied question_ids.

    Returns (best_subject_or_None, {subject_code: matched_count}).
    """
    qid_set = {q for q in question_ids if q}
    counts: dict[str, int] = {}
    best: tuple[int, str | None] = (0, None)
    for code, subj in parsed["subjects"].items():
        n = sum(1 for q in qid_set if q in subj.entries)
        counts[code] = n
        if n > best[0]:
            best = (n, code)
    if best[1] is None:
        return None, counts
    return parsed["subjects"][best[1]], counts


def format_answer_text(entry: AnswerEntry) -> str:
    """Human-readable single-line answer text used in the rendered PDF."""
    if entry.kind == "single":
        return f"Correct Option: {entry.options[0]}"
    if entry.kind == "multi":
        return f"Correct Options: {', '.join(str(x) for x in entry.options)}  (multiple correct)"
    if entry.kind == "or":
        a, b = entry.options[0], entry.options[1]
        return f"Correct Option: {a} or {b}  (either accepted)"
    if entry.kind == "drop":
        return "Question dropped (all candidates awarded marks)"
    return f"Answer (raw): {entry.raw}"
