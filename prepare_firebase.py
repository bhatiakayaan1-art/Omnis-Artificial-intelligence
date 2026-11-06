import argparse
import json
import shutil
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "firebase-public"
PUBLIC_FILES = (
    "index.html",
    "manifest.json",
    "sw.js",
    "icon.svg",
    "icon-180.png",
    "icon-192.png",
    "icon-512.png",
)


def validate_api_url(api_url):
    parts = urlsplit(api_url)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
    ):
        raise ValueError("API URL must be a public HTTPS origin with no path or credentials.")
    return f"https://{parts.netloc}"


def prepare_site(api_url, output_dir=DEFAULT_OUTPUT):
    api_origin = validate_api_url(api_url)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    for filename in PUBLIC_FILES:
        source = ROOT / filename
        if not source.is_file():
            raise FileNotFoundError(f"Required public site asset is missing: {source}")
        shutil.copyfile(source, output / filename)
    config = f"window.OMNIS_API_BASE = {json.dumps(api_origin)};\n"
    (output / "api-config.js").write_text(config, encoding="utf-8")
    return output


def main():
    parser = argparse.ArgumentParser(
        description="Build a Firebase Hosting-only Omnis site that calls a hosted Vercel API."
    )
    parser.add_argument(
        "api_url",
        help="HTTPS origin of the deployed Vercel API, for example https://omnis-demo.vercel.app",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()
    try:
        output = prepare_site(arguments.api_url, arguments.output)
    except (ValueError, FileNotFoundError) as exc:
        parser.error(str(exc))
    print(f"Firebase static site prepared at {output}")
    print("Only the Omnis web interface, PWA assets, and configured API origin were copied.")


if __name__ == "__main__":
    main()
