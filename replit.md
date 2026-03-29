# Manuscript Converter

A full-stack PDF-to-DOCX manuscript conversion platform with AI-powered text cleanup.

## Architecture

- **Frontend**: React + Vite + TypeScript + Tailwind CSS (port 5000)
- **Backend**: FastAPI + SQLAlchemy + Celery (port 8000)
- **Database**: PostgreSQL (via Replit's managed DB, `DATABASE_URL` env var)
- **Storage**: Local filesystem (`backend/storage/`)
- **Auth**: Firebase (Google auth, disabled by default via `VITE_DISABLE_AUTH=true`)

## Project Structure

```
/
├── src/                    # React frontend source
│   ├── App.tsx             # Root app with routing and auth guard
│   ├── pages/              # Dashboard, Upload, Configuration, Documents, etc.
│   ├── components/         # Sidebar, Header, reusable UI
│   ├── contexts/           # AuthContext (Firebase)
│   ├── lib/api.ts          # Backend API client (proxied via Vite)
│   ├── utils/              # Gemini AI service, PDF processor
│   └── firebase.ts         # Firebase initialization
├── backend/
│   ├── app/
│   │   ├── main.py         # FastAPI app entry point
│   │   ├── api/            # API routes (documents.py, manuscript.py)
│   │   ├── core/           # Config, database, celery
│   │   ├── models/         # SQLAlchemy models (document.py + manuscript models)
│   │   ├── schemas/        # Pydantic schemas
│   │   ├── services/       # manuscript_pipeline.py, manuscript_assembler.py
│   │   └── tasks/          # Celery task orchestration
│   ├── storage/            # Uploads, outputs, SQLite/Postgres DB
│   └── start.sh            # Backend start script
├── pdf_to_clean_docx.py    # Core PDF-to-DOCX conversion logic
├── vite.config.ts          # Vite config (port 5000, proxy /api to :8000)
└── firebase-applet-config.json  # Firebase config
```

## Core Pipeline Services

- `backend/app/services/chapter_detector.py` — Chapter boundary detection using PyMuPDF font-size analysis and heading pattern matching. Provides `detect_chapter_boundaries()`, `detect_chapter_boundaries_with_fallback()` (with AI fallback when < 3 boundaries/100 pages), `group_chapters_into_chunks()`, `check_table_safety()`. Used when `split_mode` is `chapters` or `hybrid`.
- `backend/app/services/manuscript_pipeline.py` — Main pipeline: chunk planning (page-count or chapter-aware), extraction, cleanup, **AI transformation**, DOCX generation, merge support, final assembly with front matter. Pipeline stages: queued → inspect → plan → extract → clean_pass_1 → clean_pass_2 → final_normalize → **ai_transform** → part_generate → appendix_extract → merge_prep → completed.
- `backend/app/services/manuscript_assembler.py` — Draft assembly, section management, review workflow.
- `backend/app/services/ai_transformer.py` — Two-pass AI content transformation: Pass 1 = structural labeling (H1/H2/H3/BODY/LIST/TABLE + needs_rewrite flag) in word-limited batches with table-row grouping so tables are never split across batches; Pass 2 = academic rewriting of flagged non-TABLE blocks with context-aware prompts and entity-preserving integrity check (100% numbers, 100% units, 75% medical terms); TABLE blocks always bypass Pass 2 and receive cell-by-cell verification after Pass 1.
- `backend/app/core/ai_pool.py` — Multi-provider API key pool: round-robin Gemini + Groq keys, exponential backoff on 429s, thread-safe.

## Key Configuration

- Frontend runs on port **5000** (required for Replit webview)
- Backend runs on port **8000** (localhost only)
- Vite proxies all `/api` requests to `http://localhost:8000`
- `VITE_DISABLE_AUTH=true` bypasses Firebase auth in dev
- `DATABASE_URL` environment variable points to PostgreSQL

## Workflows

- **Start application**: `npm run dev` (frontend, port 5000)
- **Backend API**: `bash backend/start.sh` (FastAPI, port 8000)

## Environment Variables

- `GEMINI_API_KEY` — Primary Gemini API key for AI transformation (required)
- `GEMINI_API_KEY_1`, `GEMINI_API_KEY_2`, ... — Additional Gemini keys for key-pool rotation
- `GROQ_API_KEY_1`, `GROQ_API_KEY_2`, ... — Groq keys as secondary AI provider
- `DATABASE_URL` — PostgreSQL connection string (auto-set by Replit)
- `VITE_DISABLE_AUTH` — Set to `true` to bypass Firebase login
- `VITE_API_BASE_URL` — Override API base URL (defaults to empty = relative, proxied)

## AI Transformation Key Features

- **Two-pass design**: Pass 1 labels every block (H1/H2/H3/BODY/LIST/TABLE) and flags ~25-35% for rewriting; Pass 2 rewrites only flagged blocks using surrounding context
- **Content preservation**: Entity-preserving integrity check after each Pass 2 rewrite — requires 100% of numeric values, 100% of measurement units (mg/kcal/mmol/L etc.), and 100% of capitalised medical/technical terms to be present in the rewritten text; any missing entity triggers fallback to original text
- **Tables protected**: TABLE blocks bypass Pass 2 entirely; after Pass 1 each TABLE block receives cell-by-cell verification and any missing cell triggers reversion to original paragraph text
- **Graceful degradation**: If no AI keys configured, ai_transform stage is skipped silently and pipeline continues with cleaned text
- **Artifacts saved**: Transformed text (human-readable with heading markers) and transformed JSON (machine-readable blocks) saved as artifacts per chunk

## DOCX Export — Professional Styling

`backend/app/services/docx_exporter.py` produces publication-quality DOCX files:

- **Named Word styles**: Heading 1–3, Body Text, Caption, Front Matter Heading, Chapter Opener
- **Typography**: Times New Roman 12pt body (justified + first-line indent 1.27cm), Arial headings, 1.5 line spacing
- **Page layout**: A4 (21×29.7cm), 2.54cm margins all sides, header (book title top-right), footer (page number bottom-center)
- **Front matter**: Title page (title, subtitle, author, edition, institution, ISBN, year), Copyright page, optional Dedication / Preface / Acknowledgements / Disclaimer
- **TOC**: Word built-in TOC field (`TOC \o "1-N"`) — updates automatically when opened in Word
- **Chapter headings**: "Chapter N: Title" with page-break-before; chapter numbering is automatic from section order
- **Tables**: Table Grid style, bold dark-shaded header row, white text, per-cell borders, auto-fit columns
- **Back matter**: References and Index placeholders always appended

### Export Profile fields (ExportProfile model / `export_profiles` table)
New fields added in Task #2: `edition`, `isbn`, `copyright_year` (DB migration applied)
All fields exposed in `/api/v1/documents/{id}/export-profile` GET/PUT endpoints.
PublishingTools UI (`/publishing/:id`) exposes all fields including Edition, ISBN, Copyright Year.

## Processing Note

The backend uses ThreadPoolExecutor (not Celery/Redis) for async processing. All pipeline stages (including AI transformation) run within the thread pool and complete synchronously before control returns.
