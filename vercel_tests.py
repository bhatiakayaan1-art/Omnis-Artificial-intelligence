import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app
import prepare_firebase
import server


class VercelAppTests(unittest.TestCase):
    def setUp(self):
        app.CHAT_REQUESTS.clear()
        app.GENERATION_REQUESTS.clear()
        app.app.middleware_stack = None
        self.client = TestClient(app.app)

    def test_health_never_depends_on_this_pcs_ollama(self):
        with patch.object(server, "MODEL_API_URL", ""), \
                patch.object(server, "MODEL_API_KEY", ""), \
                patch.object(server, "HOSTED_MODEL", ""):
            response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["public_mode"])
        self.assertFalse(response.json()["ollama"])
        self.assertFalse(response.json()["hosted_model_configured"])

    def test_public_page_is_served_but_local_source_and_runtime_files_are_not(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("HOSTED WEB", response.text)
        for path in ("/server.py", "/app.py", "/launcher.py", "/models/model.bin"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_local_only_api_routes_are_not_available(self):
        for method, path in (
            ("get", "/api/creator"),
            ("get", "/api/memory"),
            ("get", "/api/apps"),
            ("post", "/api/open"),
            ("post", "/api/run"),
            ("post", "/api/memory"),
        ):
            with self.subTest(path=path):
                self.assertEqual(getattr(self.client, method)(path).status_code, 404)

    def test_public_math_tool_works_without_a_model_provider(self):
        with patch.object(server, "MODEL_API_URL", ""), \
                patch.object(server, "MODEL_API_KEY", ""), \
                patch.object(server, "HOSTED_MODEL", ""):
            response = self.client.post("/api/chat/stream", json={
                "messages": [{"role": "user", "content": "/calc 10 * 10"}],
            })
        self.assertEqual(response.status_code, 200)
        self.assertIn('"message": "Result: 100"', response.text)

    def test_public_chat_reports_missing_model_provider(self):
        with patch.object(server, "MODEL_API_URL", ""), \
                patch.object(server, "MODEL_API_KEY", ""), \
                patch.object(server, "HOSTED_MODEL", ""):
            response = self.client.post("/api/chat/stream", json={
                "messages": [{"role": "user", "content": "Hello"}],
            })
        self.assertEqual(response.status_code, 200)
        self.assertIn("OMNIS_MODEL_API_URL", response.text)

    def test_public_chat_uses_hosted_provider_without_calling_ollama(self):
        with patch.object(server, "MODEL_API_URL", "https://provider.example/v1"), \
                patch.object(server, "MODEL_API_KEY", "test-token"), \
                patch.object(server, "HOSTED_MODEL", "test-model"), \
                patch.object(server, "hosted_chat_stream", return_value=iter([
                    {"type": "delta", "content": "Hello."},
                    {"type": "done", "model": "test-model"},
                ])) as hosted, \
                patch.object(server, "ollama_chat_stream", side_effect=AssertionError("Ollama called")):
            response = self.client.post("/api/chat/stream", json={
                "messages": [{"role": "user", "content": "Hi Omnis"}],
            })
        self.assertIn('"content": "Hello."', response.text)
        hosted.assert_called_once()

    def test_public_interactive_quiz_uses_hosted_model_and_streams_quiz_data(self):
        quiz = {
            "questions": [{
                "question": "Which is a mammal?",
                "choices": ["Whale", "Shark", "Trout", "Octopus"],
                "answer": 0,
                "explanation": "Whales are mammals that breathe air.",
            }],
        }
        with patch.object(server, "hosted_chat", return_value=json.dumps(quiz)) as hosted, \
                patch.object(server, "ollama_chat", side_effect=AssertionError("Ollama called")):
            response = self.client.post("/api/chat/stream", json={
                "messages": [{"role": "user", "content": "/quiz 1 question about animals"}],
            })
        self.assertEqual(response.status_code, 200)
        event = json.loads(response.text.strip())
        self.assertEqual(event["type"], "result")
        self.assertEqual(event["tool"], "quiz")
        self.assertEqual(event["quiz"]["questions"][0]["answer"], 0)
        hosted.assert_called_once()

    def test_public_chat_passes_uploaded_photos_to_hosted_vision_model(self):
        image = {"mime_type": "image/png", "data": "aW1hZ2U="}
        with patch.object(server, "MODEL_API_URL", "https://provider.example/v1"), \
                patch.object(server, "MODEL_API_KEY", "test-token"), \
                patch.object(server, "HOSTED_MODEL", "test-model"), \
                patch.object(server, "hosted_chat_stream", return_value=iter([
                    {"type": "delta", "content": "Here are the steps."},
                    {"type": "done", "model": "test-model"},
                ])) as hosted:
            response = self.client.post("/api/chat/stream", json={
                "messages": [{
                    "role": "user",
                    "content": "Please solve this.",
                    "images": [image],
                }],
            })
        self.assertEqual(response.status_code, 200)
        self.assertIn("Here are the steps.", response.text)
        self.assertEqual(hosted.call_args.args[0][-1]["images"], [image])

    def test_non_streaming_public_chat_never_uses_local_memory_or_creator_identity(self):
        with patch.object(server, "relevant_memory", side_effect=AssertionError("local memory read")), \
                patch.object(server, "save_memory_turn", side_effect=AssertionError("local memory write")), \
                patch.object(server, "hosted_chat", return_value="Hello.") as hosted:
            response = server.chat({
                "messages": [{"role": "user", "content": "Hi Omnis"}],
            }, creator_mode=True, public_mode=True)
        hosted.assert_called_once()
        self.assertNotIn("authenticated locally as the creator", str(hosted.call_args))
        self.assertEqual(response["message"], "Hello.")

    def test_chat_rate_limit_is_enforced(self):
        payload = {"messages": [{"role": "user", "content": "/calc 1 + 1"}]}
        for _ in range(app.MAX_CHAT_REQUESTS_PER_MINUTE):
            self.assertEqual(self.client.post("/api/chat/stream", json=payload).status_code, 200)
        self.assertEqual(self.client.post("/api/chat/stream", json=payload).status_code, 429)

    def test_oversized_chat_requests_are_rejected(self):
        response = self.client.post(
            "/api/chat/stream",
            content=b'{"large":"' + b"x" * (app.MAX_REQUEST_BYTES + 1) + b'"}',
            headers={"content-type": "application/json"},
        )
        self.assertEqual(response.status_code, 413)

    def test_only_explicit_firebase_origins_are_allowed_to_call_api(self):
        origin = "https://omnis-demo.web.app"
        cors = next(
            middleware for middleware in app.app.user_middleware
            if middleware.cls.__name__ == "CORSMiddleware"
        )
        cors.kwargs["allow_origins"] = [origin]
        app.app.middleware_stack = None
        response = self.client.options(
            "/api/health",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], origin)

    def test_cors_origin_configuration_rejects_wildcards_and_insecure_urls(self):
        for origin in ("*", "http://omnis-demo.web.app", "https://example.com/path"):
            with self.subTest(origin=origin):
                with self.assertRaises(ValueError):
                    app.parse_public_origins(origin)

    def test_firebase_package_contains_only_allowlisted_assets_and_api_origin(self):
        with tempfile.TemporaryDirectory() as directory:
            output = prepare_firebase.prepare_site(
                "https://omnis-api.vercel.app",
                Path(directory) / "public",
            )
            files = {path.name for path in output.iterdir()}
            self.assertEqual(
                files,
                set(prepare_firebase.PUBLIC_FILES) | {"api-config.js"},
            )
            config = (output / "api-config.js").read_text(encoding="utf-8")
            self.assertEqual(
                config,
                'window.OMNIS_API_BASE = "https://omnis-api.vercel.app";\n',
            )
            self.assertNotIn("server.py", files)
            self.assertNotIn("models", files)

    def test_firebase_package_rejects_paths_and_non_https_api_urls(self):
        for url in (
            "http://omnis-api.vercel.app",
            "https://omnis-api.vercel.app/api",
            "https://user:password@omnis-api.vercel.app",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    prepare_firebase.validate_api_url(url)

    def test_media_provider_features_are_reported_separately(self):
        with patch.object(server, "REPLICATE_API_TOKEN", "test-token"), \
                patch.object(server, "REPLICATE_IMAGE_MODEL", "owner/image-model"), \
                patch.object(server, "REPLICATE_VIDEO_MODEL", ""):
            response = self.client.get("/api/health")
        self.assertTrue(response.json()["image_generation"])
        self.assertFalse(response.json()["video_generation"])

    def test_public_image_generation_creates_a_hosted_prediction(self):
        with patch.object(server, "REPLICATE_API_TOKEN", "test-token"), \
                patch.object(server, "REPLICATE_IMAGE_MODEL", "owner/image-model"), \
                patch.object(app, "replicate_request", return_value={
                    "id": "prediction-123",
                    "status": "starting",
                }) as provider, \
                patch.object(server, "comfy_workflow", side_effect=AssertionError("ComfyUI called")):
            response = self.client.post("/api/generate", json={
                "type": "image",
                "prompt": "A realistic portrait with natural light",
            })
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["job_id"], "prediction-123")
        provider.assert_called_once_with(
            "/models/owner/image-model/predictions",
            {"input": {"prompt": (
                "Photorealistic image, true-to-life detail, natural lighting, realistic textures, "
                "accurate perspective, lifelike colors. Scene: A realistic portrait with natural light"
            )}},
        )

    def test_explicit_art_styles_are_preserved(self):
        self.assertEqual(
            app.prepare_media_prompt("image", "Watercolor portrait of a fox"),
            "Watercolor portrait of a fox",
        )
        video_prompt = app.prepare_media_prompt("video", "Animated watercolor landscape")
        self.assertIn("Animated watercolor landscape", video_prompt)
        self.assertIn("Preserve the requested art style", video_prompt)
        self.assertNotIn("Photorealistic", video_prompt)

    def test_video_prompt_adds_continuous_motion_and_camera_guidance(self):
        prompt = app.prepare_media_prompt("video", "A fox running through snow")
        self.assertIn("Photorealistic video", prompt)
        self.assertIn("One continuous shot", prompt)
        self.assertIn("coherent beginning-to-end motion", prompt)
        self.assertIn("smooth camera movement", prompt)
        self.assertIn("A fox running through snow", prompt)

    def test_public_page_keeps_unconfigured_video_control_explainable(self):
        response = self.client.get("/")
        self.assertIn("Generate video", response.text)
        self.assertIn("OMNIS_REPLICATE_VIDEO_MODEL", response.text)
        self.assertIn("Video generation is not configured", response.text)

    def test_video_generation_uses_the_separately_configured_video_model(self):
        with patch.object(server, "REPLICATE_API_TOKEN", "test-token"), \
                patch.object(server, "REPLICATE_VIDEO_MODEL", "owner/video-model"), \
                patch.object(app, "replicate_request", return_value={
                    "id": "video-job-123",
                    "status": "starting",
                }) as provider:
            response = self.client.post("/api/generate", json={
                "type": "video",
                "prompt": "A cinematic landscape shot",
            })
        self.assertEqual(response.status_code, 202)
        provider.assert_called_once_with(
            "/models/owner/video-model/predictions",
            {"input": {"prompt": (
                "Photorealistic video, natural lighting, One continuous shot with coherent "
                "beginning-to-end motion, consistent subject appearance, physically plausible "
                "action, and smooth camera movement. Preserve the requested art style and scene. "
                "Scene: A cinematic landscape shot"
            )}},
        )

    def test_public_generation_never_returns_untrusted_output_urls(self):
        with patch.object(server, "REPLICATE_API_TOKEN", "test-token"), \
                patch.object(app, "replicate_request", return_value={
                    "status": "succeeded",
                    "output": ["https://attacker.example/file.png"],
                }):
            response = self.client.get("/api/jobs/prediction-123")
        self.assertEqual(response.json()["status"], "error")
        self.assertNotIn("attacker.example", response.text)

    def test_public_video_job_preserves_media_type_when_provider_url_has_no_extension(self):
        with patch.object(server, "REPLICATE_API_TOKEN", "test-token"), \
                patch.object(app, "replicate_request", return_value={
                    "status": "succeeded",
                    "output": ["https://replicate.delivery/video-id"],
                }):
            response = self.client.get("/api/jobs/video-job-123?media_type=video")
        self.assertEqual(response.json()["media"][0]["type"], "video")

    def test_public_generation_rejects_invalid_prompts_and_job_ids(self):
        invalid_prompt = self.client.post("/api/generate", json={
            "type": "video",
            "prompt": " ",
        })
        invalid_job = self.client.get("/api/jobs/../../etc/passwd")
        self.assertEqual(invalid_prompt.status_code, 400)
        self.assertEqual(invalid_job.status_code, 404)

    def test_public_generation_rate_limit_protects_provider_spend(self):
        with patch.object(server, "REPLICATE_API_TOKEN", "test-token"), \
                patch.object(server, "REPLICATE_IMAGE_MODEL", "owner/image-model"), \
                patch.object(app, "replicate_request", return_value={
                    "id": "prediction-123",
                    "status": "starting",
                }):
            responses = [
                self.client.post("/api/generate", json={
                    "type": "image",
                    "prompt": "Test",
                })
                for _ in range(app.MAX_GENERATIONS_PER_MINUTE + 1)
            ]
        self.assertEqual(
            [response.status_code for response in responses],
            [202] * app.MAX_GENERATIONS_PER_MINUTE + [429],
        )


if __name__ == "__main__":
    unittest.main()
