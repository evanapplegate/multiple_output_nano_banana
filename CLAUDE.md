# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Guidance

Max concision. Reply like a curt continental open-source maintainer.

## Setup

Copy `.env.example` to `.env` and set `GEMINI_API_KEY`:
```
cp .env.example .env
# edit .env and add your key
```

Install dependencies:
```
pip install -r requirements.txt
```

## Running

```
python server.py
```

Runs on `http://localhost:5050` with Flask debug mode enabled.

## Architecture

A minimal Flask web app for AI image generation using Google's Gemini API.

- **`server.py`** — Flask backend with two routes:
  - `GET /` — serves `templates/index.html`
  - `POST /generate` — accepts `{prompt, resolution, attachments}` JSON; fires 3 parallel Gemini calls via `ThreadPoolExecutor` and returns `{images: [base64DataURL|null, ...]}` (one per shot)
- **`templates/index.html`** — single-file vanilla JS frontend; no build step. Handles prompt input, image attachment (drag-and-drop or file picker), resolution selection (1K/2K/4K), and renders the 3-shot results grid with per-image save buttons.

Gemini models (default `gemini-nano-banana-2.1`, also `gemini-3-pro-image`, `gemini-3.1-flash-image`, `gemini-3.1-flash-lite-image`, `gemini-2.5-flash-image`) are called via the `generativelanguage.googleapis.com/v1beta` REST API. Attachments are sent as `inlineData` parts alongside the text prompt. Each of the 3 generation calls is independent (no shared state); `null` is returned for any call that fails.
