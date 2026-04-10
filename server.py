import os
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DEFAULT_MODEL = "gemini-3-pro-image-preview"
VALID_MODELS = {"gemini-3-pro-image-preview", "gemini-3.1-flash-image-preview", "gemini-2.5-flash-image"}
API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
VALID_RESOLUTIONS = {"1K", "2K", "4K"}
VALID_ASPECT_RATIOS = {"1:1", "1:4", "1:8", "2:3", "3:2", "3:4", "4:1", "4:3", "4:5", "5:4", "8:1", "9:16", "16:9", "21:9"}


def call_gemini(prompt: str, resolution: str, aspect_ratio: str, attachments: list, model: str = DEFAULT_MODEL) -> str | None:
    """Make a single Gemini image generation call. Returns base64 data URL or None on failure."""
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
        resp.raise_for_status()
        data = resp.json()
        parts = data["candidates"][0]["content"]["parts"]
        for part in parts:
            if "inlineData" in part and part["inlineData"]["mimeType"].startswith("image/"):
                mime = part["inlineData"]["mimeType"]
                b64 = part["inlineData"]["data"]
                return f"data:{mime};base64,{b64}"
        return None
    except Exception:
        return None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate():
    if not GEMINI_API_KEY:
        return jsonify({"error": "GEMINI_API_KEY not set in .env"}), 500

    body = request.get_json(silent=True) or {}
    prompt = (body.get("prompt") or "").strip()
    model = (body.get("model") or DEFAULT_MODEL).strip()
    resolution = (body.get("resolution") or "1K").upper()
    aspect_ratio = (body.get("aspectRatio") or "").strip()
    attachments = body.get("attachments") or []  # [{mimeType, data}]

    if not prompt:
        return jsonify({"error": "prompt is required"}), 400
    if model not in VALID_MODELS:
        return jsonify({"error": f"model must be one of {sorted(VALID_MODELS)}"}), 400
    if resolution not in VALID_RESOLUTIONS:
        return jsonify({"error": f"resolution must be one of {VALID_RESOLUTIONS}"}), 400
    if aspect_ratio and aspect_ratio not in VALID_ASPECT_RATIOS:
        return jsonify({"error": f"aspectRatio must be one of {sorted(VALID_ASPECT_RATIOS)}"}), 400

    shots = body.get("shots", 3)
    if not isinstance(shots, int) or shots < 1 or shots > 9:
        return jsonify({"error": "shots must be 1–9"}), 400

    images = [None] * shots
    with ThreadPoolExecutor(max_workers=shots) as executor:
        futures = {executor.submit(call_gemini, prompt, resolution, aspect_ratio, attachments, model): i for i in range(shots)}
        for future in as_completed(futures):
            idx = futures[future]
            images[idx] = future.result()

    return jsonify({"images": images})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
