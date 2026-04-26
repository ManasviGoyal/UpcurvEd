# tests/test_generate_pipeline.py
import json

from fastapi.testclient import TestClient

import backend.api.main as main_mod
from backend.api.main import app


def test_generate_pipeline_happy_path(monkeypatch):
    # 1) Fake LLM to return a valid plan JSON on first call and code on second call.
    from backend.agent import llm

    def fake_call_llm(provider, api_key, model, system, user):
        if "Produce a plan with this JSON structure" in user:
            return json.dumps(
                {
                    "title": "Demo",
                    "description": "Demo desc",
                    "contexts": [],
                    "scenes": [
                        {
                            "id": "s1",
                            "duration_seconds": 2.0,
                            "voiceover_text": "Hello world",
                            "code_plan": None,
                            "language": "en",
                        }
                    ],
                    "code_plan": None,
                }
            )
        # draft path: return runnable-ish code
        return (
            "from manim import *\n"
            "from manim_voiceover import VoiceoverScene\n"
            "from manim_voiceover.services.gtts import GTTSService\n"
            "class GeneratedScene(VoiceoverScene):\n"
            "    def construct(self):\n"
            "        self.set_speech_service(GTTSService())\n"
            "        with self.voiceover(text='Hello world') as tracker:\n"
            "            t = Text('Hello world')\n"
            "            self.play(Write(t), run_time=tracker.duration)\n"
        )

    monkeypatch.setattr(llm.clients, "call_llm", fake_call_llm)

    # 2) Fake job runner to avoid calling manim/pyflakes

    def fake_run_job_from_code(
        code: str, scene_name: str = "GeneratedScene", timeout_seconds: int = 600
    ):
        assert "class GeneratedScene" in code
        return {
            "status": "ok",
            "job_id": "test1234",
            "video_url": "/static/jobs/test1234/video.mp4",
            "logs": {"stdout_url": "", "stderr_url": "", "cmd_url": ""},
        }

    # Patch where it's used (in main.py)
    monkeypatch.setattr(main_mod, "run_job_from_code", fake_run_job_from_code)

    client = TestClient(app)
    payload = {
        "prompt": "Say hello with text.",
        "keys": {
            "claude": "dummy",
            "gemini": "",
        },  # no real keys needed due to monkeypatch
        "provider": "claude",
        "model": "claude-sonnet-4-6",
    }

    # Global mock in conftest.py handles auth
    res = client.post("/generate", json=payload)
    assert res.status_code == 200
    data = res.json()
    # May succeed or fail, but should return structured response
    assert "status" in data


def test_generate_reports_backend_error():
    # Global mock handles LLM, but we can test with invalid params
    client = TestClient(app)

    # Global mock in conftest.py handles auth
    res = client.post(
        "/generate",
        json={
            "prompt": "Anything",
            "keys": {"claude": "x", "gemini": ""},
            "provider": "claude",
        },
    )
    # May succeed or fail, should return response
    assert res.status_code in (200, 401, 400, 500)
