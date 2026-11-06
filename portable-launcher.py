import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PYTHON = ROOT / "python" / "python.exe"
OLLAMA = ROOT / "ollama" / "ollama.exe"
MODEL = "qwen2.5:7b"
OLLAMA_URL = "http://127.0.0.1:11435"
OMNIS_PORT_START = 8000
OMNIS_PORT_ATTEMPTS = 20
COMFY_URL = "http://127.0.0.1:8188"
COMFY_MODEL_FILES = (
    Path("models/diffusion_models/dreamshaper-8-unet-fp16.safetensors"),
    Path("models/text_encoders/dreamshaper-8-clip-fp16.safetensors"),
    Path("models/vae/dreamshaper-8-vae-fp16.safetensors"),
)


def require_file(path, description):
    if not path.is_file():
        raise FileNotFoundError(f"Portable {description} is missing: {path}")


def available_omnis_port(start=OMNIS_PORT_START, attempts=OMNIS_PORT_ATTEMPTS):
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            try:
                listener.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise OSError(
        f"No free local Omnis port is available between {start} and {start + attempts - 1}."
    )


def model_is_available(model_root):
    manifest = model_root / "manifests-v2" / "ollama.com" / "library" / "qwen2.5" / "7b"
    if not manifest.is_file():
        return False
    data = json.loads(manifest.read_text(encoding="utf-8"))
    for layer in data.get("layers", []):
        digest = layer.get("digest", "").replace(":", "-")
        blob = model_root / "blobs" / digest
        if not blob.is_file() or blob.stat().st_size != layer.get("size"):
            return False
    return True


def prepare_model_store():
    source = ROOT / "models"
    if not model_is_available(source):
        raise FileNotFoundError(f"The {MODEL} model files are missing or incomplete under {source}")

    local_app_data = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    candidates = [
        Path.home() / ".ollama" / "models",
        local_app_data / "OmnisAI" / "portable-models" / "qwen2.5-7b",
    ]
    for candidate in candidates:
        if model_is_available(candidate):
            print(f"Using the local {MODEL} model at {candidate}", flush=True)
            return candidate

    size = sum(path.stat().st_size for path in source.rglob("*") if path.is_file())
    if shutil.disk_usage(local_app_data).free < size + 256 * 1024 * 1024:
        raise OSError(
            f"Omnis needs about {size / (1024 ** 3):.1f} GB of free local disk space "
            "to cache its model for faster startup."
        )

    cache = candidates[1]
    cache.parent.mkdir(parents=True, exist_ok=True)
    print(f"Copying the {MODEL} model to this PC for faster startup (about {size / (1024 ** 3):.1f} GB; only needed once).", flush=True)
    shutil.copytree(source, cache, dirs_exist_ok=True)
    if not model_is_available(cache):
        raise OSError(f"The local {MODEL} model cache is incomplete: {cache}")
    return cache


def ollama_ready():
    request = urllib.request.Request(f"{OLLAMA_URL}/api/tags")
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            models = json.loads(response.read().decode("utf-8")).get("models", [])
        return any(model.get("name") == MODEL for model in models)
    except (OSError, ValueError, urllib.error.URLError):
        return False


def comfy_models_available(comfy_dir):
    return all(
        (comfy_dir / relative_path).is_file()
        and (comfy_dir / relative_path).stat().st_size > 0
        for relative_path in COMFY_MODEL_FILES
    )


def comfy_server_ready(url=COMFY_URL):
    request = urllib.request.Request(f"{url}/system_stats")
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def configure_comfyui(env, root=ROOT, comfy_dir=None, readiness_timeout=90):
    comfy_dir = Path(comfy_dir or Path.home() / "ComfyUI")
    workflow = root / "image-workflow-api.json"
    launcher = comfy_dir / "start-cpu.bat"
    python = comfy_dir / ".venv" / "Scripts" / "python.exe"
    env["OMNIS_COMFY_DIR"] = str(comfy_dir)
    env["OMNIS_VIDEO_WORKFLOW"] = ""

    missing_models = [
        str(comfy_dir / relative_path)
        for relative_path in COMFY_MODEL_FILES
        if not (comfy_dir / relative_path).is_file()
        or (comfy_dir / relative_path).stat().st_size == 0
    ]
    if missing_models:
        env["OMNIS_COMFY_URL"] = ""
        env["OMNIS_IMAGE_WORKFLOW"] = ""
        print(
            "Image generation is unavailable: ComfyUI model files are missing or empty: "
            + ", ".join(missing_models),
            flush=True,
        )
        return False
    if not workflow.is_file():
        env["OMNIS_COMFY_URL"] = ""
        env["OMNIS_IMAGE_WORKFLOW"] = ""
        print(f"Image generation is unavailable: workflow not found: {workflow}", flush=True)
        return False
    if not comfy_server_ready():
        if not launcher.is_file() or not python.is_file():
            env["OMNIS_COMFY_URL"] = ""
            env["OMNIS_IMAGE_WORKFLOW"] = ""
            print(
                f"Image generation is unavailable: ComfyUI is not responding and "
                f"its CPU launcher or Python environment is missing under {comfy_dir}.",
                flush=True,
            )
            return False
        print("Starting the installed ComfyUI CPU service...", flush=True)
        subprocess.Popen(
            ["cmd.exe", "/c", "start", "Omnis ComfyUI (CPU)", "/min", str(launcher)],
            cwd=comfy_dir,
            env=os.environ.copy(),
        )
        deadline = time.monotonic() + readiness_timeout
        while time.monotonic() < deadline:
            if comfy_server_ready():
                break
            time.sleep(2)
        else:
            env["OMNIS_COMFY_URL"] = ""
            env["OMNIS_IMAGE_WORKFLOW"] = ""
            print(
                f"Image generation is unavailable: ComfyUI did not respond at "
                f"{COMFY_URL} within {readiness_timeout} seconds.",
                flush=True,
            )
            return False

    env["OMNIS_COMFY_URL"] = COMFY_URL
    env["OMNIS_IMAGE_WORKFLOW"] = str(workflow)
    print(f"ComfyUI image generation is ready at {COMFY_URL}.", flush=True)
    return True


def main():
    require_file(PYTHON, "Python runtime")
    require_file(OLLAMA, "Ollama runtime")
    model_root = prepare_model_store()

    env = os.environ.copy()
    env["OLLAMA_MODELS"] = str(model_root)
    env["OLLAMA_HOST"] = "127.0.0.1:11435"
    env["OMNIS_OLLAMA_URL"] = OLLAMA_URL
    env["OMNIS_MODEL"] = MODEL
    configure_comfyui(env)
    env["OMNIS_MEMORY_DB"] = str(
        Path(env.get("LOCALAPPDATA", str(Path.home()))) / "OmnisAI" / "memory.sqlite3"
    )
    env["PORT"] = str(available_omnis_port())
    env["PYTHONNOUSERSITE"] = "1"

    ollama_process = None
    try:
        if not ollama_ready():
            ollama_process = subprocess.Popen([str(OLLAMA), "serve"], cwd=ROOT, env=env)
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if ollama_process.poll() is not None:
                    raise RuntimeError(f"Portable Ollama exited with code {ollama_process.returncode}")
                if ollama_ready():
                    break
                time.sleep(0.5)
            else:
                raise TimeoutError("Portable Ollama did not become ready within 60 seconds")

        print(f"Omnis is starting at http://127.0.0.1:{env['PORT']}")
        return subprocess.call([str(PYTHON), str(ROOT / "server.py")], cwd=ROOT, env=env)
    finally:
        if ollama_process is not None and ollama_process.poll() is None:
            ollama_process.terminate()
            try:
                ollama_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                ollama_process.kill()
                ollama_process.wait()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (FileNotFoundError, RuntimeError, TimeoutError, OSError, ValueError) as exc:
        print(f"Omnis could not start: {exc}", file=sys.stderr)
        sys.exit(1)
