import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from local_ports import available_local_port


ROOT = Path(__file__).resolve().parent
MODEL = os.getenv("OMNIS_MODEL", "qwen2.5:7b")
OLLAMA_URL = os.getenv("OMNIS_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
COMFY_URL = os.getenv("OMNIS_COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
COMFY_DIR = Path(os.getenv("OMNIS_COMFY_DIR", str(Path.home() / "ComfyUI")))
LOCAL_DATA = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "OmnisAI"
LOG_PATH = LOCAL_DATA / "launcher.log"
STATE_PATH = LOCAL_DATA / "local-app.json"
MODEL_FILES = (
    Path("models/diffusion_models/dreamshaper-8-unet-fp16.safetensors"),
    Path("models/text_encoders/dreamshaper-8-clip-fp16.safetensors"),
    Path("models/vae/dreamshaper-8-vae-fp16.safetensors"),
)
STARTUP_TIMEOUT = 120


def log(message):
    LOCAL_DATA.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as output:
        output.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")


def request_json(url, timeout=3):
    request = urllib.request.Request(url, headers={"User-Agent": "Omnis-Local/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def read_ollama_models():
    try:
        return request_json(f"{OLLAMA_URL}/api/tags").get("models", [])
    except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError):
        return None


def ollama_has_model():
    models = read_ollama_models()
    return models is not None and any(model.get("name") == MODEL for model in models)


def comfy_is_ready():
    try:
        return bool(request_json(f"{COMFY_URL}/system_stats").get("system"))
    except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError):
        return False


def model_files_are_present():
    return all(
        (COMFY_DIR / relative_path).is_file()
        and (COMFY_DIR / relative_path).stat().st_size > 0
        for relative_path in MODEL_FILES
    )


def start_hidden(arguments, cwd, environment):
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(
        arguments,
        cwd=str(cwd),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )


def find_ollama_executable():
    candidates = (
        Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
        ROOT / "runtime" / "ollama" / "ollama.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    discovered = shutil.which("ollama")
    return Path(discovered) if discovered else None


def ensure_ollama():
    models = read_ollama_models()
    if models is not None:
        if not any(model.get("name") == MODEL for model in models):
            available = ", ".join(model.get("name", "") for model in models)
            raise RuntimeError(
                f"Ollama is running, but {MODEL} is not installed. Available models: "
                f"{available or 'none'}. Install {MODEL} once, then start Omnis again."
            )
        log(f"Ollama and model {MODEL} are ready.")
        return

    executable = find_ollama_executable()
    if not executable:
        raise RuntimeError(
            "Ollama is not installed. Install Ollama once; Omnis will start it automatically "
            "next time. The required model is qwen2.5:7b."
        )

    environment = os.environ.copy()
    environment["OLLAMA_HOST"] = "127.0.0.1:11434"
    try:
        start_hidden([str(executable), "serve"], ROOT, environment)
        log(f"Started Ollama service using {executable}.")
    except OSError as exc:
        log(f"Could not start Ollama: {exc}")

    deadline = time.monotonic() + STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        models = read_ollama_models()
        if models is not None:
            if any(model.get("name") == MODEL for model in models):
                log(f"Ollama and model {MODEL} are ready.")
                return
            available = ", ".join(model.get("name", "") for model in models)
            raise RuntimeError(
                f"Ollama started, but {MODEL} is not installed. Available models: "
                f"{available or 'none'}. Install {MODEL} once, then start Omnis again."
            )
        time.sleep(2)

    raise RuntimeError(
        f"Ollama did not respond within {STARTUP_TIMEOUT} seconds. "
        "Check the local launcher log and try again."
    )


def start_comfyui():
    if not model_files_are_present():
        log(f"ComfyUI image models are missing under {COMFY_DIR}; chat will still start.")
        return False
    workflow = ROOT / "image-workflow-api.json"
    if not workflow.is_file():
        log(f"ComfyUI API workflow is missing: {workflow}; chat will still start.")
        return False
    if comfy_is_ready():
        log("ComfyUI is already running.")
        return True

    launcher = COMFY_DIR / "start-cpu.bat"
    if not launcher.is_file():
        log(f"ComfyUI launcher is missing: {launcher}; chat will still start.")
        return False

    command = ["cmd.exe", "/c", "start", "Omnis ComfyUI (CPU)", "/min", str(launcher)]
    try:
        subprocess.Popen(
            command,
            cwd=str(COMFY_DIR),
            env=os.environ.copy(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            close_fds=True,
        )
        log(f"Started ComfyUI from {launcher}.")
    except OSError as exc:
        log(f"Could not start ComfyUI: {exc}")
        return False

    deadline = time.monotonic() + STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        if comfy_is_ready():
            log("ComfyUI is ready.")
            return True
        time.sleep(2)
    log("ComfyUI did not start within the readiness timeout; chat will still start.")
    return False


def process_is_running(process_id):
    if not isinstance(process_id, int) or process_id <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(0x1000, False, process_id)
        if not handle:
            return ctypes.get_last_error() == 5
        try:
            exit_code = wintypes.DWORD()
            return bool(
                kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                and exit_code.value == 259
            )
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(process_id, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def existing_app_url():
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if state.get("root") != str(ROOT) or not process_is_running(state.get("server_pid")):
            return None
        port = int(state["port"])
        health = request_json(f"http://127.0.0.1:{port}/api/health")
        if health.get("status") == "ready" and not health.get("public_mode", False):
            return f"http://127.0.0.1:{port}/"
    except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError, json.JSONDecodeError):
        return None
    return None


def write_state(server_pid, port):
    LOCAL_DATA.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"root": str(ROOT), "server_pid": server_pid, "port": port}),
        encoding="utf-8",
    )
    temporary.replace(STATE_PATH)


def start_server():
    python = Path(sys.executable)
    if not python.is_file():
        raise RuntimeError(f"The bundled Python runtime is missing: {python}")
    script = ROOT / "server.py"
    if not script.is_file():
        raise RuntimeError(f"Omnis server is missing: {script}")

    port = available_local_port()
    workflow = ROOT / "image-workflow-api.json"
    image_generation_configured = model_files_are_present() and workflow.is_file()
    environment = os.environ.copy()
    environment.update({
        "PORT": str(port),
        "OMNIS_HOST": "127.0.0.1",
        "OMNIS_OPEN_BROWSER": "0",
        "OMNIS_MODEL": MODEL,
        "OMNIS_OLLAMA_URL": OLLAMA_URL,
        "OMNIS_COMFY_DIR": str(COMFY_DIR),
        "OMNIS_COMFY_URL": COMFY_URL if image_generation_configured else "",
        "OMNIS_IMAGE_WORKFLOW": str(workflow)
        if image_generation_configured
        else "",
        "OMNIS_VIDEO_WORKFLOW": "",
    })
    environment.pop("OMNIS_PUBLIC_MODE", None)
    environment.pop("PUBLIC_MODE", None)

    LOCAL_DATA.mkdir(parents=True, exist_ok=True)
    server_log = LOCAL_DATA / "server.log"
    with server_log.open("a", encoding="utf-8") as output:
        process = subprocess.Popen(
            [str(python), str(script)],
            cwd=str(ROOT),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            close_fds=True,
        )
    log(f"Started the PC-local Omnis server (pid {process.pid}) on port {port}.")

    deadline = time.monotonic() + 60
    url = f"http://127.0.0.1:{port}/"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            tail = server_log.read_text(encoding="utf-8", errors="replace")[-2000:]
            raise RuntimeError(f"Omnis server stopped during startup. Server log:\n{tail}")
        try:
            if request_json(f"http://127.0.0.1:{port}/api/health").get("status") == "ready":
                write_state(process.pid, port)
                return url
        except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError):
            pass
        time.sleep(1)
    raise TimeoutError(f"Omnis did not become ready in 60 seconds. See {server_log}.")


def open_app():
    ensure_ollama()
    start_comfyui()
    url = existing_app_url()
    if url:
        log(f"Reusing the running PC-local Omnis app at {url}.")
        webbrowser.open(url, new=2)
        return url

    url = start_server()
    if not webbrowser.open(url, new=2):
        log(f"Could not open the default browser automatically. Open {url} manually.")
    log(f"Opened Omnis at {url}.")
    return url


def show_error(message):
    log(message)
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                None,
                f"{message}\n\nDetails are in {LOG_PATH}.",
                "Omnis AI could not start",
                0x10,
            )
        except (AttributeError, OSError):
            pass
    else:
        print(message, file=sys.stderr)


if __name__ == "__main__":
    try:
        open_app()
    except (OSError, RuntimeError, TimeoutError, ValueError) as error:
        show_error(str(error))
        sys.exit(1)
