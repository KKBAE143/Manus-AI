#!/usr/bin/env python3
"""
extract_and_clean.py

Extracts text from a PDF, cleans it using heuristic filters to remove
chat/UI artifacts, and saves the result as chunked JSON files.
"""

import argparse
import json
import re
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fitz  # PyMuPDF

# --- Regex Constants from pdf_to_clean_docx.py ---

HARD_REMOVE_PATTERNS = [
    r"^\s*\[SOURCE PAGE \d+\]\s*$",
    r"^=====\s*PAGE\s+\d+\s*=====\s*$",
    r"^\s*Sure[!\.]?\s*$",
    r"^\s*Sure[,!]?\s+here.*$",
    r"^\s*Great question[!\.]?.*$",
    r"^\s*Good question[!\.]?.*$",
    r"^\s*Absolutely[!\.]?\s*$",
    r"^\s*Absolutely[,!]?\s+.*$",
    r"^\s*Of course[!\.]?.*$",
    r"^\s*Certainly[!\.]?.*$",
    r"^\s*Here is\s+.*$",
    r"^\s*Here's\s+.*content.*$",
    r"^\s*Here's\s+.*chapter.*$",
    r"^\s*Here's\s+.*section.*$",
    r"^\s*Here's\s+.*module.*$",
    r"^\s*Here's\s+.*table.*$",
    r"^\s*Here's\s+.*the next.*$",
    r"^\s*Let me now.*$",
    r"^\s*Let me (explain|start|begin|continue|present|summarize|write|provide).*$",
    r"^\s*Let's (now|begin|start|dive|explore|look).*$",
    r"^\s*Below is.*$",
    r"^\s*Awesome.*$",
    r"^\s*Which options do you want.*$",
    r"^\s*Think of this section as.*$",
    r"^\s*I kept it succinct.*$",
    r"^\s*I chose a comprehensive.*$",
    r"^\s*I will now.*$",
    r"^\s*I'll now.*$",
    r"^\s*I'll (begin|start|cover|explain|present|continue|write|move).*$",
    r"^\s*I've (now|already|just|covered|completed|finished).*$",
    r"^\s*As (I|we) (mentioned|discussed|said|noted|explained|covered).*$",
    r"^\s*As promised.*$",
    r"^\s*Now I'll.*$",
    r"^\s*Now let's.*$",
    r"^\s*Now, let's.*$",
    r"^\s*So basically.*$",
    r"^\s*So, (basically|let me|let's|here|we).*$",
    r"^\s*You (can|should|may|might|will) (see|note|notice|find|observe).*$",
    r"^\s*We've covered.*$",
    r"^\s*We (have now|will now|can now|should|need to).*$",
    r"^\s*This is the (next|final|last|first).*section.*$",
    r"^\s*Moving (on|forward|ahead|to the next).*$",
    r"^\s*In this (section|chapter|module|part|unit|topic),?\s*(I|we|you)?.*$",
    r"^\s*Would you like me to.*$",
    r"^\s*Before I generate.*$",
    r"^\s*Just confirm.*$",
    r"^\s*Once you reply.*$",
    r"^\s*Perfect.*$",
    r"^\s*Excellent.*$",
    r"^\s*Outstanding.*$",
    r"^\s*Done.*$",
    r"^\s*Your wish.*$",
    r"^\s*As your wish.*$",
    r"^\s*If you want, I can.*$",
    r"^\s*Here's what I'll do next.*$",
    r"^\s*Here is what I'll do next.*$",
    r"^\s*Shall I.*$",
    r"^\s*Yess+\s*!*\s*$",
    r"^\s*yes+\s*!*\s*$",
    r"^\s*No worries.*$",
    r"^\s*Buddy.*$",
    r"^\s*Dt\. Kaladhar.*$",
    r"^\s*GPT.*$",
    r"^\s*ChatGPT.*$",
    r"^\s*Visible:\s*\d+%.*$",
    r"^\s*<<?ImageDisplayed>>?\s*$",
    r"^\s*Page \d+ of \d+\s*$",
    r"^\s*Sound good, buddy\??\s*$",
    r"^\s*If yes, I'll proceed.*$",
    r"^\s*Here's the plan for the next output.*$",
    r"^\s*It will include:\s*$",
    r"^\s*Before I start writing, please confirm.*$",
    r"^\s*Would you like this section titled\s*$",
    r"^\s*Both are professional.*$",
    r"^\s*Which one should I go with\??\s*$",
    r"^\s*Now I'll start building it step-by-step with:\s*$",
    r"^\s*Now, everything is ready for final Word formatting\.?\s*$",
    r"^\s*It'll include:\s*$",
    r"^\s*Elegant section dividers\s*$",
    r"^\s*Indexed headers.*$",
    r"^\s*Color-accented boxes.*$",
    r"^\s*The 'Summary & Quick Recall Sheet' at the end\s*$",
    r"^\s*Word\):\s*$",
    r"^\s*Should it be:\s*$",
    r"^\s*or shorter like:\s*$",
    r"^\s*Which one should I lock in.*$",
    r"^\s*Here's what happens next:\s*$",
    r"^\s*Before I start the compilation pass:\s*$",
    r"^\s*So the next step:.*$",
    r"^\s*Final Professional Sign-off\s*$",
    r"^\s*Liver & Renal Sections\s*$",
    r"^\s*Summary \+ Quick-Recall Sheet\s*$",
    r"^\s*Next Module Preview\s*$",
    r"^\s*Clinical Nutritionist & (Culinary )?Nutrition Expert\s*$",
    r"^\s*NutriRevive Wellness Studio\s*\|.*$",
    r"^\s*Would you like a dedication page.*$",
    r"^\s*\d+\. I'll merge all confirmed content.*$",
    r"^\s*\d+\. I'll generate both \.docx and \.pdf outputs.*$",
    r"^\s*\d+\. You'll receive a version.*$",
    r"^\s*Shall we begin.*$",
    r"^\s*or simply\s*$",
    r"^\s*everyday dietitians\.\s*$",
    r"^\s*complete on its own\??\s*$",
    r"^\s*and practitioner-friendly nutrition modules ever written!?\s*$",
    r"^\s*Next Module Preview\s*-.*$",
    r"^\s*Final Tagline\s*$",
    r"^\s*Now, I'll start compiling the Word version.*$",
    r"^\s*[^A-Za-z0-9]*Dt\. Kaladhar.*$",
    r"^\s*Next Module:\s*\d+.*$",
    r"^\s*Integration\s*$",
    r"^\s*and structure intact\.\s*$",
    r"^\s*digital release\.\s*$",
    r'^\s*Health Through Food Wisdom\."\s*$',
]

SOFT_REMOVE_CONTAINS = [
    "emoji", "ui fragments", "conversational confirmations",
    "chat interface", "output limit", "strict preservation extraction",
    "source preservation check", "continuity note",
]

EXTRA_CONVERSATIONAL_HINTS = [
    "or simply", "which one should i go with", "your wish",
    "here's how the final ending block", "next module preview",
    "everything is now locked in", "so the next step",
    "would you like a dedication page", "before i hit finalize",
    "before i start the compilation pass", "i'll generate both .docx and .pdf",
    "you'll receive a version", "shall we begin", "we're now entering",
    "this chapter is where clinical accuracy meets patient practicality",
    "benchmark for practical clinical nutrition handbooks",
]

EXTRA_DROP_REGEX = [
    re.compile(r'^\s*complete on its own\??\s*$', re.I),
    re.compile(r'^\s*everyday dietitians\.\s*$', re.I),
    re.compile(r"^\s*it's complete, polished, and publication-ready.*$", re.I),
    re.compile(r'^\s*clinical nutritionist & culinary nutrition expert\s*$', re.I),
    re.compile(r'^\s*nutrirevive wellness studio.*$', re.I),
    re.compile(r'^\s*"Knowledge becomes power only when applied with purpose\."\s*$', re.I),
    re.compile(r'^\s*and structure intact\.\s*$', re.I),
    re.compile(r'^\s*digital release\.\s*$', re.I),
    re.compile(r'^\s*Health Through Food Wisdom\."\s*$', re.I),
    re.compile(r'^\s*therapy alignment - making nutrition science instantly usable.*$', re.I),
    re.compile(r'^\s*"Case\s+\d+\s*-.*"\??\s*$', re.I),
    re.compile(r'^\s*cucumber slices"\)\.\s*$', re.I),
]

LIKELY_NONCONTENT_CONTAINS = [
    "would you like me to create that file version",
    "once you confirm",
    "i'll now build this into the full file structure",
    "before i generate the word file",
    "just confirm these 3 details",
    "do you prefer the document layout",
    "sound good, buddy",
    "if yes, i'll proceed with the full formatted",
    "here's the plan for the next output",
    "before i start writing, please confirm one small thing",
    "would you like this section titled",
    "which one should i go with",
    "now i'll start building it step-by-step",
    "everything is ready for final word formatting",
    "copy it directly into word",
    "hard copy set",
    "signature manual",
    "same professional-educational, clinic-ready format",
    "this title gives it a clinical touch",
    "the first one emphasizes scientific depth",
    "the second one looks cleaner for clinic use",
    "upcoming cardio-endocrine disorders module",
    "color-accented boxes",
    "indexed headers",
    "most premium and practitioner-friendly nutrition modules ever written",
    "ready-to-print, ready-to-publish version",
    "just confirm one tiny detail for the footer line",
    "the first looks more professional for publication",
    "it's complete, polished, and publication-ready",
    "here's what happens next",
    "before i start the compilation pass",
    "dedication page",
    "i'll merge all confirmed content",
    "i'll generate both .docx and .pdf outputs",
    "you'll receive a version you can open directly in word",
    "final ending block + preview",
    "everything is now locked in",
    "final professional sign-off",
    "professionally formatted word layout",
    "professional, motivating, and reader-engaging",
    "coming up next in the advanced diet modification manual",
    "this upcoming module explores the interlinked pathways",
    "reader message", "table of contents", "full sections",
    "appendices", "acknowledgments", "summary & quick recall sheet",
    "endocrine health, connecting:", "it's the most essential and applied module",
    "dietitian and nutritionist - the diabetes mellitus", "shall we begin",
    "we're now entering the most crucial and career-defining module",
    "this chapter is where clinical accuracy meets patient practicality",
    "you'll learn not only how to plan diets",
    "the skill that sets top clinical dietitians apart",
]

EMOJI_RE = re.compile(
    "[" "\U0001F300-\U0001FAFF" "\u2600-\u27BF" "]+",
    flags=re.UNICODE,
)
WEIRD_BULLETS_RE = re.compile(r"[•●◦▪■◆◇▶►▸▹➤➜➔]+")
MULTISPACE_RE = re.compile(r"[ \t]{2,}")
MULTIBLANK_RE = re.compile(r"\n{3,}")

PERSONAL_DATA_RE = [
    re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
    re.compile(r"(?:ph\.?\s*(?:no\.?|num\.?|number)?\s*[:;]?\s*|phone\s*[:;]\s*|mobile\s*[:;]\s*|contact\s*[:;]\s*)[\+]?\d[\d\s\-]{7,14}", re.I),
    re.compile(r"(?<!\d)\d{10}(?!\d)"),
]

NUMBER_EMOJI_MAP = {
    "1\u20e3": "1.", "2\u20e3": "2.", "3\u20e3": "3.", "4\u20e3": "4.",
    "5\u20e3": "5.", "6\u20e3": "6.", "7\u20e3": "7.", "8\u20e3": "8.",
    "9\u20e3": "9.", "\U0001f51f": "10.",
}
NUMBER_EMOJI_RE = re.compile("|".join(re.escape(k) for k in NUMBER_EMOJI_MAP))

TEXT_FUSION_RE = re.compile(r"([a-z])([A-Z])")
DIGIT_LETTER_RE = re.compile(r"(\d)([A-Za-z])")
LETTER_DIGIT_RE = re.compile(r"([a-z])(\d)")

PIPE_TABLE_RE = re.compile(r"^\s*\|.+\|.+\|\s*$")

CHAT_DROP_PATTERNS = [
    re.compile(r"\bi read the manual\b", re.I),
    re.compile(r"\bfrom my end i want\b", re.I),
    re.compile(r"\bas of now i work\b", re.I),
    re.compile(r"\bsoon gonna leave\b", re.I),
    re.compile(r"\bin that mention what is for what\b", re.I),
    re.compile(r"\bthat'?s exactly the mindset\b", re.I),
    re.compile(r"\byou'?re thinking like a\b", re.I),
    re.compile(r"\blet'?s design this upgrade\b", re.I),
    re.compile(r"\bgreat choice[!.]?\s*starting with\b", re.I),
    re.compile(r"\bnext,\s*would you like me to create\b", re.I),
    re.compile(r"\bwould you like me to create section\b", re.I),
    re.compile(r"\bthis next section will be your secret\b", re.I),
    re.compile(r"\bif you want,?\s*i'?ll now make you\b", re.I),
    re.compile(r"\byess please[!.]?\b", re.I),
    re.compile(r"\bspot on[!.]?\b", re.I),
    re.compile(r"\b-\s*let'?s roll[!.]?\b", re.I),
    re.compile(r"\b-\s*great choice[!.]?\b", re.I),
    re.compile(r"\bkaladhar\s*[-–]\s*we'?re now building\b", re.I),
    re.compile(r"\bit'?ll make you unbeatable\b", re.I),
    re.compile(r"\byour clients will never need a second opinion\b", re.I),
    re.compile(r"\bonce we create this,? you'?ll have\b", re.I),
    re.compile(r"\bword\s*\+\s*pdf version\b", re.I),
    re.compile(r"\bwhich do you prefer\b", re.I),
    re.compile(r"\bconfirm these\s*\d*\s*final details\b", re.I),
    re.compile(r"\bfinal structure[:\s]*['\"]?platinum\b", re.I),
    re.compile(r"\bplanned structure inside the file\b", re.I),
    re.compile(r"\bfront page setup\b.*edition\b", re.I),
    re.compile(r"\blayout selection option\b", re.I),
    re.compile(r"\bformat plan\b", re.I),
    re.compile(r"\bplacement order\b", re.I),
    re.compile(r"\bthis will be your professional toolbook\b", re.I),
    re.compile(r"\bmaster dietitian daily clinical bible\b", re.I),
    re.compile(r"\bdiet modification master manual\b", re.I),
    re.compile(r"\bnavath\s*kaladhar\b", re.I),
    re.compile(r"\bnavathkaladhar\b", re.I),
]

LIST_ITEM_RE = re.compile(
    r"^\s*(?:"
    r"[-\u2013\u2014\u2022\u25cf\u25aa\u25ab\u2023\u00b7]\s+"
    r"|[a-zA-Z0-9]{1,3}[.)]\s+"
    r"|\d{1,3}[.)]\s+"
    r")"
)

# --- Helper Functions from pdf_to_clean_docx.py ---

def _replace_number_emoji(m: "re.Match[str]") -> str:
    return NUMBER_EMOJI_MAP.get(m.group(0), m.group(0))

def normalize_line(line: str) -> str:
    line = line.replace("\u00a0", " ")
    line = line.replace("\u2018", "'")
    line = line.replace("\u2019", "'")
    line = line.replace("\u201c", '"')
    line = line.replace("\u201d", '"')
    line = line.replace("\u2013", "-")
    line = line.replace("\u2014", "-")
    line = line.replace("\ufe0f", "")
    line = line.replace("\u200d", "")
    line = line.replace("\ufffe", "")
    line = line.replace("\ufffd", "")
    line = NUMBER_EMOJI_RE.sub(_replace_number_emoji, line)
    line = EMOJI_RE.sub("", line)
    line = WEIRD_BULLETS_RE.sub("-", line)

    # Strip personal data
    for pat in PERSONAL_DATA_RE:
        line = pat.sub("", line)

    line = MULTISPACE_RE.sub(" ", line).strip()
    return line

def should_drop_line(line: str) -> bool:
    if not line.strip():
        return False
    lower = line.lower().strip()
    for pat in HARD_REMOVE_PATTERNS:
        if re.match(pat, line, flags=re.I): return True
    for token in SOFT_REMOVE_CONTAINS:
        if token in lower: return True
    for token in EXTRA_CONVERSATIONAL_HINTS:
        if token in lower: return True
    for token in LIKELY_NONCONTENT_CONTAINS:
        if token in lower: return True
    for pat in EXTRA_DROP_REGEX:
        if pat.match(line): return True
    if lower in {"yes", "yess", "perfect", "excellent", "done"}: return True
    if PIPE_TABLE_RE.match(line): return True
    if re.match(r"^\d{1,2}\.\s*$", line.strip()): return True
    for pat in CHAT_DROP_PATTERNS:
        if pat.search(line): return True
    return False

def fix_text_fusion(text: str) -> str:
    text = TEXT_FUSION_RE.sub(r"\1 \2", text)
    text = DIGIT_LETTER_RE.sub(r"\1 \2", text)
    text = LETTER_DIGIT_RE.sub(r"\1 \2", text)
    text = re.compile(r",([A-Za-z])").sub(r", \1", text)
    return text

def _detect_column_gaps(lines: List[str], min_gap: int = 3) -> List[int]:
    if not lines: return []
    max_len = max(len(l) for l in lines)
    col_has_char = [False] * max_len
    for line in lines:
        for i, ch in enumerate(line):
            if ch != " ": col_has_char[i] = True
    gap_positions: List[int] = []
    in_gap = False
    gap_start = 0
    for i in range(max_len):
        if not col_has_char[i]:
            if not in_gap:
                gap_start = i
                in_gap = True
        else:
            if in_gap:
                if i - gap_start >= min_gap:
                    gap_positions.append(gap_start + (i - gap_start) // 2)
                in_gap = False
    return gap_positions

def reconstruct_column_table(lines: List[str], min_rows: int = 3, min_cols: int = 2, min_gap: int = 4) -> Optional[str]:
    if len(lines) < min_rows: return None
    gaps = _detect_column_gaps(lines, min_gap)
    if len(gaps) < min_cols - 1: return None
    split_points = [0] + gaps
    rows: List[List[str]] = []
    for line in lines:
        cells: List[str] = []
        for idx, start in enumerate(split_points):
            end = split_points[idx + 1] if idx + 1 < len(split_points) else len(line)
            cells.append(line[start:end].strip())
        rows.append(cells)
    table_lines = [" | ".join(row) for row in rows]
    return "\n".join(table_lines)

def clean_page_text(text: str) -> str:
    raw_lines = text.splitlines()
    kept_lines: List[str] = []

    # Simple column table reconstruction logic (simplified from original for brevity)
    candidate_table_blocks: List[List[str]] = []
    current_block: List[str] = []
    for raw_line in raw_lines:
        if raw_line.strip():
            current_block.append(raw_line)
        else:
            if current_block: candidate_table_blocks.append(current_block)
            current_block = []
    if current_block: candidate_table_blocks.append(current_block)

    for block in candidate_table_blocks:
        if len(block) >= 3:
            table_str = reconstruct_column_table(block)
            if table_str:
                kept_lines.append(table_str)
                continue
        for raw in block:
            line = normalize_line(raw)
            if not line or should_drop_line(line): continue
            line = fix_text_fusion(line)
            kept_lines.append(line)

    text = "\n\n".join(kept_lines).strip()
    return MULTIBLANK_RE.sub("\n\n", text)

# --- Main Extraction Logic ---

def extract_pdf_pages(pdf_path: Path, start_page: int, end_page: int) -> List[Dict[str, Any]]:
    doc = fitz.open(pdf_path)
    total_pages = len(doc)

    start_idx = max(0, start_page - 1)
    end_idx = min(total_pages - 1, end_page - 1)

    results = []
    for i in range(start_idx, end_idx + 1):
        page = doc[i]
        # Prefer get_text("text") for general layout, then clean
        raw_text = page.get_text("text")
        cleaned = clean_page_text(raw_text)
        if cleaned.strip():
            results.append({
                "page_num": i + 1,
                "text": cleaned
            })
    doc.close()
    return results

def main():
    parser = argparse.ArgumentParser(description="Extract and clean PDF text to JSON chunks.")
    parser.add_argument("--input", required=True, help="Path to input PDF")
    parser.add_argument("--output-dir", required=True, help="Directory to save JSON chunks")
    parser.add_argument("--start-page", type=int, default=1, help="1-based start page")
    parser.add_argument("--end-page", type=int, default=100000, help="1-based end page")
    parser.add_argument("--chunk-size", type=int, default=50, help="Pages per JSON chunk")

    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Extracting pages {args.start_page} to {args.end_page} from {input_path}...")
    pages = extract_pdf_pages(input_path, args.start_page, args.end_page)

    # Chunk and save
    for i in range(0, len(pages), args.chunk_size):
        chunk = pages[i : i + args.chunk_size]
        chunk_idx = (i // args.chunk_size) + 1
        output_file = output_dir / f"chunk_{chunk_idx:02d}.json"

        data = {
            "chunk_index": chunk_idx,
            "pages": chunk
        }

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Done. Saved {((len(pages)-1)//args.chunk_size)+1} chunk(s) to {output_dir}")

if __name__ == "__main__":
    main()
