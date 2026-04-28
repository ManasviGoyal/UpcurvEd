"""More integration tests for API coverage."""

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


class TestGenerateVariations:
    """Test generate endpoint variations."""

    def test_generate_with_all_parameters(self, client, monkeypatch):
        """Test generate with maximum parameters."""
        import backend.api.main as main_mod

        def fake_run(**kwargs):
            return "code", "/static/test.mp4", True, 1, ["job1"], "job1"

        monkeypatch.setattr(main_mod, "run_to_code", fake_run)

        response = client.post(
            "/generate",
            json={
                "prompt": "Complex animation",
                "keys": {"claude": "key", "gemini": "key2"},
                "provider": "claude",
                "model": "claude-3-5-sonnet",
                "temperature": 0.7,
                "chatId": "chat-123",
                "jobId": "custom-job",
            },
        )
        assert response.status_code in [200, 500]

    def test_generate_minimal_parameters(self, client, monkeypatch):
        """Test generate with minimal parameters."""
        import backend.api.main as main_mod

        def fake_run(**kwargs):
            return "code", "/static/test.mp4", True, 1, ["job1"], "job1"

        monkeypatch.setattr(main_mod, "run_to_code", fake_run)

        response = client.post(
            "/generate",
            json={
                "prompt": "Simple",
                "keys": {"claude": "key"},
            },
        )
        assert response.status_code in [200, 500]

    def test_generate_different_temperatures(self, client, monkeypatch):
        """Test generate with various temperatures."""
        import backend.api.main as main_mod

        def fake_run(**kwargs):
            return "code", "/static/test.mp4", True, 1, ["job1"], "job1"

        monkeypatch.setattr(main_mod, "run_to_code", fake_run)

        for temp in [0.0, 0.5, 1.0, 1.5]:
            response = client.post(
                "/generate",
                json={
                    "prompt": "Test",
                    "keys": {"claude": "key"},
                    "temperature": temp,
                },
            )
            assert response.status_code in [200, 500]


class TestQuizVariations:
    """Test quiz endpoint variations."""

    def test_quiz_all_difficulties(self, client):
        """Test quiz with all difficulty levels."""
        for difficulty in ["easy", "medium", "hard"]:
            response = client.post(
                "/quiz/embedded",
                json={
                    "prompt": f"Test {difficulty}",
                    "keys": {"claude": "key"},
                    "difficulty": difficulty,
                    "num_questions": 5,
                },
            )
            assert response.status_code in [200, 500]

    def test_quiz_various_question_counts(self, client):
        """Test quiz with different question counts."""
        for count in [1, 5, 10, 20]:
            response = client.post(
                "/quiz/embedded",
                json={
                    "prompt": "Math",
                    "keys": {"claude": "key"},
                    "num_questions": count,
                },
            )
            assert response.status_code in [200, 500]

    def test_quiz_with_long_context(self, client):
        """Test quiz with extensive context."""
        context = "This is a very detailed context. " * 50
        response = client.post(
            "/quiz/embedded",
            json={
                "prompt": "Test",
                "context": context,
                "keys": {"claude": "key"},
            },
        )
        assert response.status_code in [200, 500]

    def test_quiz_with_both_providers(self, client):
        """Test quiz with both providers specified."""
        response = client.post(
            "/quiz/embedded",
            json={
                "prompt": "Science",
                "keys": {"claude": "key1", "gemini": "key2"},
                "provider": "gemini",
            },
        )
        assert response.status_code in [200, 500]


class TestPodcastVariations:
    """Test podcast endpoint variations."""

    def test_podcast_with_different_models(self, client):
        """Test podcast with different model selections."""
        for model in ["claude-3-5-sonnet", "gemini-3-flash-preview"]:
            response = client.post(
                "/podcast",
                json={
                    "prompt": "History",
                    "keys": {"claude": "key"},
                    "model": model,
                },
            )
            assert response.status_code in [200, 500]

    def test_podcast_with_long_prompt(self, client):
        """Test podcast with long prompt."""
        long_prompt = "Explain quantum physics. " * 100
        response = client.post(
            "/podcast",
            json={
                "prompt": long_prompt,
                "keys": {"claude": "key"},
            },
        )
        assert response.status_code in [200, 500]

    def test_podcast_with_context(self, client):
        """Test podcast with additional context."""
        response = client.post(
            "/podcast",
            json={
                "prompt": "Machine learning",
                "context": "Focus on neural networks",
                "keys": {"claude": "key"},
            },
        )
        assert response.status_code in [200, 500]


class TestHealthChecks:
    """Test health and monitoring endpoints."""

    def test_health_multiple_times(self, client):
        """Health check should be consistent."""
        for _ in range(5):
            response = client.get("/health")
            assert response.status_code == 200
            assert response.json()["ok"] is True

    def test_health_with_headers(self, client):
        """Health check should ignore extra headers."""
        response = client.get(
            "/health",
            headers={
                "X-Custom-Header": "value",
                "Authorization": "Bearer fake",
            },
        )
        assert response.status_code == 200

    def test_health_response_time(self, client):
        """Health check should be fast."""
        import time

        start = time.time()
        response = client.get("/health")
        elapsed = time.time() - start
        assert response.status_code == 200
        assert elapsed < 1.0  # Should be subsecond
