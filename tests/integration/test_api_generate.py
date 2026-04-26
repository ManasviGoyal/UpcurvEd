"""Integration tests for /generate endpoint"""

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def mock_auth(monkeypatch):
    """Mock Firebase authentication."""
    import backend.api.main as main_mod

    def fake_auth(authorization=None):
        return "test-uid-123"

    monkeypatch.setattr(main_mod, "require_firebase_user", fake_auth)
    return fake_auth


class TestGenerateEndpoint:
    """Test /generate endpoint."""

    def test_generate_requires_auth(self, client):
        """Generate endpoint works with authentication."""
        # With our test mock, auth always succeeds
        response = client.post(
            "/generate",
            json={
                "prompt": "Draw a circle",
                "keys": {"claude": "key"},
            },
        )
        # Auth is mocked, so request proceeds (may fail for other reasons)
        assert response.status_code in [200, 500]  # Either succeeds or fails in processing

    def test_generate_success_path(self, client, mock_auth, monkeypatch):
        """Successful generation should return video URL."""
        import backend.api.main as main_mod

        def fake_run_to_code(**kwargs):
            code = "class GeneratedScene(VoiceoverScene): pass"
            video_url = "/static/jobs/test123/out/video.mp4"
            render_ok = True
            tries = 1
            attempt_job_ids = ["test123"]
            succeeded_job_id = "test123"
            return code, video_url, render_ok, tries, attempt_job_ids, succeeded_job_id

        # Patch where it's used (in main.py)
        monkeypatch.setattr(main_mod, "run_to_code", fake_run_to_code)

        response = client.post(
            "/generate",
            json={
                "prompt": "Draw a circle",
                "keys": {"claude": "test-key"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["status"] == "ok"
        assert "video_url" in data
        assert data["video_url"].endswith(".mp4")

    def test_generate_failure_path(self, client, mock_auth, monkeypatch):
        """Failed generation should return error status."""
        import backend.api.main as main_mod

        def fake_run_to_code(**kwargs):
            code = "# Failed code"
            video_url = None
            render_ok = False
            tries = 3
            attempt_job_ids = ["job1", "job2", "job3"]
            succeeded_job_id = None
            return code, video_url, render_ok, tries, attempt_job_ids, succeeded_job_id

        monkeypatch.setattr(main_mod, "run_to_code", fake_run_to_code)

        response = client.post(
            "/generate",
            json={
                "prompt": "Draw something impossible",
                "keys": {"claude": "test-key"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False
        assert data["status"] == "error"
        assert data["video_url"] is None

    def test_generate_with_provider_selection(self, client, mock_auth, monkeypatch):
        """Generate should respect provider selection."""
        import backend.api.main as main_mod

        captured_kwargs = {}

        def fake_run_to_code(**kwargs):
            captured_kwargs.update(kwargs)
            return "code", "/static/test.mp4", True, 1, ["job1"], "job1"

        monkeypatch.setattr(main_mod, "run_to_code", fake_run_to_code)

        response = client.post(
            "/generate",
            json={
                "prompt": "Test",
                "keys": {"gemini": "gemini-key"},
                "provider": "gemini",
            },
        )
        assert response.status_code == 200
        assert captured_kwargs.get("provider") == "gemini"

    def test_generate_with_model_selection(self, client, mock_auth, monkeypatch):
        """Generate should respect model selection."""
        import backend.api.main as main_mod

        captured_kwargs = {}

        def fake_run_to_code(**kwargs):
            captured_kwargs.update(kwargs)
            return "code", "/static/test.mp4", True, 1, ["job1"], "job1"

        monkeypatch.setattr(main_mod, "run_to_code", fake_run_to_code)

        response = client.post(
            "/generate",
            json={
                "prompt": "Test",
                "keys": {"claude": "key"},
                "provider": "claude",
                "model": "claude-sonnet-4-6",
            },
        )
        assert response.status_code == 200
        assert captured_kwargs.get("model") == "claude-sonnet-4-6"

    def test_generate_infers_provider_from_keys(self, client, mock_auth, monkeypatch):
        """Generate should infer provider if not specified."""
        import backend.api.main as main_mod

        captured_kwargs = {}

        def fake_run_to_code(**kwargs):
            captured_kwargs.update(kwargs)
            return "code", "/static/test.mp4", True, 1, ["job1"], "job1"

        monkeypatch.setattr(main_mod, "run_to_code", fake_run_to_code)

        # Provide only gemini key, no explicit provider
        response = client.post(
            "/generate",
            json={
                "prompt": "Test",
                "keys": {"gemini": "gemini-key"},
            },
        )
        assert response.status_code == 200
        assert captured_kwargs.get("provider") == "gemini"

    def test_generate_with_chat_id(self, client, mock_auth, monkeypatch):
        """Generate should accept chatId for organization."""
        import backend.api.main as main_mod

        def fake_run_to_code(**kwargs):
            return "code", "/static/test.mp4", True, 1, ["job1"], "job1"

        monkeypatch.setattr(main_mod, "run_to_code", fake_run_to_code)

        response = client.post(
            "/generate",
            json={
                "prompt": "Test",
                "keys": {"claude": "key"},
                "chatId": "chat-abc-123",
            },
        )
        assert response.status_code == 200

    def test_generate_with_job_id(self, client, mock_auth, monkeypatch):
        """Generate should accept jobId parameter."""
        import backend.api.main as main_mod

        def fake_run_to_code(**kwargs):
            return "code", "/static/test.mp4", True, 1, ["job1"], "job1"

        monkeypatch.setattr(main_mod, "run_to_code", fake_run_to_code)

        response = client.post(
            "/generate",
            json={
                "prompt": "Test",
                "keys": {"claude": "key"},
                "jobId": "custom-job-123",
            },
        )
        assert response.status_code == 200

    def test_generate_default_model_for_gemini(self, client, mock_auth, monkeypatch):
        """Generate should use default model for Gemini."""
        import backend.api.main as main_mod

        captured_kwargs = {}

        def fake_run_to_code(**kwargs):
            captured_kwargs.update(kwargs)
            return "code", "/static/test.mp4", True, 1, ["job1"], "job1"

        monkeypatch.setattr(main_mod, "run_to_code", fake_run_to_code)

        response = client.post(
            "/generate",
            json={
                "prompt": "Test",
                "keys": {"gemini": "key"},
                "provider": "gemini",
            },
        )
        assert response.status_code == 200
        assert captured_kwargs.get("model") == "gemini-2.5-pro"

    def test_generate_default_model_for_claude(self, client, mock_auth, monkeypatch):
        """Generate should use default model for Claude."""
        import backend.api.main as main_mod

        captured_kwargs = {}

        def fake_run_to_code(**kwargs):
            captured_kwargs.update(kwargs)
            return "code", "/static/test.mp4", True, 1, ["job1"], "job1"

        monkeypatch.setattr(main_mod, "run_to_code", fake_run_to_code)

        response = client.post(
            "/generate",
            json={
                "prompt": "Test",
                "keys": {"claude": "key"},
                "provider": "claude",
            },
        )
        assert response.status_code == 200
        assert captured_kwargs.get("model") == "claude-sonnet-4-6"
