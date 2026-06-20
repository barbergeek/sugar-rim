#!/usr/bin/env bash
set -e

VENV=".venv"

if [ ! -d "$VENV" ]; then
  echo "Creating virtual environment…"
  python3 -m venv "$VENV"
fi

source "$VENV/bin/activate"
pip install -q -r requirements.txt

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "Created .env from .env.example — open Settings in the app to configure."
fi

# Local dev is plain HTTP, so allow the session cookie without the Secure flag
# (production serves HTTPS via Cloudflare and keeps Secure on by default).
export SESSION_COOKIE_SECURE="${SESSION_COOKIE_SECURE:-0}"

exec python app.py
