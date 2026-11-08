# Image Gen

Minimal Flask app for multi-shot image generation with Google Gemini (Nano Banana) and OpenAI GPT Image. Run one provider or both side by side and compare.

![Python](https://img.shields.io/badge/python-3.10+-blue) ![Flask](https://img.shields.io/badge/flask-3.0+-green)

## Features

- Gemini and OpenAI in the same run, each in its own results grid
- Gemini models: `gemini-nano-banana-2.1` (default), `gemini-3-pro-image`, `gemini-3.1-flash-image`, `gemini-3.1-flash-lite-image` (1K only), `gemini-2.5-flash-image`
- OpenAI models: `gpt-image-2.5-flare`, `gpt-image-2.5-sunburst`, `gpt-image-2`, `gpt-image-1`, `gpt-image-1-mini`
- 1-9 shots per prompt. Shots run one at a time per provider, providers run in parallel, results stream in as each lands
- Gemini resolution 1K / 2K / 4K; OpenAI sizes from 1024x1024 up to 3840x1280 (3:1 sizes need `gpt-image-2` or newer); shared aspect ratio picker
- Image attachments: up to 14 files, 7MB each, 20MB total; drag-and-drop or file picker; optional auto-resize of oversized images. With attachments, OpenAI uses the edits endpoint
- Stop button, prompt history, last 5 runs kept in the browser (IndexedDB), save one or save all, Cmd/Ctrl+Enter to generate, light/dark theme
- Vanilla JS frontend, no build step

## Setup

### 1. API keys

You only need the key for the provider(s) you use.

- Gemini: [Google AI Studio](https://aistudio.google.com/apikey)
- OpenAI: [platform.openai.com/api-keys](https://platform.openai.com/api-keys)

### 2. Install

```bash
git clone https://github.com/evanapplegate/multiple_output_nano_banana.git
cd multiple_output_nano_banana
cp .env.example .env
# edit .env: set GEMINI_API_KEY and/or OPENAI_API_KEY
pip install -r requirements.txt
```

### 3. Run

```bash
python3 server.py
```

Open [http://localhost:5050](http://localhost:5050).

**macOS:** double-click `run.command` to start the server and open the browser.

## High-throughput variant

`high_throughput_nano_banana/` batches prompts against style references:

- Multiple prompts, each run against every selected style image
- Style images loaded from a directory (default `styles/`, 7 bundled) or uploaded
- Gemini and OpenAI pickers as above; Gemini models here are `gemini-3-pro-image-preview` (default), `gemini-3.1-flash-image-preview`, `gemini-2.5-flash-image`
- One request per prompt x style x model; Gemini shots run in parallel, OpenAI shots serially
- Port **5001**, reads `.env` from the repo root

```bash
cd high_throughput_nano_banana
python3 server.py
```

Open [http://localhost:5001](http://localhost:5001), or double-click `high_throughput_nano_banana/run.command`.

## API

`POST /generate` (main app) takes JSON:

| Field | Notes |
|---|---|
| `prompt` | required |
| `geminiModel`, `openaiModel` | at least one; empty string skips that provider |
| `resolution` | Gemini: `1K` / `2K` / `4K` |
| `openaiSize` | `auto` or `WxH` |
| `aspectRatio` | e.g. `16:9`; empty for auto |
| `shots` | 1-9 |
| `attachments` | `[{mimeType, data, name}]`, base64 data |

Response is NDJSON: one line per shot, `{provider, index, image, error, note}`, then `{done, ok, total}`.

## Project structure

```
server.py                    Flask backend: validates, calls Gemini/OpenAI, streams NDJSON
templates/index.html         Single-file frontend
.env.example                 GEMINI_API_KEY, OPENAI_API_KEY
run.command                  macOS launcher (port 5050)
high_throughput_nano_banana/
  server.py                  Batch backend (port 5001), style listing and thumbnails
  templates/index.html       Batch frontend
  styles/                    Bundled style reference images
  run.command                macOS launcher (port 5001)
```

Both servers run with Flask debug mode on and listen on localhost only. Don't expose them publicly.
