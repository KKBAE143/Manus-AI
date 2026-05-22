# Manuscript Processing App

Large-PDF manuscript processing web app with a React frontend and FastAPI/Celery backend.

## What It Does

- Upload very large PDFs as projects
- Inspect page count and metadata
- Split processing into chunks
- Run deterministic extraction and cleanup
- Generate cleaned DOCX parts
- Track chunks, logs, artifacts, and manifests
- Validate merge readiness
- Merge parts into a final DOCX

## Architecture

- Frontend: Vite + React + TypeScript
- Backend API: FastAPI
- Background jobs: Celery
- Queue/result backend: Redis
- Database: SQLite by default, Postgres-ready via `DATABASE_URL`
- Storage: local filesystem under `backend/storage/projects`

## Local Development

### Prerequisites

- Node.js 18+
- Python 3.11+
- Docker Desktop

### 1. Frontend

```bash
cd C:\Users\kkbae\Downloads\zip
npm install
npm run dev
```

### 2. Backend dependencies

```bash
cd C:\Users\kkbae\Downloads\zip\backend
venv\Scripts\activate
python -m pip install -r requirements.txt
```

### 3. Redis

```bash
docker run -d --name manuscript-redis -p 6379:6379 redis:7-alpine
```

If the container already exists:

```bash
docker start manuscript-redis
```

### 4. Backend API

```bash
cd C:\Users\kkbae\Downloads\zip\backend
venv\Scripts\activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 5. Celery worker

```bash
cd C:\Users\kkbae\Downloads\zip\backend
venv\Scripts\activate
celery -A app.core.celery_app:celery_app worker --loglevel=info --pool=solo
```

## Useful URLs

- Frontend: `http://localhost:3000`
- Backend API: `http://localhost:8000`
- Backend health: `http://localhost:8000/api/health`
- API docs: `http://localhost:8000/docs`

## Environment Variables

Copy `backend/.env.example` to `backend/.env` and adjust as needed.

### SQLite (default)

```env
DATABASE_URL=sqlite:///./storage/manuscript_app.db
```

### Postgres example

```env
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/manuscript_app
```

## Alembic Migrations

### Generate a migration

```bash
cd C:\Users\kkbae\Downloads\zip\backend
venv\Scripts\activate
alembic revision --autogenerate -m "init schema"
```

### Apply migrations

```bash
cd C:\Users\kkbae\Downloads\zip\backend
venv\Scripts\activate
alembic upgrade head
```

## Production Notes

- Use Postgres instead of SQLite
- Run multiple Celery workers for throughput
- Put Redis behind managed infrastructure or a private network
- Persist `backend/storage/projects` on durable disk or object storage
- Serve frontend with a static host or reverse proxy
- Run FastAPI behind nginx, Caddy, or a cloud load balancer

## Recommended Production Processes

- `uvicorn` or `gunicorn` for API
- `celery worker` for chunk processing
- Redis service
- Postgres service
- persistent project storage volume

## Operational Notes

- Chunk fan-out is enabled
- Merge is blocked when validation fails
- Projects can be archived or deleted
- Individual or bulk chunk reruns are supported
- Preview/search exists for manifests, artifacts, and parts
