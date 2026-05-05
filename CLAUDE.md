# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

sugar-rim is an alternate web interface for [Bar Assistant](https://github.com/bar-assistant/bar-assistant), a self-hosted cocktail recipe manager.

## Architecture

- `app.py` — Flask backend; proxies all Bar Assistant API calls (API token never sent to browser)
- `templates/index.html` — Single-page app shell
- `static/css/style.css` — Full UI styles (dark theme, full-viewport layout for Raspberry Pi)
- `static/js/app.js` — Frontend SPA logic (vanilla JS, no build step)
- `.env` — Runtime secrets (`BA_API_URL`, `BA_API_TOKEN`); gitignored
- `.env.example` — Template to copy for new installs

## Language & Tooling

Python + Flask. Dependencies in `requirements.txt`.

## Commands

```bash
# First run (sets up venv, installs deps, copies .env.example → .env)
./run.sh

# Manual
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py          # runs on http://localhost:5000

# Lint
ruff check .
ruff format .
```

## Configuration

API URL and token are set via the **Settings** tab in the UI, which writes them to `.env`. The token is stored only server-side and never sent to the browser. To bootstrap without the UI, edit `.env` directly.
