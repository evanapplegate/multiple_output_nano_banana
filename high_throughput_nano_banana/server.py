from __future__ import annotations
import os
import base64
import mimetypes
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, request, jsonify, render_template, send_file
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

app = Flask(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DEFAULT_MODEL = "gemini-3-pro-image-preview"
GEMINI_VALID_MODELS = {"gemini-3-pro-image-preview", "gemini-3.1-flash-image-preview", "gemini-2.5-flash-image"}
OPENAI_VALID_MODELS = {"gpt-image-2.5-flare", "gpt-image-2.5-sunburst", "gpt-image-2", "gpt-image-1", "gpt-image-1-mini"}
API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
OPENAI_GEN_URL = "https://api.openai.com/v1/images/generations"
OPENAI_EDIT_URL = "https://api.openai.com/v1/images/edits"
VALID_RESOLUTIONS = {"1K", "2K", "4K"}
VALID_ASPECT_RATIOS = {"1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"}
VALID_OPENAI_SIZES = {
    "auto", "1024x1024", "1024x1536", "1536x1024",
    # gpt-image-2 and 2.5 only
    "1440x480", "480x1440",
    "3072x1024", "1024x3072",
    "3840x1280", "1280x3840",
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def call_gemini(prompt: str, resolution: str, aspect_ratio: str, attachments: list, model: str = DEFAULT_MODEL) -> str | None:
    parts = [{"text": prompt}]
    for att in attachments:
        parts.append({"inlineData": {"mimeType": att["mimeType"], "data": att["data"]}})
    image_config = {"imageSize": resolution}
    if aspect_ratio:
        image_config["aspectRatio"] = aspect_ratio
    try:
        resp = requests.post(
            API_URL_TEMPLATE.format(model),
            headers={
                "x-goog-api-key": GEMINI_API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "contents": [{"parts": parts}],
                "generationConfig": {
                    "responseModalities": ["TEXT", "IMAGE"],
                    "imageConfig": image_config,
                },
            },
            timeout=120,
        )
        print(f"[Gemini] {model} -> {resp.status_code}", flush=True)
        if resp.status_code != 200:
            body = resp.text[:500]
            print(f"[Gemini] ERROR body: {body}", flush=True)
            return None
        data = resp.json()
        parts = data["candidates"][0]["content"]["parts"]
        for part in parts:
            if "inlineData" in part and part["inlineData"]["mimeType"].startswith("image/"):
                mime = part["inlineData"]["mimeType"]
                b64 = part["inlineData"]["data"]
                print(f"[Gemini] OK, got {mime} image", flush=True)
                return f"data:{mime};base64,{b64}"
        print(f"[Gemini] No image in response. Parts keys: {[list(p.keys()) for p in parts]}", flush=True)
        return None
    except Exception as e:
        print(f"[Gemini] EXCEPTION: {e}", flush=True)
        return None


def aspect_to_openai_size(aspect_ratio: str) -> str:
    if aspect_ratio in {"2:3", "3:4", "9:16", "4:5"}:
        return "1024x1536"
    if aspect_ratio in {"3:2", "4:3", "16:9", "21:9", "5:4"}:
        return "1536x1024"
    return "1024x1024"


def call_openai(prompt: str, size: str, aspect_ratio: str, attachments: list, model: str) -> str | None:
    if size == "auto" or not size:
        size = aspect_to_openai_size(aspect_ratio)
    try:
        if attachments:
            files = []
            for i, att in enumerate(attachments):
                ext = (att["mimeType"].split("/")[-1] or "png").split("+")[0]
                files.append(("image[]", (f"img{i}.{ext}", base64.b64decode(att["data"]), att["mimeType"])))
            resp = requests.post(
                OPENAI_EDIT_URL,
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                files=files,
                data={"prompt": prompt, "model": model, "n": "1", "size": size},
                timeout=300,
            )
        else:
            resp = requests.post(
                OPENAI_GEN_URL,
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
                json={"prompt": prompt, "model": model, "n": 1, "size": size},
                timeout=300,
            )
        print(f"[OpenAI] {model} -> {resp.status_code}", flush=True)
        if resp.status_code != 200:
            print(f"[OpenAI] ERROR body: {resp.text[:500]}", flush=True)
            return None
        return f"data:image/png;base64,{resp.json()['data'][0]['b64_json']}"
    except Exception as e:
        print(f"[OpenAI] EXCEPTION: {e}", flush=True)
        return None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/list-styles")
def list_styles():
    dir_path = request.args.get("dir", "").strip()
    if not dir_path:
        return jsonify({"error": "dir parameter required"}), 400
    if not os.path.isabs(dir_path):
        dir_path = os.path.join(os.path.dirname(__file__), dir_path)
    dir_path = os.path.realpath(dir_path)
    if not os.path.isdir(dir_path):
        return jsonify({"error": f"not a directory: {dir_path}"}), 400
    images = []
    for fname in sorted(os.listdir(dir_path)):
        ext = os.path.splitext(fname)[1].lower()
        if ext in IMAGE_EXTENSIONS:
            images.append({"filename": fname, "path": os.path.join(dir_path, fname)})
    return jsonify({"images": images, "dir": dir_path})


@app.route("/style-thumb")
def style_thumb():
    path = request.args.get("path", "").strip()
    if not path or not os.path.isfile(path):
        return "not found", 404
    ext = os.path.splitext(path)[1].lower()
    if ext not in IMAGE_EXTENSIONS:
        return "not an image", 400
    return send_file(path)


@app.route("/generate", methods=["POST"])
def generate():
    body = request.get_json(silent=True) or {}
    prompt = (body.get("prompt") or "").strip()
    model = (body.get("model") or DEFAULT_MODEL).strip()
    resolution = (body.get("resolution") or "1K").upper()
    openai_size = (body.get("openaiSize") or "auto").strip()
    aspect_ratio = (body.get("aspectRatio") or "").strip()
    style_path = (body.get("stylePath") or "").strip()

    if not prompt:
        return jsonify({"error": "prompt is required"}), 400
    if model not in GEMINI_VALID_MODELS | OPENAI_VALID_MODELS:
        return jsonify({"error": f"model must be one of {sorted(GEMINI_VALID_MODELS | OPENAI_VALID_MODELS)}"}), 400
    is_openai = model in OPENAI_VALID_MODELS
    if is_openai and not OPENAI_API_KEY:
        return jsonify({"error": "OPENAI_API_KEY not set in .env"}), 500
    if not is_openai and not GEMINI_API_KEY:
        return jsonify({"error": "GEMINI_API_KEY not set in .env"}), 500
    if resolution not in VALID_RESOLUTIONS:
        return jsonify({"error": f"resolution must be one of {VALID_RESOLUTIONS}"}), 400
    if openai_size not in VALID_OPENAI_SIZES:
        return jsonify({"error": f"openaiSize must be one of {sorted(VALID_OPENAI_SIZES)}"}), 400
    if aspect_ratio and aspect_ratio not in VALID_ASPECT_RATIOS:
        return jsonify({"error": f"aspectRatio must be one of {sorted(VALID_ASPECT_RATIOS)}"}), 400

    shots = body.get("shots", 3)
    if not isinstance(shots, int) or shots < 1 or shots > 9:
        return jsonify({"error": "shots must be 1-9"}), 400

    attachments = []
    style_data = body.get("styleData")  # {mimeType, data} from uploaded file
    if style_data and style_data.get("data"):
        attachments.append({"mimeType": style_data["mimeType"], "data": style_data["data"]})
    elif style_path:
        if not os.path.isfile(style_path):
            return jsonify({"error": f"style image not found: {style_path}"}), 400
        with open(style_path, "rb") as f:
            img_data = base64.b64encode(f.read()).decode("utf-8")
        mime = mimetypes.guess_type(style_path)[0] or "image/png"
        attachments.append({"mimeType": mime, "data": img_data})

    if is_openai:
        call = lambda: call_openai(prompt, openai_size, aspect_ratio, attachments, model)
    else:
        call = lambda: call_gemini(prompt, resolution, aspect_ratio, attachments, model)

    images = [None] * shots
    # OpenAI chokes on parallel bursts: one shot at a time
    with ThreadPoolExecutor(max_workers=1 if is_openai else shots) as executor:
        futures = {executor.submit(call): i for i in range(shots)}
        for future in as_completed(futures):
            idx = futures[future]
            images[idx] = future.result()

    return jsonify({"images": images})


if __name__ == "__main__":
    app.run(debug=True, port=5001)
