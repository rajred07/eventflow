#!/bin/bash

# Exit on error
set -e

echo "Starting Celery Worker..."
celery -A app.worker.celery_app worker --loglevel=info --concurrency=1 &

echo "Starting Celery Beat..."
celery -A app.worker.celery_app beat --loglevel=info &

echo "Running Alembic Migrations..."
alembic upgrade head

echo "Starting FastAPI Server..."
uvicorn app.main:app --host 0.0.0.0 --port 10000 --workers 1
