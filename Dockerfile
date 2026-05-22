# =============================================================================
# Hugging Face Spaces single-image build.
#
# Differences from the Oracle Dockerfile:
#   - Listens on port 7860 (HF default)
#   - Storage path defaults to /data (HF persistent mount)
#   - Caddy is not needed - HF provides HTTPS automatically
#
# Stage 1: build the React/Vite frontend
# Stage 2: install Python deps + copy backend + frontend dist into one image
# =============================================================================

# ---- Stage 1: frontend ------------------------------------------------------
FROM node:20-bookworm-slim AS frontend
WORKDIR /build

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY tsconfig.json vite.config.ts index.html ./
COPY public ./public
COPY src ./src
COPY .env.example ./.env

# Same-origin in production: the backend serves the bundle, so /api/... lands
# directly on FastAPI with no CORS or proxy config required.
ENV VITE_API_BASE_URL=""
RUN npm run build


# ---- Stage 2: backend + bundled frontend -----------------------------------
FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Native deps PyMuPDF / fonts need at runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        libgl1 \
        libglib2.0-0 \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install -r backend/requirements.txt

# Backend source
COPY backend/app ./backend/app
COPY backend/alembic.ini ./backend/alembic.ini
COPY backend/alembic ./backend/alembic

# Frontend bundle from stage 1
COPY --from=frontend /build/dist ./frontend

# HF Spaces conventions:
#   - listen on $PORT (defaults to 7860)
#   - persistent storage (when toggled on) is mounted at /data
ENV STORAGE_ROOT=/data \
    FRONTEND_DIST_DIR=/app/frontend \
    PYTHONPATH=/app/backend \
    PORT=7860

# HF can run the container with a non-root user the first time; pre-create
# /data and make /app writable so STORAGE_ROOT and SQLite work either way.
RUN mkdir -p /data && chmod -R 777 /data /app

EXPOSE 7860

# One worker is plenty for 2 users and avoids extra memory cost. --timeout 600
# lets PyMuPDF render large PDFs without being killed.
CMD ["sh", "-c", "gunicorn app.main:app --worker-class uvicorn.workers.UvicornWorker --workers 1 --bind 0.0.0.0:${PORT:-7860} --timeout 600 --access-logfile -"]
