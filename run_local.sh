#!/usr/bin/env bash
# Local dev runner. Creates a venv, installs deps, starts the app on :8000.
set -e
python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt
[ -f .env ] || cp .env.example .env
[ -f org_config.json ] || cp org_config.example.json org_config.json
echo "Starting on http://localhost:8000  (mock mode unless ANTHROPIC_API_KEY is set)"
uvicorn backend.main:app --reload --port 8000
