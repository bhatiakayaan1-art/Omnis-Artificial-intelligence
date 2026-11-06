# Omnis AI

Omnis AI is designed to be used as a hosted public web assistant, with an optional private PC/USB version for local tools. The public website runs on cloud services and does not rely on this PC being online; the desktop version is separate. Omnis combines hosted or local models with deterministic tools and auditable controls; it is not a model trained from scratch.

## MVP capabilities

- Local conversational AI through Ollama
- Multilingual chat (including Hindi and Marathi)
- Safe arithmetic and Python simulation execution
- Real-time web search and weather reports
- Allowlisted Windows app launching
- Streaming chat replies and model warm-up for reduced wait times
- Installable, phone-friendly web app for Android and iPhone
- Local image and video generation through configurable ComfyUI workflows
- Voice input using the browser's speech API
- Schoolwork help, including step-by-step math and essay planning/drafting
- Interactive multiple-choice quizzes with explanations and scoring (`/quiz 5 questions about photosynthesis`)
- Photo attachments for questions and problems (JPG, PNG, or WebP; up to 3 MB)
- Code, science, math, art, and general assistance

## Optional local PC version

On the configured PC, double-click `start-local.bat` or the **Omnis AI (Local)** desktop shortcut. The launcher uses the bundled Python runtime, starts Ollama and ComfyUI in the background when needed, and opens the Omnis page in your browser. You do not need to open their separate windows or install Python separately.

Ollama, the `qwen2.5:7b` chat model, ComfyUI, and its DreamShaper image files must still be installed on a new PC. Omnis checks for these components and reports clearly when a model is missing; the large AI models are not downloaded automatically. The configured PC already has them installed.

Photo questions require a vision-capable model. The public hosted model must accept images through the OpenAI-compatible chat-completions API. The bundled local `qwen2.5:7b` model is text-only; to analyze photos locally, install a vision-capable Ollama model (for example, `qwen2.5vl:7b`) and select it with `OMNIS_MODEL`. Uploaded photos are sent to the configured model provider for analysis.

For manual development, run `python server.py` after configuring Ollama and any ComfyUI workflows. The local server uses Python's standard library. Optional configuration:

```bat
set OMNIS_MODEL=llama3.2:3b
set OMNIS_OLLAMA_URL=http://127.0.0.1:11434
set OMNIS_OPEN_BROWSER=0
set PORT=8000
python server.py
```

## Publish Omnis using free hosting tiers

The public website can be split across Google's free Firebase Hosting Spark tier (static interface), Vercel Hobby (Python API), and Google's Gemini API (chat model). These are separate services: Firebase Hosting serves the page; the AI API runs on Vercel; Gemini answers chat. None uses the Ollama or ComfyUI installed on this PC. Free quotas and eligible Gemini models vary, can change, and are not an unlimited guarantee. The Vercel Hobby plan is intended for personal, non-commercial use. A live site needs your own hosting accounts; this computer currently has no Firebase/Vercel CLI or configured provider credentials.

1. **Create a Gemini key:** sign in to [Google AI Studio](https://aistudio.google.com/apikey), create an API key, and choose a model that AI Studio lists as available on the free tier. The Gemini free tier has usage limits; Google says free-tier content may be used to improve its products. Don't send passwords, secrets, or private conversations to a free-tier model.
2. **Create a private GitHub repository:** add the project files. `.gitignore` excludes the bundled model, Ollama runtime, Python runtime, local databases, and secrets. Never upload `.env` files, API keys, or the large `models`, `ollama`, and `python` directories.
3. **Deploy the API to Vercel:** import the private repository and set the Root Directory to the folder containing this README, `app.py`, and `vercel.json` (`.` if those files are at the repository root). In Vercel's environment settings, add:
   - `OMNIS_MODEL_API_URL=https://generativelanguage.googleapis.com/v1beta/openai`
   - `OMNIS_MODEL_API_KEY` = the Gemini key (keep this secret in Vercel settings)
   - `OMNIS_HOSTED_MODEL` = the exact free-tier model ID selected in AI Studio
   - `OMNIS_CORS_ORIGINS=https://YOUR_PROJECT_ID.web.app,https://YOUR_PROJECT_ID.firebaseapp.com`
   
   Deploy the Vercel API and note its `https://...vercel.app` origin. These environment variables configure Google's [OpenAI-compatible Gemini endpoint](https://ai.google.dev/gemini-api/docs/openai); don't put the model key in frontend code.
4. **Create a Firebase project on Spark:** select the no-cost plan in the [Firebase Console](https://console.firebase.google.com/). Copy its project ID; Firebase Hosting provides free `web.app`/`firebaseapp.com` domains within its current quotas. The configuration already uses `firebase.json`.
5. **Build only the public website files:** from this folder, run `python prepare_firebase.py https://YOUR-VERCEL-PROJECT.vercel.app`. This generates `firebase-public` containing only the Omnis page, public icons/PWA metadata, and the Vercel API address—never the Python source, local app, or model files.
6. **Deploy to Firebase Hosting:** install/sign in to the [Firebase CLI](https://firebase.google.com/docs/cli), choose your Firebase project (`firebase use --add`), then run `firebase deploy --only hosting`. The public site's API origin is allowlisted by the Vercel `OMNIS_CORS_ORIGINS` setting above. If you change Firebase project domains, update that setting and redeploy the Vercel API.

### If hosting the interface on GitHub Pages

GitHub Pages serves static files only; it cannot run Omnis' Python chat API. If chat reports that a response is not valid JSON or shows “The page could not be found,” the page is reaching GitHub Pages for `/api/chat/stream` instead of a deployed API. Deploy the backend to Vercel and ensure the repository root includes `app.py`, `server.py`, `vercel.json`, `requirements.txt`, and `.vercelignore`. Set the Vercel environment variables above. In the repository's `api-config.js`, set the public API origin (not a key or token):

```js
window.OMNIS_API_BASE = "https://YOUR-VERCEL-PROJECT.vercel.app";
```

In Vercel, set `OMNIS_CORS_ORIGINS` to the exact website origin, such as `https://YOUR-GITHUB-USERNAME.github.io` (no repository path), then redeploy the API and GitHub Pages site. Keep both API and frontend on HTTPS. The page now shows a setup hint instead of a JSON parsing error when an HTML error page is returned. Do not upload `.env`, provider credentials, local models, Ollama, or the bundled Python runtime.

Firebase Spark covers static hosting only; it does not run this Python API. The Vercel API and Gemini model have their own limits. Optional image/video generation uses Replicate and is billed separately: add `OMNIS_REPLICATE_API_TOKEN`, `OMNIS_REPLICATE_IMAGE_MODEL`, and/or `OMNIS_REPLICATE_VIDEO_MODEL` in Vercel, using `owner/name` model slugs that accept a `prompt` input. Omnis adds photorealism hints by default and preserves explicit illustration styles, but the selected model determines quality and price. Put provider spending limits in place before sharing a public URL. Generated files link to the provider and may expire under its retention policy.

Public mode hides or blocks PC app launching, Python execution, creator access, personal memory, and local Ollama/ComfyUI routes. A basic per-instance chat/generation rate limit is not a substitute for provider quotas or account-level abuse protection.

For quicker chat, Omnis keeps the model loaded for 30 minutes, warms it in the background at startup, streams generated text immediately, and uses a 4K context with a bounded reply length. Actual speed still depends on the PC's RAM, CPU/GPU, and model. A smaller Ollama model such as `qwen2.5:3b` can be selected with `OMNIS_MODEL=qwen2.5:3b`.

## Run Omnis from the KLEVV USB drive

The portable Windows bundle includes Omnis, a standalone 64-bit Python runtime, Ollama, and the `qwen2.5:7b` model. On a 64-bit Windows 10 (22H2+) or Windows 11 PC, open the `Omnis-AI` folder on the USB drive and double-click `start-usb.bat`. Omnis opens in your browser on a free local port starting at http://127.0.0.1:8000; the launcher prints the exact address. This avoids clashing with another local app. Keep the launcher window open and the USB connected while using Omnis; closing the launcher stops its server. A previously installed Omnis app can show a cached screen even when the server is off, but chat will not work until `start-usb.bat` is running. On first use per PC, the launcher copies the model to that user's local app-data folder for faster startup, so allow about 5 GB of free internal storage.

The model uses several gigabytes of RAM, so a PC with at least 8 GB of memory is recommended. Chat and calculations work locally; live search and weather need internet. ComfyUI, image/video models, and any personal conversation history are not included. Omnis keeps each Windows user's memory database on that PC, not on the USB. This bundle is for 64-bit Windows and has not been tested on every PC or Windows configuration.

### Run from this PC without the USB

The `Omnis-AI` folder and `start-local.bat` are installed on the PC. Double-click `start-local.bat` to run Omnis using the locally installed Ollama model and `%USERPROFILE%\ComfyUI`; leave the launcher window open while you use it. It does not depend on the USB drive.

### Local ComfyUI image generation

When `start-usb.bat` runs, Omnis checks `%USERPROFILE%\ComfyUI` for a working ComfyUI CPU installation and the DreamShaper UNET, CLIP, and VAE model files. If present, it starts ComfyUI when needed and connects the USB app to its image workflow. ComfyUI and the image models are not stored on the USB; install and configure them separately on each PC. Image generation runs on the CPU here and may take several minutes. Omnis temporarily unloads its local chat model to free memory, then chat can load it again. Without the local ComfyUI setup and all three models, the launcher clearly reports that image generation is unavailable while the other Omnis features remain usable.

## Local creator mode

Use **Creator access** in the app to set up a new passcode on this PC and unlock a creator identity for the current browser. Choose a fresh passcode of at least 16 characters; enter it in the local dialog, never in the chat. Omnis stores a salted PBKDF2 verifier in `%LOCALAPPDATA%\OmnisAI\creator-auth.json`, not the plaintext passcode or the USB drive. The browser session expires after an hour or can be locked from the dialog. After five incorrect attempts, unlocking is paused for five minutes.

For SMS two-step verification, create a Twilio Verify service and set `OMNIS_TWILIO_ACCOUNT_SID`, `OMNIS_TWILIO_AUTH_TOKEN`, `OMNIS_TWILIO_VERIFY_SERVICE_SID`, and `OMNIS_CREATOR_PHONE_NUMBER` as environment variables for the local launcher. Use a phone number in international E.164 format. Never put these credentials in chat, the source code, or a committed `.env` file. Twilio SMS may incur charges; trial accounts can only send to verified recipient numbers. If these settings are absent, the local app clearly reports that SMS verification is not configured and uses its existing passcode-only sign-in. When enabled, creator sign-in requires the passcode and a short-lived, attempt-limited code delivered by Twilio Verify.

Creator mode only identifies the signed-in creator to Omnis. It does not grant administrator privileges, arbitrary command execution, or unrestricted access to PC files, and it does not expose visitor conversations. The public Omnis deployment does not store or expose visitor chat history. If you want users to contribute conversations for evaluation or training, collect only conversations that each user explicitly chooses to share, with clear disclosure, deletion controls, and a defined retention policy; do not silently collect private chats. Omnis responses can be more considerate of emotional cues, but it does not read minds, diagnose conditions, or replace professional help. The passcode previously shared in chat should be considered exposed; do not reuse it.

## Accuracy and live answers

Interactive quizzes are generated by the configured chat model. Start one with `/quiz <topic>`, `/quiz 5 questions about <topic>`, or `/quiz <topic> --count 5` (1–10 questions). Pick an answer in the page to see whether it is correct and read the explanation; the score stays in the current page and is not saved to conversation memory. Omnis validates the quiz structure, but generated quiz facts and answer keys can still be wrong, so check important educational material.

Omnis uses deterministic local evaluation for recognized arithmetic instead of asking the language model to calculate. Questions about public figures, wars, current affairs, current/latest/recent information, today's news or results, product recommendations, or citations automatically retrieve live web results. Omnis checks that result titles and descriptions match the question before using them; when search fails or results are unrelated, it says it could not verify the answer rather than letting the model guess. Natural-language weather questions such as “What's the weather in Pune?” use Open-Meteo's current conditions, while `/search your query` shows matching web results with source links. Search-result markup is removed and source text is treated as untrusted evidence. The model also gets instructions to cite relevant evidence, state uncertainty and assumptions, and avoid fabricated citations. Non-user-provided song lyrics are not reproduced; Omnis can summarize or discuss a song instead. Recent conversation history is bounded so long chats are less likely to crowd out the latest question, and a lower response temperature makes answers more consistent.

When a live lookup succeeds, Omnis withholds a generated answer unless it cites at least one source number that was actually provided to the model. This catches uncited or nonexistent references, but it does not prove that a citation supports every claim. Check cited source pages for important decisions.

These are accuracy improvements, not a guarantee. Omnis currently uses the local `qwen2.5:7b` model; a small local model can still misunderstand a question, give incorrect answers, or struggle with languages such as Marathi, and search snippets can be incomplete. Omnis does not train its model or independently verify every answer.

The local regression suite includes 1,000 seeded, exact-answer arithmetic prompts across addition, subtraction, multiplication, division, and powers, including number words. This tests deterministic math routing and calculation, not 1,000 general-knowledge or generated answers; creative, multilingual, current-affairs, and media quality still require separate evaluation.

## Local conversation memory

When enabled, Omnis saves completed user/assistant turns in a local SQLite database at `%LOCALAPPDATA%\OmnisAI\memory.sqlite3` on Windows. It also picks up clearly stated preferences and personal details (such as “I prefer short answers” or “My favorite color is blue”) and supplies relevant saved context to later chats. Memory matching is local keyword matching; it is not model training or a change to the model weights.

Use the **Memory: On/Off** control to pause or resume saving and recall. Pausing keeps existing saved data but stops accessing and adding to it. **Forget all** erases saved conversations and extracted details, and starts a fresh chat. Memory stays on the PC; the text of the current conversation still goes to the configured Ollama model on that PC as usual. Anyone who can access the PC's local data may be able to read the memory database, so do not save sensitive information to a shared Windows account.

To choose another local database location, set `OMNIS_MEMORY_DB` before starting Omnis.

## Use Omnis from a phone

Omnis is an installable web app with a phone-sized chat layout, touch-friendly tools, and a home-screen icon. The AI model still runs on the PC; your phone is the remote screen and sends chat requests to that PC.

For private phone access, use a tailnet VPN rather than exposing the Omnis server or opening a router port:

1. Install Tailscale on the PC and phone and sign both into your private tailnet.
2. Start Omnis on the PC with `python server.py` (it stays bound to localhost).
3. In PowerShell on the PC, run `tailscale serve --bg 8000`.
4. Run `tailscale serve status` and open the HTTPS URL it shows on your phone.
5. Add it to the home screen: use the **Install app** button or browser menu on Android; in iPhone Safari use **Share → Add to Home Screen**.

The phone and PC must be online and connected to Tailscale for AI replies. The service worker caches only the app shell; it never caches chat/API responses. Do not bind Omnis to `0.0.0.0`, forward port 8000 from your router, or publish it to the public internet without adding a proper authentication and HTTPS deployment.

## Local tools

Use the Tools panel or chat commands:

- `/calc 12 * (3 + 4) + sqrt(16)`
- `10 plus 10`
- `What is 500 raised to the power of 2?`
- `two hundred and twenty-one times three`
- `/python print(sum(range(100)))`
- `/search current Python release`
- `/weather Pune`
- `/open calculator`
- `/open notepad`
- `/open chrome`
- `/open terminal`
- `/image A watercolor illustration of a mountain lake at sunrise`
- `/video A short cinematic shot of waves rolling onto a beach`
- `/quiz 5 questions about photosynthesis`

### Image and video generation setup

The [ComfyUI](https://github.com/Comfy-Org/ComfyUI) source, Python 3.12 environment, and CPU PyTorch are installed at `%USERPROFILE%\ComfyUI`. This computer's Radeon RX 550 is not a supported NVIDIA CUDA device; CPU mode is used and image generation will be slow. The Omnis image workflow uses Lykon's DreamShaper 8 FP16 files. Run `%USERPROFILE%\ComfyUI\download-model.bat` once to download the approximately 2.1 GB model files from a pinned Hugging Face revision with SHA-256 verification. Review the [model card and CreativeML OpenRAIL-M license](https://huggingface.co/Lykon/dreamshaper-8).

Start ComfyUI in CPU mode with `%USERPROFILE%\ComfyUI\start-cpu.bat`. Start Omnis with `start.bat`, which configures its localhost ComfyUI URL and checked-in API workflow. The Omnis UI reports image generation as available only after the required workflow and model files exist.

Video generation needs a separately installed compatible video model and API workflow and is not included in the CPU setup. Video diffusion is particularly demanding; this PC is not a practical local video-generation machine.

To use different workflows or a different ComfyUI install, configure these variables before starting Omnis:

```bat
set OMNIS_COMFY_URL=http://127.0.0.1:8188
set OMNIS_COMFY_DIR=C:\path\to\ComfyUI
set OMNIS_IMAGE_WORKFLOW=C:\path\to\image-api-workflow.json
set OMNIS_VIDEO_WORKFLOW=C:\path\to\video-api-workflow.json
python server.py
```

For image-only use, the video workflow variable can be omitted. Generation runs as a background job so you can keep chatting while it works. Video-generation latency is hardware- and workflow-dependent and can be substantial on CPU-only PCs.

## Safety

- App launching is restricted to an allowlist.
- HTTP binds to localhost only.
- Generated media is served only by proxying files requested from the configured ComfyUI instance; traversal paths are rejected.
- Python has a 12-second timeout and 20,000-character limit, and runs in a temporary working directory.
- Python is not an OS sandbox. Never execute untrusted code as an elevated process.
- External search and model providers may receive the text you send to them.
- For autonomous file, system, network, and destructive actions, the backend should require explicit confirmation before production use.
