# =============================================================================
# Manus-AI single-image build:
#   Stage 1: build the React/Vite frontend
#   Stage 2: install Python deps + copy backend + frontend dist into one image
# Result: a single container that serves the API at /api/* and the SPA at /.
# =============================================================================

# ---- Stage 1: frontend ------------------------------------------------------
FROM node:20-bookworm-slim AS frontend
WORKDIR /build

# Install deps first (better layer caching when only source changes)
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# Copy what's needed to build the bundle
COPY tsconfig.json vite.config.ts index.html ./
COPY public ./public
COPY src ./src
COPY .env.example ./.env

# Force Vite to use relative API base; in production the backend serves the
# bundle from the same origin, so /api/... lands on FastAPI directly.
ENV VITE_API_BASE_URL=""
RUN npm run build


# ---- Stage 2: backend + bundled frontend -----------------------------------
FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Minimal native deps PyMuPDF / fonts / typst need at runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        libgl1 \
        libglib2.0-0 \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install -r backend/requirements.txt gunicorn

# Backend source
COPY backend/app ./backend/app
COPY backend/alembic.ini ./backend/alembic.ini
COPY backend/alembic ./backend/alembic

# Frontend bundle from stage 1
COPY --from=frontend /build/dist ./frontend

# Default storage path inside the container; mounted as a volume in production.
ENV STORAGE_ROOT=/var/data/storage \
    FRONTEND_DIST_DIR=/app/frontend \
    PYTHONPATH=/app/backend

# Make sure the storage path exists for the very first run before the volume
# is mounted (won't conflict with a real volume mount).
RUN mkdir -p /var/data/storage

EXPOSE 8000

# Gunicorn with one uvicorn worker is plenty for 2 users and avoids the
# memory cost of multiple workers. --timeout 600 lets PyMuPDF render large
# PDFs without being killed.
CMD ["gunicorn", \
     "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "1", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "600", \
     "--access-logfile", "-"]
