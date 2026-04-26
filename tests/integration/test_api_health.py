"""Integration tests for health and basic endpoints."""

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


class TestHealthEndpoint:
    """Test /health endpoint."""

    def test_health_returns_ok(self, client):
        """Health endpoint should return ok status."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data == {"ok": True}

    def test_health_no_auth_required(self, client):
        """Health endpoint should not require authentication."""
        # Should work without any headers
        response = client.get("/health")
        assert response.status_code == 200


class TestEchoEndpoint:
    """Test /echo endpoint."""

    def test_echo_basic_prompt(self, client, monkeypatch):
        """Echo endpoint should process simple prompt."""
        # Mock the echo and runner functions
        import backend.api.main as main_mod
        from backend.agent import minigraph

        def fake_echo(prompt):
            return f"# Generated code for: {prompt}"

        def fake_runner(code, **kwargs):
            return {
                "ok": True,
                "status": "ok",
                "job_id": "test123",
                "video_url": "/static/test.mp4",
            }

        monkeypatch.setattr(minigraph, "echo_manim_code", fake_echo)
        # Patch where it's used (in main.py), not where it's defined
        monkeypatch.setattr(main_mod, "run_job_from_code", fake_runner)

        response = client.post(
            "/echo",
            json={
                "prompt": "Draw a circle",
                "keys": {"claude": "test-key"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "video_url" in data

    def test_echo_requires_prompt(self, client):
        """Echo endpoint should require prompt field."""
        response = client.post("/echo", json={"keys": {}})
        # this would be a validation error response
        assert response.status_code == 422


class TestJobsCancelEndpoint:
    """Test /jobs/cancel endpoint."""

    def test_cancel_job_missing_param(self, client):
        """Cancel without jobId should fail."""
        response = client.post("/jobs/cancel")
        # this would mean missing a required query parameter
        assert response.status_code == 422

    def test_cancel_job_with_id(self, client, monkeypatch):
        """Cancel job with valid ID."""
        import backend.api.main as main_mod

        def fake_cancel(job_id):
            return {"ok": True, "job_id": job_id, "cancelled": True}

        # Patch where it's used (in main.py), not where it's defined
        monkeypatch.setattr(main_mod, "cancel_job", fake_cancel)

        response = client.post("/jobs/cancel?jobId=test123")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
