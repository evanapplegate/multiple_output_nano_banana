# Gemini Image Generator

A minimal web app for AI image generation using Google's Gemini API. Fires multiple parallel generation calls and displays results in a grid.

![Python](https://img.shields.io/badge/python-3.10+-blue) ![Flask](https://img.shields.io/badge/flask-3.0+-green)

## Features

- Text-to-image generation via Gemini (`gemini-3-pro-image-preview` and others)
- Multiple shots per prompt (1–9 parallel generations)
- Configurable resolution (1K / 2K / 4K) and aspect ratio
- Image attachments as input (drag-and-drop or file picker)
- Per-image save buttons
- No build step — vanilla JS frontend

## How to Run

### 1. Get a Gemini API Key

Create one at [Google AI Studio](https://aistudio.google.com/apikey).

### 2. Install

```bash
git clone <this-repo>
cd img_gen
cp .env.example .env
# edit .env and paste your GEMINI_API_KEY
pip install -r requirements.txt
```

### 3. Start

```bash
python server.py
```

Open [http://localhost:5000](http://localhost:5000).

**macOS shortcut:** double-click `run.command` to launch the server and open the browser in one step.

## High-Throughput Version

`high_throughput_nano_banana/` is an extended variant with:

- **Style image gallery** — browse and pick from bundled style reference images (`styles/`)
- **Style upload** — or upload your own style reference
- Runs on port **5001** (shares the same `.env` from the parent dir)

```bash
cd high_throughput_nano_banana
pip install -r requirements.txt
python server.py
```

Open [http://localhost:5001](http://localhost:5001).

## Project Structure

```
server.py                          — Flask backend (API proxy to Gemini)
templates/index.html               — Single-file frontend
.env.example                       — Template for environment variables
run.command                        — macOS one-click launcher
high_throughput_nano_banana/
  server.py                        — Extended backend (style gallery + upload)
  templates/index.html             — Extended frontend
  styles/                          — Bundled style reference images
```
