#!/usr/bin/env bash
# TASARIM.md §4: docker compose down -v && up -d && alembic upgrade head && seed_db.py
# Postgres verisini SIFIRDAN kurar (volume dahil siler) -- geri dönüşü yoktur.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
INFRA_DIR="$(dirname "$BACKEND_DIR")/infra"

echo "== docker compose down -v (infra/) =="
(cd "$INFRA_DIR" && docker compose down -v)

echo "== docker compose up -d (infra/) =="
(cd "$INFRA_DIR" && docker compose up -d)

echo "== postgres healthy bekleniyor =="
until docker compose -f "$INFRA_DIR/docker-compose.yml" ps postgres --format json | grep -q '"Health":"healthy"'; do
  sleep 1
done

echo "== alembic upgrade head (backend/) =="
(cd "$BACKEND_DIR" && .venv/bin/alembic upgrade head)

echo "== seed_db.py (backend/) =="
(cd "$BACKEND_DIR" && .venv/bin/python -m scripts.seed_db "$@")

echo "== tamamlandı =="
