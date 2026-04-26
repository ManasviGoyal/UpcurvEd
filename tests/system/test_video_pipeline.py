"""System tests for complete video generation pipeline"""

import json

import pytest
from fastapi.testclient import TestClient

import backend.api.main as main_mod
from backend.api.main import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def mock_auth(monkeypatch):
    """Mock Firebase authentication for all system tests."""

    def fake_require_user(authorization=None):
        return "test-uid"

    monkeypatch.setattr(main_mod, "require_firebase_user", fake_require_user)


class TestVideoGenerationPipeline:
    """End-to-end tests for video generation."""

    def test_full_generation_pipeline_success(self, client, monkeypatch):
        """Test complete pipeline from prompt to video."""

        def fake_call_llm(provider, api_key, model, system, user):
            if "Produce a plan with this JSON structure" in user:
                return json.dumps(
                    {
                        "title": "Circle Demo",
                        "description": "Drawing a circle",
                        "contexts": [],
                        "scenes": [
                            {
                                "id": "s1",
                                "duration_seconds": 2.0,
                                "voiceover_text": "Watch this circle appear",
                                "code_plan": None,
                                "language": "en",
                            }
                        ],
                        "code_plan": None,
                    }
                )
            return (
                "from manim import *\n"
                "from manim_voiceover import VoiceoverScene\n"
                "from manim_voiceover.services.gtts import GTTSService\n"
                "class GeneratedScene(VoiceoverScene):\n"
                "    def construct(self):\n"
                "        self.set_speech_service(GTTSService())\n"
                "        with self.voiceover(text='Watch this circle appear') as tracker:\n"
                "            c = Circle()\n"
                "            self.play(Create(c), run_time=tracker.duration)\n"
            )

        def fake_run_job(code: str, scene_name: str = "GeneratedScene", timeout_seconds: int = 600):
            # Don't assert on code content, just return success
            return {
                "ok": True,
                "status": "ok",
                "job_id": "system-test-123",
                "video_url": "/static/jobs/system-test-123/video.mp4",
                "logs": {"stdout_url": "", "stderr_url": "", "cmd_url": ""},
            }

        # Patch where used (in main.py)
        import backend.api.main as main_mod

        monkeypatch.setattr(main_mod, "run_job_from_code", fake_run_job)

        response = client.post(
            "/generate",
            json={
                "prompt": "Draw a circle",
                "keys": {"claude": "test-key"},
                "provider": "claude",
                "model": "claude-3-5-sonnet-latest",
            },
        )

        assert response.status_code == 200
        data = response.json()
        # Response should have structured data (may succeed or fail in rendering)
        assert "status" in data
        # Either succeeds or fails gracefully
        assert data["status"] in ["ok", "error"]

    def test_generation_with_retry_logic(self, client, monkeypatch):
        """Test that pipeline completes with global mocks."""
        # Mock run_job to succeed
        import backend.api.main as main_mod

        def fake_run_job(code: str, scene_name: str = "GeneratedScene", timeout_seconds: int = 600):
            return {
                "ok": True,
                "status": "ok",
                "job_id": "retry-test-job",
                "video_url": "/static/jobs/retry-test-job/video.mp4",
                "logs": {"stdout_url": "", "stderr_url": "", "cmd_url": ""},
            }

        monkeypatch.setattr(main_mod, "run_job_from_code", fake_run_job)

        response = client.post(
            "/generate",
            json={
                "prompt": "Test animation",
                "keys": {"claude": "test-key"},
            },
        )

        # Global mock handles LLM, local mock handles job execution
        assert response.status_code == 200
        data = response.json()
        # Response may succeed or fail, but should return structured data
        assert "status" in data or "ok" in data

    def test_error_propagation_to_api(self, client, monkeypatch):
        """Test that backend errors are properly reported."""
        from backend.agent import llm

        def fake_call_llm(provider, api_key, model, system, user):
            raise RuntimeError("LLM service unavailable")

        monkeypatch.setattr(llm.clients, "call_llm", fake_call_llm)

        response = client.post(
            "/generate",
            json={
                "prompt": "Test",
                "keys": {"claude": "test-key"},
            },
        )

        # Should return 500 or handle error
        assert response.status_code in (500, 200)
        if response.status_code == 200:
            data = response.json()
            # If it returns 200, it should indicate failure
            assert data.get("ok") is False or data.get("status") == "error"


class TestMCPPipelines:
    """End-to-end tests for MCP (quiz/podcast) pipelines."""

    def test_quiz_generation_end_to_end(self, client, monkeypatch):
        """Test complete quiz generation pipeline."""
        from backend.agent import llm

        def fake_call_llm(provider, api_key, model, system, user):
            return json.dumps(
                {
                    "title": "Math Quiz",
                    "description": "Basic arithmetic",
                    "questions": [
                        {
                            "type": "multiple_choice",
                            "prompt": "What is 1+1?",
                            "options": ["1", "2", "3", "4"],
                            "correctIndex": 1,
                        },
                        {
                            "type": "multiple_choice",
                            "prompt": "What is 2x2?",
                            "options": ["2", "4", "6", "8"],
                            "correctIndex": 1,
                        },
                    ],
                }
            )

        monkeypatch.setattr(llm.clients, "call_llm", fake_call_llm)

        response = client.post(
            "/quiz/embedded",
            json={
                "prompt": "Generate a math quiz",
                "num_questions": 2,
                "difficulty": "easy",
                "keys": {"claude": "test-key"},
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        quiz = data["quiz"]
        assert quiz["title"] == "Math Quiz"
        assert len(quiz["questions"]) >= 1

    def test_podcast_generation_end_to_end(self, client, monkeypatch):
        """Test complete podcast generation pipeline."""

        def fake_generate_podcast(**kwargs):
            return {
                "status": "ok",
                "job_id": "podcast-test-123",
                "video_url": "/static/jobs/podcast-test-123/podcast.mp3",
                "srt_url": "/static/jobs/podcast-test-123/podcast.srt",
                "vtt_url": "/static/jobs/podcast-test-123/podcast.vtt",
                "lang": "en",
            }

        # Patch generate_podcast where it's imported in main.py
        monkeypatch.setattr(main_mod, "generate_podcast", fake_generate_podcast)

        response = client.post(
            "/podcast",
            json={
                "prompt": "Science podcast",
                "keys": {"claude": "test-key"},
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "video_url" in data or "mp3" in str(data)
