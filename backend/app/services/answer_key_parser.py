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

# Alternate 2023-style header used in some keys:
#   "Subject :\nCHE - CHEMICAL SCIENCES"   (no parenthesised numeric code, just
#                                            a 3-letter abbreviation)
# We capture the abbreviation as the synthetic "code" and the full name.
SUBJECT_ABBR_RE = re.compile(
    r"Subject\s*:\s*\n?\s*([A-Z]{2,4})\s*[-\u2010\u2013\u2014]\s*([A-Z][A-Z &,/\-]+?)(?:\s{2,}|\n|$)",
    re.IGNORECASE,
)

# 2022-style:
#   "Subject :\n702 - CSIR Earth Atmospheric Ocean N Planetary Science"
# Numeric code without parens, hyphen separator.
SUBJECT_NUM_HYPHEN_RE = re.compile(
    r"Subject\s*:\s*\n?\s*(\d{3})\s*[-\u2010\u2013\u2014]\s*([A-Za-z][A-Za-z0-9 &,/\-]+?)(?:\s{2,}|\n|$)",
    re.IGNORECASE,
)

# Dec 2024-style:
#   "Subject : Earth Science"
# Just "Subject : <name>" with no abbreviation or number; the data IDs
# themselves carry the subject prefix (702xxx, 703xxx, ...).
SUBJECT_NAME_ONLY_RE = re.compile(
    r"Subject\s*:\s*([A-Z][A-Za-z][A-Za-z &,/\-]+?)(?:\s{2,}|\n|$)",
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
    use_short_id_mode: bool = False  # set True when matched via abbr/num-hyphen/name-only headers


# --- CSIR text-PDF style key (used with the textpdf cleaner) ---------------

# Look for a section trailer like "Subject: Life Science" (no parens, no code).
TEXTPDF_SUBJECT_RE = re.compile(
    r"Subject\s*:\s*([A-Za-z][A-Za-z &\-]+?)\s*$",
    re.MULTILINE,
)

# This format prints each answer cell as "<qid>\n<answer>\n" pairs. Answers
# can be:
#   "503"                -> single Option ID
#   "129 ,132"            -> multiple Option IDs (with weird spacing)
#   "Dropped"            -> question dropped
#   "161(English)/Dropped(Hindi)"  -> partial drop, treat raw
#   "*41"                -> asterisked qids carry footnote info
TEXTPDF_QID_RE = re.compile(r"^\*?(\d{1,4})$")
TEXTPDF_ANSWER_RE = re.compile(
    r"^("
    r"\d{1,5}(?:\s*,\s*\d{1,5})*"               # 503  or  129 ,132
    r"|Dropped"
    r"|\d{1,5}\(English\)/Dropped\(Hindi\)"     # 161(English)/Dropped(Hindi)
    r"|Dropped\(English\)/\d{1,5}\(Hindi\)"
    r")$",
    re.IGNORECASE,
)


def _classify_textpdf_answer(raw: str) -> AnswerEntry:
    s = raw.strip()
    if not s:
        return AnswerEntry(question_id="", raw="", kind="unknown")
    if re.fullmatch(r"Dropped", s, re.IGNORECASE):
        return AnswerEntry(question_id="", raw="Dropped", kind="drop")
    # Multi-Option-ID list like "129 ,132" - keep as multi
    parts = re.split(r"\s*,\s*", s)
    if all(p.strip().isdigit() for p in parts):
        opts = sorted({int(p.strip()) for p in parts if p.strip().isdigit()})
        if len(opts) == 1:
            return AnswerEntry(question_id="", raw=str(opts[0]), kind="single", options=opts)
        return AnswerEntry(question_id="", raw=", ".join(str(o) for o in opts), kind="multi", options=opts)
    # Hindi/English partial-drop or other - record raw for human review
    return AnswerEntry(question_id="", raw=s, kind="unknown")


def _parse_textpdf_key(doc: fitz.Document) -> dict:
    """Parse a CSIR text-PDF style answer key.

    Returns the same dict shape as :func:`parse_answer_key`. Each subject
    gets the textual subject name as both the code and name (since this
    format has no numeric code), so callers can still look up by name.
    """
    subjects: dict[str, SubjectAnswers] = {}
    subject_order: list[str] = []
    warnings: list[str] = []

    # Walk the pages and snapshot all tokens *with* their page so we can
    # bucket per-section. The trailer "Subject: Life Science" appears at
    # the END of each section's pages, so we collect all tokens for a page,
    # see which subject the page declares, then attach them.
    for page_idx in range(len(doc)):
        page_text = doc[page_idx].get_text()
        subj_match = TEXTPDF_SUBJECT_RE.search(page_text)
        if not subj_match:
            # No declared subject on this page; skip rather than guess.
            continue
        subject_name = subj_match.group(1).strip()
        # Use the name as a synthetic code (no parenthesised number in this format)
        code = subject_name.upper()

        if code not in subjects:
            subjects[code] = SubjectAnswers(
                subject_code=code, subject_name=subject_name
            )
            subject_order.append(code)
        subj = subjects[code]
        subj.page_indices.append(page_idx)

        # Tokenise the page line by line
        lines = [ln.strip() for ln in page_text.splitlines() if ln.strip()]
        # Walk pairs.
        i = 0
        while i < len(lines):
            ln = lines[i]
            qid_match = TEXTPDF_QID_RE.match(ln)
            if qid_match and TEXTPDF_ANSWER_RE.match(lines[i + 1] if i + 1 < len(lines) else ""):
                qid = qid_match.group(1)
                ans = lines[i + 1]
                entry = _classify_textpdf_answer(ans)
                entry.question_id = qid
                if qid in subj.entries:
                    subj.duplicates.append((qid, subj.entries[qid].raw, entry.raw))
                if entry.kind == "unknown":
                    subj.unrecognised.append((qid, entry.raw))
                subj.entries[qid] = entry
                i += 2
                continue
            i += 1

    total = sum(len(s.entries) for s in subjects.values())
    for s in subjects.values():
        if s.unrecognised:
            warnings.append(
                f"{s.subject_name}: {len(s.unrecognised)} unrecognised answer token(s)"
            )
        if s.duplicates:
            warnings.append(
                f"{s.subject_name}: {len(s.duplicates)} duplicate question id(s) overwritten"
            )

    return {
        "subjects": subjects,
        "subject_order": subject_order,
        "total_entries": total,
        "warnings": warnings,
    }


def looks_like_textpdf_key(doc: fitz.Document) -> bool:
    """Quick sniff: are we looking at a CSIR text-PDF style key (no Subject:
    (NNN) NAME headers, but has Subject: NAME trailers and 1-4 digit qids)?
    """
    sample = "\n".join(doc[i].get_text() for i in range(min(3, len(doc))))
    # If the standard format detector matches, prefer that
    if SUBJECT_RE.search(sample):
        return False
    # Else look for the textpdf signature
    if TEXTPDF_SUBJECT_RE.search(sample):
        # Make sure we have the column headers too
        if "Correct Option ID" in sample:
            return True
    return False


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


def _classify_short_id_answer(raw: str) -> AnswerEntry | None:
    """Classify an answer-cell value from the 2022-style "short id" key.

    Allowed shapes:
      "3"               -> single option-number style answer (1-4)
      "503"             -> single Option ID
      "501,504"         -> multiple Option IDs (multi-correct)
      "501 or 503"      -> either Option ID accepted
      "Dropped" / "Drop" -> question dropped
      "*"               -> "Marks awarded to all who attempted the question"
                           per the footnote on these keys; treat as Drop.
    """
    s = raw.strip()
    if not s:
        return None
    # Bare asterisk = "marks awarded to all" per the key's footnote
    if s in ("*", "(*)"):
        return AnswerEntry(question_id="", raw="* (marks awarded to all)", kind="drop")
    s = s.rstrip("*").strip()
    if not s:
        return AnswerEntry(question_id="", raw="* (marks awarded to all)", kind="drop")
    if re.fullmatch(r"Dropped|Drop", s, re.IGNORECASE):
        return AnswerEntry(question_id="", raw="Dropped", kind="drop")
    # Single integer
    if re.fullmatch(r"\d{1,5}", s):
        return AnswerEntry(question_id="", raw=s, kind="single", options=[int(s)])
    # Multi (comma-separated list of integers; tolerate trailing comma)
    if re.fullmatch(r"\d{1,5}(?:\s*,\s*\d{1,5})+,?", s):
        opts = sorted({int(p.strip()) for p in s.split(",") if p.strip().isdigit()})
        return AnswerEntry(
            question_id="",
            raw=", ".join(str(x) for x in opts),
            kind="multi",
            options=opts,
        )
    # "X or Y"
    if re.fullmatch(r"\d{1,5}\s+or\s+\d{1,5}", s, re.IGNORECASE):
        nums = [int(x) for x in re.findall(r"\d+", s)]
        return AnswerEntry(question_id="", raw=s, kind="or", options=nums)
    # Anything else - flag for human review
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
    try:
        # CSIR text-PDF style keys have a different layout (no parenthesised
        # subject codes; Option IDs instead of option numbers; multi-column
        # tabular layout). Detect and dispatch.
        if looks_like_textpdf_key(doc):
            return _parse_textpdf_key(doc)

        return _parse_standard_key(doc)
    finally:
        doc.close()


def _parse_standard_key(doc: fitz.Document) -> dict:
    """Parse the standard NTA/CSIR-UGC NET answer-key format."""
    subjects: dict[str, SubjectAnswers] = {}
    subject_order: list[str] = []
    warnings: list[str] = []

    current: SubjectAnswers | None = None

    for page_idx in range(len(doc)):
        page_text = doc[page_idx].get_text()

        # A page can carry over the previous subject. Look for a fresh subject header.
        subj_match = SUBJECT_RE.search(page_text)
        abbr_match = None if subj_match else SUBJECT_ABBR_RE.search(page_text)
        num_hyphen_match = None if (subj_match or abbr_match) else SUBJECT_NUM_HYPHEN_RE.search(page_text)
        # Last-resort: bare "Subject : Name" with no code or abbreviation.
        # We synthesize a code from the leading word(s) of the name. This
        # path only fires when none of the more specific patterns matched.
        name_only_match = (
            None if (subj_match or abbr_match or num_hyphen_match)
            else SUBJECT_NAME_ONLY_RE.search(page_text)
        )
        if subj_match:
            code = subj_match.group(1).strip()
            name = subj_match.group(2).strip(" ,;:-")
            if code not in subjects:
                subjects[code] = SubjectAnswers(subject_code=code, subject_name=name)
                subject_order.append(code)
            current = subjects[code]
            current.page_indices.append(page_idx)
        elif abbr_match:
            # 2023-style "Subject :\nCHE - CHEMICAL SCIENCES" header. We use
            # the abbreviation as the synthetic code so callers can group by
            # subject; if the abbr already exists keep it, otherwise create.
            abbr = abbr_match.group(1).strip().upper()
            name = abbr_match.group(2).strip(" ,;:-")
            if abbr not in subjects:
                subjects[abbr] = SubjectAnswers(
                    subject_code=abbr, subject_name=name, use_short_id_mode=True
                )
                subject_order.append(abbr)
            current = subjects[abbr]
            current.page_indices.append(page_idx)
        elif num_hyphen_match:
            # 2022-style "Subject :\n702 - CSIR Life Sciences" header.
            code = num_hyphen_match.group(1).strip()
            name = num_hyphen_match.group(2).strip(" ,;:-")
            if code not in subjects:
                subjects[code] = SubjectAnswers(
                    subject_code=code, subject_name=name, use_short_id_mode=True
                )
                subject_order.append(code)
            current = subjects[code]
            current.page_indices.append(page_idx)
        elif name_only_match:
            # Dec 2024-style "Subject : Life Science" - synthesize a code
            # from the name so callers can group consistently.
            name = name_only_match.group(1).strip(" ,;:-")
            code = name.upper().replace(" ", "_")
            if code not in subjects:
                subjects[code] = SubjectAnswers(
                    subject_code=code, subject_name=name, use_short_id_mode=True
                )
                subject_order.append(code)
            current = subjects[code]
            current.page_indices.append(page_idx)
        elif current is not None:
            current.page_indices.append(page_idx)

        if current is None:
            # No subject yet — nothing to attach answers to.
            continue

        tokens = _tokenise(page_text)

        # Some keys (e.g. CSIR NET Nov 2020 / "8key.pdf") use Option ID values
        # in the answer column where each answer ID is itself a 6+ digit
        # number indistinguishable from a Question ID. The standard pair
        # logic below would treat the answer as the next QID. Detect the
        # column header and switch off the "next token must not be a QID"
        # safety check.
        answers_are_option_ids = (
            "Correct Option ID" in page_text or "CORRECT OPTION ID" in page_text
        )

        # The "alternating pairs" mode is used for keys without parenthesised
        # numeric subject codes (2022-style "702 - NAME" header, Dec 2024-style
        # "Subject : NAME" header). Some of these keys mix small integers
        # (1-20 for general-aptitude) with full 6-digit IDs (702101+ for
        # subject-specific) on the SAME page, so we cannot rely on the
        # 6-digit-ish QID_RE alone. The subject's `use_short_id_mode` flag
        # tells us which parser to run.
        is_short_id_mode = current.use_short_id_mode and (
            "Correct" in page_text
            and (
                "Option ID" in page_text
                or "OPTION ID" in page_text
                or "Key" in page_text
            )
        )

        if is_short_id_mode:
            # Collect every integer token after the FIRST "Option ID" column
            # header on the page (later mentions like the footer
            # "Note :- Correct Option ID '*' means ..." must NOT be used as a
            # marker because they would skip past all the data).
            #
            # We can't use _tokenise's joined-by-multispace splitter directly
            # because the integers each sit on their own line; just walk the
            # raw lines instead.
            raw_lines = [ln.strip() for ln in page_text.splitlines() if ln.strip()]
            # Find column-header marker (first occurrence ONLY)
            header_idx = -1
            for li, ln in enumerate(raw_lines):
                # Skip lines that are clearly notes/footers.
                if ln.lower().startswith(("note", "*", "(*)")):
                    continue
                if ln in (
                    "Option ID", "OPTION ID",
                    "Correct Option ID", "CORRECT OPTION ID",
                    "Key", "KEY",
                    "Correct Key", "CORRECT KEY",
                ):
                    header_idx = li
                    break
            data_lines = raw_lines[header_idx + 1:] if header_idx >= 0 else raw_lines
            # Now walk in pairs: (qid_line, answer_line)
            di = 0
            while di + 1 < len(data_lines):
                qid_str = data_lines[di]
                ans_str = data_lines[di + 1]
                # Skip section trailers ("NATIONAL TESTING AGENCY" etc.)
                if _is_noise(qid_str) or _is_noise(ans_str):
                    di += 1
                    continue
                # qid must be a small/medium integer (1-4 digits or 6-7 digits)
                if not re.fullmatch(r"\d{1,7}", qid_str):
                    di += 1
                    continue
                # answer can be: single int, "Dropped", "Multi" int list ("501,504"),
                # or "1 or 2"-style.
                ans_clean = ans_str.strip()
                entry = _classify_short_id_answer(ans_clean)
                if entry is None:
                    di += 1
                    continue
                entry.question_id = qid_str
                if qid_str in current.entries:
                    current.duplicates.append((qid_str, current.entries[qid_str].raw, entry.raw))
                if entry.kind == "unknown":
                    current.unrecognised.append((qid_str, entry.raw))
                current.entries[qid_str] = entry
                di += 2
            continue

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

                    # When answer column is Option ID, the cand may be a
                    # bare big integer OR a big integer with trailing comma
                    # (multi-correct continuation). Handle the comma case
                    # FIRST so we don't fall through to the standard logic.
                    if answers_are_option_ids and re.fullmatch(r"\d{6,},", cand):
                        # Strip trailing comma and look ahead to collect
                        # all comma-continued option ids.
                        multi_opts = [int(cand.rstrip(","))]
                        k = j + 1
                        while k < len(tokens):
                            nxt = tokens[k]
                            if _is_noise(nxt):
                                k += 1
                                continue
                            stripped = nxt.rstrip(",")
                            if not re.fullmatch(r"\d{6,}", stripped):
                                break
                            multi_opts.append(int(stripped))
                            k += 1
                            if not nxt.endswith(","):
                                break
                        answer_entry = AnswerEntry(
                            question_id="",
                            raw=", ".join(str(o) for o in multi_opts),
                            kind="multi",
                            options=multi_opts,
                        )
                        j = k
                        break

                    # If the next token is itself another QID, the current one
                    # has no answer paired with it -> protocol violation.
                    # Exception: when the column header advertises "Correct
                    # Option ID" the answer column ALSO contains big numbers
                    # that match QID_RE; pair them anyway.
                    if QID_RE.match(cand) and not answers_are_option_ids:
                        break
                    if answers_are_option_ids and QID_RE.match(cand):
                        # Treat the option-id as a single big integer.
                        answer_entry = AnswerEntry(
                            question_id="", raw=cand, kind="single",
                            options=[int(cand)],
                        )
                        j += 1
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
