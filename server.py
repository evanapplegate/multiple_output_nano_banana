import os
import json
import base64
import threading
import queue
import requests
from flask import Flask, request, jsonify, render_template, Response
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

GEMINI_VALID_MODELS = {"gemini-nano-banana-2.1", "gemini-3-pro-image", "gemini-3.1-flash-image", "gemini-3.1-flash-lite-image", "gemini-2.5-flash-image"}
OPENAI_VALID_MODELS = {"gpt-image-2.5-flare", "gpt-image-2.5-sunburst", "gpt-image-2","gpt-image-1", "gpt-image-1-mini"}

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
OPENAI_GEN_URL = "https://api.openai.com/v1/images/generations"
OPENAI_EDIT_URL = "https://api.openai.com/v1/images/edits"

VALID_RESOLUTIONS = {"1K", "2K", "4K"}
# Per Google docs — extreme banners (1:4, 8:1, …) are not supported by any of these models.
VALID_ASPECT_RATIOS = {"1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"}
VALID_OPENAI_SIZES = {
    "auto", "1024x1024", "1024x1536", "1536x1024",
    # gpt-image-2 and 2.5 only: custom sizes at max 3:1 aspect (divisible by 16, within pixel caps)
    "1440x480", "480x1440",
    "3072x1024", "1024x3072",
    "3840x1280", "1280x3840",
}

MAX_ATTACHMENTS = 14
MAX_ATTACHMENT_MB = 7
MAX_TOTAL_MB = 20
ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp", "image/gif", "image/heic", "image/heif"}


def validate_attachments(attachments):
    """Normalize in place; return list of human-readable problems (empty = clean)."""
    problems = []
    if not isinstance(attachments, list):
        return ["attachments must be a list"]
    if len(attachments) > MAX_ATTACHMENTS:
        problems.append(f"too many attachments: {len(attachments)} (max {MAX_ATTACHMENTS})")
    total = 0
    for i, att in enumerate(attachments):
        name = (att.get("name") or f"attachment {i + 1}") if isinstance(att, dict) else f"attachment {i + 1}"
        if not isinstance(att, dict) or not att.get("data"):
            problems.append(f"{name}: missing data")
            continue
        data = att["data"]
        if data.startswith("data:"):
            att["data"] = data = data.split(",", 1)[-1]
        mime = att.get("mimeType") or ""
        if mime not in ALLOWED_MIME:
            problems.append(f"{name}: unsupported type '{mime}' (use {', '.join(sorted(m.split('/')[1] for m in ALLOWED_MIME))})")
        try:
            size = len(base64.b64decode(data, validate=True))
        except Exception:
            problems.append(f"{name}: corrupt base64 data")
            continue
        total += size
        if size > MAX_ATTACHMENT_MB * 1024 * 1024:
            problems.append(f"{name}: {size / 1048576:.1f}MB exceeds {MAX_ATTACHMENT_MB}MB per-file limit")
    if total > MAX_TOTAL_MB * 1024 * 1024:
        problems.append(f"attachments total {total / 1048576:.1f}MB exceeds {MAX_TOTAL_MB}MB limit")
    return problems


def _http_error(resp, exc):
    """Extract a human-readable reason from a failed API response."""
    try:
        body = resp.json()
        err = body.get("error", body)
        if isinstance(err, dict):
            return err.get("message") or err.get("code") or str(err)
        return str(err)
    except Exception:
        return (resp.text or str(exc))[:300]


def log(tag, msg):
    print(f"[{tag}] {msg}", flush=True)


def call_gemini(prompt, resolution, aspect_ratio, attachments, model):
    parts = [{"text": prompt}]
    for att in attachments:
        parts.append({"inlineData": {"mimeType": att["mimeType"], "data": att["data"]}})
    image_config = {"imageSize": resolution}
    if aspect_ratio:
        image_config["aspectRatio"] = aspect_ratio
    resp = None
    try:
        resp = requests.post(
            GEMINI_API_URL.format(model),
            headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
            json={
                "contents": [{"parts": parts}],
                "generationConfig": {"responseModalities": ["TEXT", "IMAGE"], "imageConfig": image_config},
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()

        feedback = data.get("promptFeedback") or {}
        if feedback.get("blockReason"):
            return {"image": None, "error": f"prompt blocked: {feedback['blockReason']}", "note": None}

        candidates = data.get("candidates") or []
        if not candidates:
            return {"image": None, "error": "no candidates in response", "note": None}
        cand = candidates[0]

        image = None
        texts = []
        for part in (cand.get("content") or {}).get("parts", []):
            inline = part.get("inlineData")
            if inline and inline.get("mimeType", "").startswith("image/") and image is None:
                image = f"data:{inline['mimeType']};base64,{inline['data']}"
            elif part.get("text", "").strip():
                texts.append(part["text"].strip())

        finish = cand.get("finishReason")
        finish_note = f"finishReason: {finish}" if finish and finish != "STOP" else None

        if image:
            # Newer models caption every image ("Here is a photograph of...");
            # that text is only worth surfacing when no image came back.
            if texts:
                log("gemini", f"{model} caption: {' '.join(texts)[:200]}")
            log("gemini", f"{model} ok" + (f" with warning: {finish_note}" if finish_note else ""))
            return {"image": image, "error": None, "note": finish_note}
        reason = " · ".join(texts + ([finish_note] if finish_note else [])) or "no image in response (text-only or blocked)"
        return {"image": None, "error": reason, "note": None}
    except Exception as exc:
        reason = _http_error(resp, exc) if resp is not None else str(exc)
        log("gemini", f"{model} failed: {reason}")
        return {"image": None, "error": reason, "note": None}


def aspect_to_openai_size(aspect_ratio):
    portrait = {"2:3", "3:4", "9:16", "4:5"}
    landscape = {"3:2", "4:3", "16:9", "21:9", "5:4"}
    if aspect_ratio in portrait:
        return "1024x1536"
    if aspect_ratio in landscape:
        return "1536x1024"
    return "1024x1024"


def call_openai(prompt, size, aspect_ratio, attachments, model):
    if size == "auto" or not size:
        size = aspect_to_openai_size(aspect_ratio)
    resp = None
    try:
        if attachments:
            files = []
            for i, att in enumerate(attachments):
                ext = (att["mimeType"].split("/")[-1] or "png").split("+")[0]
                img_bytes = base64.b64decode(att["data"])
                files.append(("image[]", (f"img{i}.{ext}", img_bytes, att["mimeType"])))
            data = {"prompt": prompt, "model": model, "n": "1", "size": size}
            resp = requests.post(
                OPENAI_EDIT_URL,
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                files=files,
                data=data,
                timeout=300,
            )
        else:
            resp = requests.post(
                OPENAI_GEN_URL,
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
                json={"prompt": prompt, "model": model, "n": 1, "size": size},
                timeout=300,
            )
        resp.raise_for_status()
        b64 = resp.json()["data"][0]["b64_json"]
        log("openai", f"{model} ok")
        return {"image": f"data:image/png;base64,{b64}", "error": None, "note": None}
    except Exception as exc:
        reason = _http_error(resp, exc) if resp is not None else str(exc)
        log("openai", f"{model} failed: {reason}")
        return {"image": None, "error": reason, "note": None}


@app.errorhandler(413)
def too_large(_):
    return jsonify({"error": f"request too large (max {app.config['MAX_CONTENT_LENGTH'] // 1048576}MB) — shrink your attachments"}), 413


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate():
    body = request.get_json(silent=True) or {}
    prompt = (body.get("prompt") or "").strip()
    gemini_model = (body.get("geminiModel") or "").strip()
    openai_model = (body.get("openaiModel") or "").strip()
    resolution = (body.get("resolution") or "1K").upper()
    openai_size = (body.get("openaiSize") or "auto").strip()
    aspect_ratio = (body.get("aspectRatio") or "").strip()
    attachments = body.get("attachments") or []

    if not prompt:
        return jsonify({"error": "prompt is required"}), 400
    if not gemini_model and not openai_model:
        return jsonify({"error": "select at least one model"}), 400
    if gemini_model and gemini_model not in GEMINI_VALID_MODELS:
        return jsonify({"error": f"geminiModel must be one of {sorted(GEMINI_VALID_MODELS)} or empty"}), 400
    if openai_model and openai_model not in OPENAI_VALID_MODELS:
        return jsonify({"error": f"openaiModel must be one of {sorted(OPENAI_VALID_MODELS)} or empty"}), 400
    if resolution not in VALID_RESOLUTIONS:
        return jsonify({"error": f"resolution must be one of {VALID_RESOLUTIONS}"}), 400
    if openai_size not in VALID_OPENAI_SIZES:
        return jsonify({"error": f"openaiSize must be one of {sorted(VALID_OPENAI_SIZES)}"}), 400
    if aspect_ratio and aspect_ratio not in VALID_ASPECT_RATIOS:
        return jsonify({"error": f"aspectRatio must be one of {sorted(VALID_ASPECT_RATIOS)}"}), 400

    problems = validate_attachments(attachments)
    if problems:
        log("generate", f"rejected: {'; '.join(problems)}")
        return jsonify({"error": "bad attachments", "problems": problems}), 400

    shots = body.get("shots", 3)
    if not isinstance(shots, int) or shots < 1 or shots > 9:
        return jsonify({"error": "shots must be 1–9"}), 400

    if gemini_model and not GEMINI_API_KEY:
        return jsonify({"error": "GEMINI_API_KEY not set in .env"}), 500
    if openai_model and not OPENAI_API_KEY:
        return jsonify({"error": "OPENAI_API_KEY not set in .env"}), 500

    att_bytes = sum(len(a["data"]) * 3 // 4 for a in attachments)
    log("generate", f"start: shots={shots} gemini={gemini_model or '-'} openai={openai_model or '-'} "
                    f"res={resolution} ar={aspect_ratio or 'auto'} attachments={len(attachments)} ({att_bytes / 1048576:.1f}MB) "
                    f"prompt={prompt[:80]!r}")

    # One shot at a time per provider (the APIs choke on parallel bursts).
    # Gemini and OpenAI queues run side by side; each result streams back
    # as its own line the moment it lands.
    def event_stream():
        q = queue.Queue()
        cancel = threading.Event()

        def run_serial(provider, make_call):
            for i in range(shots):
                if cancel.is_set():
                    log(provider, f"stopped — skipping shots {i + 1}–{shots}")
                    return
                log(provider, f"shot {i + 1}/{shots} starting")
                q.put({"provider": provider, "index": i, **make_call()})

        workers = []
        if gemini_model:
            workers.append(threading.Thread(
                target=run_serial,
                args=("gemini", lambda: call_gemini(prompt, resolution, aspect_ratio, attachments, gemini_model)),
                daemon=True))
        if openai_model:
            workers.append(threading.Thread(
                target=run_serial,
                args=("openai", lambda: call_openai(prompt, openai_size, aspect_ratio, attachments, openai_model)),
                daemon=True))
        for w in workers:
            w.start()

        total = shots * len(workers)
        ok = 0
        try:
            for _ in range(total):
                evt = q.get()
                if evt.get("image"):
                    ok += 1
                yield json.dumps(evt) + "\n"
            yield json.dumps({"done": True, "ok": ok, "total": total}) + "\n"
            log("generate", f"done: {ok}/{total} images ok")
        finally:
            # Client gone (stop button / closed tab) or stream done —
            # tell workers to quit before their next shot.
            cancel.set()

    return Response(event_stream(), mimetype="application/x-ndjson")


if __name__ == "__main__":
    app.run(debug=True, port=5050)
