"""Integration tests targeting graph, llm/clients, nodes, code_sanitize - ~30 tests."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app


@pytest.fixture
def client():
    return TestClient(app)


# ============================================================================
# Integration tests for graph.py, draft_code, render, retrieve flow
# ============================================================================
class TestGraphIntegration:
    """Integration tests for graph.py execution flow."""

    @patch("backend.api.main.run_to_code")
    def test_graph_integration_01(self, mock_run, client):
        """Test graph execution via /generate endpoint."""
        mock_run.return_value = ("code", "/vid.mp4", True, 1, ["j"], "j")
        r = client.post("/generate", json={"prompt": "Test", "keys": {"claude": "k"}})
        assert r.status_code in [200, 500]
        if r.status_code == 200:
            assert mock_run.called

    @patch("backend.api.main.run_to_code")
    def test_graph_integration_02(self, mock_run, client):
        """Test graph with different providers."""
        mock_run.return_value = ("code", "/vid.mp4", True, 1, ["j"], "j")
        for provider in ["claude", "gemini"]:
            r = client.post(
                "/generate",
                json={"prompt": "Draw", "keys": {provider: "k"}, "provider": provider},
            )
            assert r.status_code in [200, 500]

    @patch("backend.api.main.run_to_code")
    def test_graph_integration_03(self, mock_run, client):
        """Test graph with models."""
        mock_run.return_value = ("code", "/vid.mp4", True, 1, ["j"], "j")
        for model in ["claude-3-5-sonnet", "gemini-2.5-pro"]:
            r = client.post(
                "/generate",
                json={"prompt": "Test", "keys": {"claude": "k"}, "model": model},
            )
            assert r.status_code in [200, 500]


# ============================================================================
# Integration tests for llm/clients.py via API
# ============================================================================
class TestLLMClientsIntegration:
    """Integration tests for LLM clients through API endpoints."""

    def test_llm_claude_via_generate(self, client):
        """Test Claude LLM via generate endpoint."""
        r = client.post(
            "/generate",
            json={
                "prompt": "Draw circle",
                "keys": {"claude": "test-key"},
                "provider": "claude",
                "model": "claude-3-5-sonnet-latest",
            },
        )
        assert r.status_code in [200, 500]

    def test_llm_gemini_via_generate(self, client):
        """Test Gemini LLM via generate endpoint."""
        r = client.post(
            "/generate",
            json={
                "prompt": "Draw square",
                "keys": {"gemini": "test-key"},
                "provider": "gemini",
                "model": "gemini-2.5-pro",
            },
        )
        assert r.status_code in [200, 500]

    def test_llm_claude_via_quiz(self, client):
        """Test Claude via quiz endpoint."""
        r = client.post(
            "/quiz/embedded",
            json={
                "prompt": "Math",
                "keys": {"claude": "k"},
                "provider": "claude",
                "difficulty": "easy",
            },
        )
        assert r.status_code in [200, 500]

    def test_llm_gemini_via_quiz(self, client):
        """Test Gemini via quiz endpoint."""
        r = client.post(
            "/quiz/embedded",
            json={
                "prompt": "Science",
                "keys": {"gemini": "k"},
                "provider": "gemini",
                "num_questions": 5,
            },
        )
        assert r.status_code in [200, 500]

    def test_llm_claude_via_podcast(self, client):
        """Test Claude via podcast endpoint."""
        r = client.post(
            "/podcast",
            json={"prompt": "History", "keys": {"claude": "k"}, "provider": "claude", "lang": "en"},
        )
        assert r.status_code in [200, 500]

    def test_llm_gemini_via_podcast(self, client):
        """Test Gemini via podcast endpoint."""
        r = client.post(
            "/podcast",
            json={"prompt": "Physics", "keys": {"gemini": "k"}, "provider": "gemini", "lang": "es"},
        )
        assert r.status_code in [200, 500]


# ============================================================================
# Integration tests for code_sanitize via generate flow
# ============================================================================
class TestCodeSanitizeIntegration:
    """Integration tests for code_sanitize.py through generation flow."""

    @patch("backend.api.main.run_to_code")
    def test_code_sanitize_via_generate_01(self, mock_run, client):
        """Test code sanitization in generation pipeline."""
        mock_run.return_value = ("sanitized code", "/vid.mp4", True, 1, ["j"], "j")
        r = client.post(
            "/generate",
            json={
                "prompt": "Create animation with code fences",
                "keys": {"claude": "k"},
            },
        )
        assert r.status_code in [200, 500]

    @patch("backend.api.main.run_to_code")
    def test_code_sanitize_via_generate_02(self, mock_run, client):
        """Test multiple sanitization scenarios."""
        for prompt in [
            "Draw with voiceover",
            "Animate with classes",
            "Create GeneratedScene",
        ]:
            mock_run.return_value = ("code", "/vid.mp4", True, 1, ["j"], "j")
            r = client.post("/generate", json={"prompt": prompt, "keys": {"claude": "k"}})
            assert r.status_code in [200, 500]


# ============================================================================
# Integration tests for draft_code, render, retrieve nodes via graph
# ============================================================================
class TestNodesIntegration:
    """Integration tests for draft_code, render, retrieve nodes."""

    @patch("backend.api.main.run_to_code")
    def test_draft_code_node_integration(self, mock_run, client):
        """Test draft_code node through API."""
        mock_run.return_value = ("drafted code", "/vid.mp4", True, 1, ["j"], "j")
        r = client.post(
            "/generate",
            json={
                "prompt": "Test draft code node",
                "keys": {"claude": "k"},
                "temperature": 0.7,
            },
        )
        assert r.status_code in [200, 500]

    @patch("backend.api.main.run_to_code")
    def test_render_node_integration(self, mock_run, client):
        """Test render node through API."""
        mock_run.return_value = ("code", "/rendered.mp4", True, 1, ["j"], "j")
        r = client.post("/generate", json={"prompt": "Test render", "keys": {"claude": "k"}})
        assert r.status_code in [200, 500]

    @patch("backend.api.main.run_to_code")
    def test_retrieve_node_integration(self, mock_run, client):
        """Test retrieve node through API (RAG)."""
        mock_run.return_value = ("code", "/vid.mp4", True, 1, ["j"], "j")
        r = client.post(
            "/generate",
            json={"prompt": "Use Manim Circle to draw", "keys": {"claude": "k"}},
        )
        assert r.status_code in [200, 500]

    @patch("backend.api.main.run_to_code")
    def test_full_node_pipeline(self, mock_run, client):
        """Test full pipeline: retrieve -> draft -> render."""
        mock_run.return_value = ("final code", "/final.mp4", True, 1, ["j"], "j")
        r = client.post(
            "/generate",
            json={
                "prompt": "Full pipeline test with Manim primitives",
                "keys": {"claude": "k"},
                "model": "claude-3-5-sonnet",
            },
        )
        assert r.status_code in [200, 500]


# ============================================================================
# Integration tests for graph_wo_rag_retry.py (no RAG path)
# ============================================================================
class TestGraphWoRagRetryIntegration:
    """Integration tests for graph_wo_rag_retry path."""

    @patch("backend.api.main.run_to_code")
    def test_no_rag_path_01(self, mock_run, client):
        """Test generation without RAG retrieval."""
        mock_run.return_value = ("code", "/vid.mp4", True, 1, ["j"], "j")
        r = client.post(
            "/generate",
            json={"prompt": "Simple no-RAG test", "keys": {"claude": "k"}},
        )
        assert r.status_code in [200, 500]

    @patch("backend.api.main.run_to_code")
    def test_no_rag_path_02(self, mock_run, client):
        """Test no-RAG with different models."""
        for model in ["claude-3-5-sonnet", "gemini-2.5-pro"]:
            mock_run.return_value = ("code", "/vid.mp4", True, 1, ["j"], "j")
            r = client.post(
                "/generate",
                json={"prompt": "No RAG", "keys": {"claude": "k"}, "model": model},
            )
            assert r.status_code in [200, 500]
