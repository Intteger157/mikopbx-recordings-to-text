# Call Recording Management & Transcription Service

Full-stack web service for MikoPBX call recording sync, RBAC-gated playback, and on-demand transcription with faster-whisper.

## Stack

- **Backend:** FastAPI, SQLAlchemy, Alembic, PostgreSQL, Celery, Redis, faster-whisper
- **Frontend:** React, Vite, Tailwind CSS, shadcn/ui-style components, Lucide icons
- **Integration:** MikoPBX REST API v3

## Quick Start

### Prerequisites

- Docker and Docker Compose

### Run

```bash
docker compose up --build
```

Services:

| Service | URL |
|---------|-----|
| Frontend | http://localhost:5173 |
| API | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |

Default superadmin credentials:

- **Username:** `admin`
- **Password:** `admin123`

Change these in production via environment variables:

```env
SUPERADMIN_USERNAME=
SUPERADMIN_EMAIL=
SUPERADMIN_PASSWORD=
JWT_SECRET=
```

## First-Run Workflow

1. Sign in as superadmin.
2. Open **PBX Settings** and enter your MikoPBX host URL and API key.
3. Click **Test connection**.
4. Choose a date range and click **Sync now** to import extensions and CDR recordings.
5. Open **Users** to create accounts and assign allowed extensions.
6. Browse **Call Records**, play audio, and click **Transcribe**.

## MikoPBX API Key Permissions

Grant at minimum:

- Call Records → Read
- Employees Management → Read (for extension/user mapping)

## Transcription Notes

- Celery worker uses faster-whisper `medium` model with CPU `int8` quantization.
- First transcription run downloads ~1.5 GB model weights (cached in Docker volume `whisper_models`).
- Supported audio formats: `.webm`, `.wav`, `.mp3` (via system ffmpeg).

## Development (without Docker)

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

Run Celery worker separately:

```bash
celery -A app.tasks.celery_app worker --loglevel=info
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Set `DATABASE_URL`, `REDIS_URL`, and `CORS_ORIGINS` for local services.

## RBAC

| Role | Access |
|------|--------|
| SUPERADMIN | Full access: PBX config, user management, all call records |
| MANAGER / USER | Call records where `src_num` or `dst_num` matches assigned extensions |

## API Overview

- `POST /api/auth/login`, `GET /api/auth/me`
- `GET /api/calls`, `GET /api/calls/{id}`, `GET /api/calls/{id}/audio`
- `POST /api/calls/{id}/transcribe`, `GET /api/calls/{id}/transcription`
- `GET/PUT /api/admin/pbx-config`, `POST /api/admin/pbx-config/test`, `POST /api/admin/pbx-config/sync`
- `GET /api/admin/extensions`
- `GET/POST/PUT/DELETE /api/users`

## Project Structure

```
backend/     FastAPI app, models, Celery tasks, Alembic migrations
frontend/    React SPA
docker-compose.yml
```
