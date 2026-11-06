import json
import os
import re
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

import server

ROOT = Path(__file__).resolve().parent
PUBLIC_ASSETS = {
    "/": "index.html",
    "/index.html": "index.html",
    "/api-config.js": "api-config.js",
    "/manifest.json": "manifest.json",
    "/sw.js": "sw.js",
    "/icon.svg": "icon.svg",
    "/icon-180.png": "icon-180.png",
    "/icon-192.png": "icon-192.png",
    "/icon-512.png": "icon-512.png",
}
MAX_REQUEST_BYTES = 5 * 1024 * 1024
MAX_CHAT_REQUESTS_PER_MINUTE = 20
MAX_GENERATIONS_PER_MINUTE = 3
CHAT_REQUESTS = {}
CHAT_REQUESTS_LOCK = threading.Lock()
GENERATION_REQUESTS = {}
REPLICATE_API = "https://api.replicate.com/v1"
MODEL_SLUG_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$")
PREDICTION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
REPLICATE_OUTPUT_HOSTS = ("replicate.delivery",)
NON_PHOTOREALISTIC_STYLES = (
    "anime", "cartoon", "comic", "drawing", "illustration", "oil painting",
    "pixel art", "sketch", "watercolor", "3d render",
)

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def parse_public_origins(value):
    origins = []
    for raw_origin in value.split(","):
        origin = raw_origin.strip()
        if not origin:
            continue
        parts = urlsplit(origin)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.path not in ("", "/")
            or parts.query
            or parts.fragment
        ):
            raise ValueError(f"Invalid public CORS origin: {origin}")
        origins.append(f"https://{parts.netloc}")
    return origins


app.add_middleware(
    CORSMiddleware,
    allow_origins=parse_public_origins(os.getenv("OMNIS_CORS_ORIGINS", "")),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def allow_chat_request(client_id):
    now = time.monotonic()
    with CHAT_REQUESTS_LOCK:
        recent = [stamp for stamp in CHAT_REQUESTS.get(client_id, []) if now - stamp < 60]
        if len(recent) >= MAX_CHAT_REQUESTS_PER_MINUTE:
            CHAT_REQUESTS[client_id] = recent
            return False
        recent.append(now)
        CHAT_REQUESTS[client_id] = recent
        if len(CHAT_REQUESTS) > 1024:
            for key, stamps in list(CHAT_REQUESTS.items()):
                active = [stamp for stamp in stamps if now - stamp < 60]
                if active:
                    CHAT_REQUESTS[key] = active
                else:
                    del CHAT_REQUESTS[key]
        return True


def allow_generation_request(client_id):
    now = time.monotonic()
    with CHAT_REQUESTS_LOCK:
        recent = [stamp for stamp in GENERATION_REQUESTS.get(client_id, []) if now - stamp < 60]
        if len(recent) >= MAX_GENERATIONS_PER_MINUTE:
            GENERATION_REQUESTS[client_id] = recent
            return False
        recent.append(now)
        GENERATION_REQUESTS[client_id] = recent
        return True


def request_client_id(request):
    forwarded_for = request.headers.get("x-forwarded-for", "")
    return (
        forwarded_for.rsplit(",", 1)[-1].strip()
        or (request.client.host if request.client else "unknown")
    )


async def read_payload(request):
    try:
        content_length = int(request.headers.get("content-length", "0"))
    except ValueError:
        return None, JSONResponse({"error": "Invalid Content-Length header."}, status_code=400)
    if content_length > MAX_REQUEST_BYTES:
        return None, JSONResponse({"error": "Request is too large."}, status_code=413)
    try:
        body = await request.body()
        if len(body) > MAX_REQUEST_BYTES:
            return None, JSONResponse({"error": "Request is too large."}, status_code=413)
        payload = json.loads(body or b"{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, JSONResponse({"error": "Request must contain valid JSON."}, status_code=400)
    if not isinstance(payload, dict):
        return None, JSONResponse({"error": "Request must be a JSON object."}, status_code=400)
    return payload, None


def replicate_model_for(media_type):
    model = {
        "image": server.REPLICATE_IMAGE_MODEL,
        "video": server.REPLICATE_VIDEO_MODEL,
    }.get(media_type, "")
    if not server.REPLICATE_API_TOKEN or not model:
        raise ValueError(f"Public {media_type} generation is not configured.")
    if not MODEL_SLUG_PATTERN.fullmatch(model):
        raise ValueError(f"Invalid configured Replicate {media_type} model.")
    return model


def prepare_media_prompt(media_type, prompt):
    normalized = prompt.strip()
    lowered = normalized.lower()
    if media_type == "image" and not any(style in lowered for style in NON_PHOTOREALISTIC_STYLES):
        return (
            "Photorealistic image, true-to-life detail, natural lighting, realistic textures, "
            "accurate perspective, lifelike colors. Scene: " + normalized
        )
    if media_type == "video":
        style = (
            "Photorealistic video, natural lighting, "
            if not any(style in lowered for style in NON_PHOTOREALISTIC_STYLES)
            else ""
        )
        return (
            style + "One continuous shot with coherent beginning-to-end motion, "
            "consistent subject appearance, physically plausible action, and smooth "
            "camera movement. Preserve the requested art style and scene. Scene: "
            + normalized
        )
    return normalized


def replicate_request(path, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {
        "Authorization": f"Bearer {server.REPLICATE_API_TOKEN}",
        "Content-Type": "application/json",
    }
    if payload is not None:
        headers["Prefer"] = "wait=1"
    request = Request(REPLICATE_API + path, data=body, headers=headers)
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise RuntimeError("The Replicate token is invalid or does not have access.") from exc
        if exc.code == 429:
            raise RuntimeError("Replicate is busy or its usage limit was reached. Try again later.") from exc
        raise RuntimeError(f"Replicate returned HTTP {exc.code}. Check the configured model.") from exc
    except (TimeoutError, URLError) as exc:
        raise RuntimeError("Replicate could not be reached. Please try again.") from exc


def replicate_media_urls(output):
    candidates = output if isinstance(output, list) else [output]
    media = []
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        try:
            from urllib.parse import urlsplit
            parsed = urlsplit(candidate)
        except ValueError:
            continue
        hostname = (parsed.hostname or "").lower()
        if (
            parsed.scheme == "https"
            and any(hostname == domain or hostname.endswith("." + domain)
                    for domain in REPLICATE_OUTPUT_HOSTS)
        ):
            media.append(candidate)
    return media


def public_media_job(job_id, media_type=""):
    if not PREDICTION_ID_PATTERN.fullmatch(job_id):
        return JSONResponse({"error": "Generation job not found."}, status_code=404)
    prediction = replicate_request(f"/predictions/{job_id}")
    status = prediction.get("status")
    if status == "succeeded":
        urls = replicate_media_urls(prediction.get("output"))
        if not urls:
            return JSONResponse(
                {"status": "error", "error": "The model returned no supported media."},
            )
        return {
            "status": "done",
            "media": [
                {
                    "type": media_type or (
                        "video"
                        if url.lower().split("?", 1)[0].endswith((".mp4", ".webm", ".mov"))
                        else "image"
                    ),
                    "url": url,
                }
                for url in urls
            ],
        }
    if status in ("failed", "canceled"):
        return {"status": "error", "error": "The hosted media model could not finish this request."}
    if status not in ("starting", "processing"):
        return JSONResponse({"status": "error", "error": "Unexpected generation status."})
    return {"status": "running", "media": []}


@app.get("/api/health")
async def health():
    return {
        "status": "ready",
        "public_mode": True,
        "model": server.HOSTED_MODEL or "hosted model not configured",
        "hosted_model_configured": server.hosted_model_is_configured(),
        "image_generation": bool(server.REPLICATE_API_TOKEN and server.REPLICATE_IMAGE_MODEL),
        "video_generation": bool(server.REPLICATE_API_TOKEN and server.REPLICATE_VIDEO_MODEL),
        "ollama": False,
    }


@app.post("/api/generate")
async def generate_media(request: Request):
    if not allow_generation_request(request_client_id(request)):
        return JSONResponse(
            {"error": "Generation is busy. Please wait a minute before trying again."},
            status_code=429,
        )
    payload, error = await read_payload(request)
    if error:
        return error
    media_type = payload.get("type")
    if media_type not in ("image", "video"):
        return JSONResponse({"error": "Choose image or video generation."}, status_code=400)
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 4000:
        return JSONResponse({"error": "Enter a prompt of 1–4000 characters."}, status_code=400)
    try:
        model = replicate_model_for(media_type)
        prediction = replicate_request(
            f"/models/{model}/predictions",
            {"input": {"prompt": prepare_media_prompt(media_type, prompt)}},
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)
    job_id = prediction.get("id")
    if not isinstance(job_id, str) or not PREDICTION_ID_PATTERN.fullmatch(job_id):
        return JSONResponse({"error": "The hosted model returned an invalid job ID."}, status_code=502)
    if prediction.get("status") == "succeeded":
        urls = replicate_media_urls(prediction.get("output"))
        if urls:
            return {
                "status": "done",
                "media": [
                    {"type": media_type, "url": url}
                    for url in urls
                ],
            }
    return JSONResponse(
        {"job_id": job_id, "status": "queued"},
        status_code=202,
    )


@app.get("/api/jobs/{job_id}")
async def media_job(job_id: str, media_type: str = ""):
    if media_type not in ("", "image", "video"):
        return JSONResponse({"error": "Unsupported media type."}, status_code=400)
    try:
        return public_media_job(job_id, media_type)
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)


@app.post("/api/chat/stream")
async def chat_stream(request: Request):
    if not allow_chat_request(request_client_id(request)):
        return JSONResponse(
            {"error": "Chat is busy. Please wait a minute before trying again."},
            status_code=429,
        )
    payload, error = await read_payload(request)
    if error:
        return error
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages or not all(
        isinstance(message, dict) for message in messages
    ):
        return JSONResponse(
            {"error": "messages must be a non-empty array of message objects."},
            status_code=400,
        )
    try:
        server.conversation_id_from(payload)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    def generate():
        for event in server.chat_stream(payload, public_mode=True):
            yield (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def unavailable_api(path):
    return JSONResponse({"error": "Endpoint not found."}, status_code=404)


@app.get("/{asset_path:path}")
async def public_asset(asset_path: str):
    asset = PUBLIC_ASSETS.get("/" + asset_path)
    if asset is None:
        return JSONResponse({"error": "Not found."}, status_code=404)
    response = FileResponse(ROOT / asset)
    if asset in ("index.html", "manifest.json", "sw.js"):
        response.headers["Cache-Control"] = "no-store"
    return response
