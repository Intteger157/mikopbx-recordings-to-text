#!/bin/sh
set -e

echo "==> Starting Celery worker (transcription + sync)..."
exec celery -A app.tasks.celery_app worker --loglevel=info --concurrency=1
