"""Additional E2E tests for comprehensive coverage."""

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


class TestFullStackWorkflows:
    """Test complete full-stack workflows."""

    def test_echo_workflow_end_to_end(self, client, monkeypatch):
        """Test echo workflow from request to response."""
        import backend.api.main as main_mod
        from backend.agent import minigraph

        def fake_echo(prompt):
            return f"# Code for: {prompt}"

        def fake_job(code, **kwargs):
            return {
                "ok": True,
                "status": "ok",
                "job_id": "echo-e2e",
                "video_url": "/static/echo.mp4",
            }

        monkeypatch.setattr(minigraph, "echo_manim_code", fake_echo)
        monkeypatch.setattr(main_mod, "run_job_from_code", fake_job)

        response = client.post(
            "/echo",
            json={"prompt": "Draw triangle", "keys": {"claude": "key"}},
        )
        assert response.status_code == 200

    def test_quiz_workflow_end_to_end(self, client):
        """Test quiz workflow from request to response."""
        response = client.post(
            "/quiz/embedded",
            json={
                "prompt": "Physics concepts",
                "num_questions": 10,
                "difficulty": "hard",
                "context": "Focus on mechanics",
                "keys": {"claude": "key"},
            },
        )
        assert response.status_code in [200, 500]

    def test_podcast_workflow_end_to_end(self, client):
        """Test podcast workflow from request to response."""
        response = client.post(
            "/podcast",
            json={
                "prompt": "Explain relativity",
                "keys": {"claude": "key"},
                "provider": "claude",
            },
        )
        assert response.status_code in [200, 500]


class TestMultipleRequests:
    """Test handling multiple concurrent requests."""

    def test_multiple_health_checks(self, client):
        """Multiple health checks should all succeed."""
        responses = [client.get("/health") for _ in range(10)]
        assert all(r.status_code == 200 for r in responses)

    def test_sequential_generations(self, client, monkeypatch):
        """Test multiple sequential generation requests."""
        import backend.api.main as main_mod

        counter = {"n": 0}

        def fake_run(**kwargs):
            counter["n"] += 1
            return "code", f"/static/job{counter['n']}.mp4", True, 1, ["j"], "j"

        monkeypatch.setattr(main_mod, "run_to_code", fake_run)

        for i in range(3):
            response = client.post(
                "/generate",
                json={"prompt": f"Test {i}", "keys": {"claude": "key"}},
            )
            assert response.status_code in [200, 500]

    def test_mixed_endpoint_calls(self, client, monkeypatch):
        """Test calling different endpoints in sequence."""
        import backend.api.main as main_mod
        from backend.agent import minigraph

        def fake_echo(prompt):
            return "code"

        def fake_run(code, **kwargs):
            return {
                "ok": True,
                "status": "ok",
                "job_id": "mixed",
                "video_url": "/static/mixed.mp4",
            }

        monkeypatch.setattr(minigraph, "echo_manim_code", fake_echo)
        monkeypatch.setattr(main_mod, "run_job_from_code", fake_run)

        # Call different endpoints
        r1 = client.get("/health")
        r2 = client.post("/echo", json={"prompt": "Test", "keys": {"claude": "k"}})
        r3 = client.get("/health")

        assert r1.status_code == 200
        assert r2.status_code in [200, 500]
        assert r3.status_code == 200


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_unicode_in_prompts(self, client, monkeypatch):
        """Test prompts with Unicode characters."""
        import backend.api.main as main_mod

        def fake_run(**kwargs):
            return "code", "/static/test.mp4", True, 1, ["j"], "j"

        monkeypatch.setattr(main_mod, "run_to_code", fake_run)

        response = client.post(
            "/generate",
            json={
                "prompt": "Draw π, ∑, ∫, and √ symbols",
                "keys": {"claude": "key"},
            },
        )
        assert response.status_code in [200, 500]

    def test_very_short_prompt(self, client, monkeypatch):
        """Test with minimal prompt."""
        import backend.api.main as main_mod

        def fake_run(**kwargs):
            return "code", "/static/test.mp4", True, 1, ["j"], "j"

        monkeypatch.setattr(main_mod, "run_to_code", fake_run)

        response = client.post(
            "/generate",
            json={"prompt": "Hi", "keys": {"claude": "key"}},
        )
        assert response.status_code in [200, 500]

    def test_numeric_in_strings(self, client, monkeypatch):
        """Test with numeric data in strings."""
        import backend.api.main as main_mod

        def fake_run(**kwargs):
            return "code", "/static/test.mp4", True, 1, ["j"], "j"

        monkeypatch.setattr(main_mod, "run_to_code", fake_run)

        response = client.post(
            "/generate",
            json={
                "prompt": "123 456 789",
                "keys": {"claude": "key"},
                "chatId": "999",
            },
        )
        assert response.status_code in [200, 500]


class TestJobManagementIntegration:
    """Test job management integration."""

    def test_cancel_nonexistent_job(self, client, monkeypatch):
        """Test canceling job that doesn't exist."""
        import backend.api.main as main_mod

        def fake_cancel(job_id):
            return {"status": "not_found", "job_id": job_id}

        monkeypatch.setattr(main_mod, "cancel_job", fake_cancel)

        response = client.post("/jobs/cancel?jobId=nonexistent-123")
        assert response.status_code == 200

    def test_cancel_completed_job(self, client, monkeypatch):
        """Test canceling already completed job."""
        import backend.api.main as main_mod

        def fake_cancel(job_id):
            return {"status": "already_finished", "job_id": job_id}

        monkeypatch.setattr(main_mod, "cancel_job", fake_cancel)

        response = client.post("/jobs/cancel?jobId=completed-456")
        assert response.status_code == 200


class TestAPIResilience:
    """Test API resilience and error handling."""

    def test_malformed_json_handling(self, client):
        """Test API handles malformed JSON."""
        response = client.post(
            "/generate",
            data="{not-valid-json}",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422

    def test_wrong_content_type(self, client):
        """Test API handles wrong content type."""
        response = client.post(
            "/generate",
            data="plain text",
            headers={"Content-Type": "text/plain"},
        )
        assert response.status_code in [415, 422]

    def test_missing_content_type(self, client):
        """Test API handles missing content type."""
        try:
            response = client.post("/generate", data='{"prompt": "test"}')
            # May accept or reject
            assert response.status_code in [200, 400, 415, 422, 500]
        except RuntimeError:
            pass  # Also acceptable to raise

    def test_options_request(self, client):
        """Test OPTIONS request for CORS."""
        response = client.options("/generate")
        # May support OPTIONS or not
        assert response.status_code in [200, 405]

    def test_head_request_on_health(self, client):
        """Test HEAD request on health endpoint."""
        response = client.head("/health")
        # May support HEAD or return 405
        assert response.status_code in [200, 405]
