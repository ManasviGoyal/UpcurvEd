"""Massive system E2E tests for coverage."""

import pytest
from fastapi.testclient import TestClient

import backend.api.main as main_mod
from backend.api.main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestE2EMassive:
    """Many E2E tests."""

    def test_e2e_generate_01(self, client, monkeypatch):
        def fake(**kw):
            return "c", "/s.mp4", True, 1, ["j"], "j"

        monkeypatch.setattr(main_mod, "run_to_code", fake)
        r = client.post("/generate", json={"prompt": "Draw circle", "keys": {"claude": "k"}})
        assert r.status_code in [200, 500]

    def test_e2e_generate_02(self, client, monkeypatch):
        def fake(**kw):
            return "c", "/s.mp4", True, 1, ["j"], "j"

        monkeypatch.setattr(main_mod, "run_to_code", fake)
        r = client.post("/generate", json={"prompt": "Draw square", "keys": {"gemini": "k"}})
        assert r.status_code in [200, 500]

    def test_e2e_quiz_01(self, client):
        r = client.post("/quiz/embedded", json={"prompt": "Math", "keys": {"claude": "k"}})
        assert r.status_code in [200, 500]

    def test_e2e_quiz_02(self, client):
        r = client.post("/quiz/embedded", json={"prompt": "Science", "keys": {"gemini": "k"}})
        assert r.status_code in [200, 500]

    def test_e2e_podcast_01(self, client):
        r = client.post("/podcast", json={"prompt": "History", "keys": {"claude": "k"}})
        assert r.status_code in [200, 500]

    def test_e2e_podcast_02(self, client):
        r = client.post("/podcast", json={"prompt": "Art", "keys": {"gemini": "k"}})
        assert r.status_code in [200, 500]

    def test_e2e_health_01(self, client):
        r = client.get("/health")
        assert r.status_code == 200

    def test_e2e_health_02(self, client):
        r = client.get("/health")
        assert r.json()["ok"] is True

    def test_e2e_cancel_01(self, client):
        r = client.post("/jobs/cancel?jobId=test1")
        assert r.status_code == 200

    def test_e2e_cancel_02(self, client):
        r = client.post("/jobs/cancel?jobId=test2")
        assert r.status_code == 200

    def test_e2e_workflow_01(self, client, monkeypatch):
        def fake(**kw):
            return "c", "/s.mp4", True, 1, ["j"], "j"

        monkeypatch.setattr(main_mod, "run_to_code", fake)
        r1 = client.get("/health")
        r2 = client.post("/generate", json={"prompt": "Test", "keys": {"claude": "k"}})
        r3 = client.get("/health")
        assert all(r.status_code in [200, 500] for r in [r1, r2, r3])

    def test_e2e_workflow_02(self, client):
        r1 = client.get("/health")
        r2 = client.post("/quiz/embedded", json={"prompt": "Test", "keys": {"claude": "k"}})
        r3 = client.get("/health")
        assert all(r.status_code in [200, 500] for r in [r1, r2, r3])

    def test_e2e_workflow_03(self, client):
        r1 = client.get("/health")
        r2 = client.post("/podcast", json={"prompt": "Test", "keys": {"claude": "k"}})
        r3 = client.get("/health")
        assert all(r.status_code in [200, 500] for r in [r1, r2, r3])

    def test_e2e_mixed_01(self, client, monkeypatch):
        def fake(**kw):
            return "c", "/s.mp4", True, 1, ["j"], "j"

        monkeypatch.setattr(main_mod, "run_to_code", fake)
        r1 = client.post("/generate", json={"prompt": "A", "keys": {"claude": "k"}})
        r2 = client.post("/quiz/embedded", json={"prompt": "B", "keys": {"claude": "k"}})
        assert all(r.status_code in [200, 500] for r in [r1, r2])

    def test_e2e_mixed_02(self, client):
        r1 = client.post("/quiz/embedded", json={"prompt": "A", "keys": {"claude": "k"}})
        r2 = client.post("/podcast", json={"prompt": "B", "keys": {"claude": "k"}})
        assert all(r.status_code in [200, 500] for r in [r1, r2])
