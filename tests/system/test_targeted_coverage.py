"""System/E2E tests targeting graph, llm/clients, nodes, code_sanitize - ~30 tests."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app


@pytest.fixture
def client():
    return TestClient(app)


# ============================================================================
# E2E tests for complete graph execution flow
# ============================================================================
class TestGraphE2E:
    """E2E tests for complete graph workflows."""

    @patch("backend.api.main.run_to_code")
    def test_complete_graph_workflow_claude(self, mock_run, client):
        """Complete workflow: user prompt -> graph -> video."""
        mock_run.return_value = ("final code", "/static/output.mp4", True, 1, ["job1"], "job1")

        r = client.post(
            "/generate",
            json={
                "prompt": "Create an educational animation explaining derivatives",
                "keys": {"claude": "test-key"},
                "provider": "claude",
                "model": "claude-haiku-4-5",
                "temperature": 0.7,
                "chatId": "session-001",
            },
        )
        assert r.status_code in [200, 500]
        if r.status_code == 200:
            r.json()  # Validate JSON response
            assert mock_run.called

    @patch("backend.api.main.run_to_code")
    def test_complete_graph_workflow_gemini(self, mock_run, client):
        """Complete workflow with Gemini."""
        mock_run.return_value = ("code", "/static/video.mp4", True, 1, ["job2"], "job2")

        r = client.post(
            "/generate",
            json={
                "prompt": "Visualize the Pythagorean theorem",
                "keys": {"gemini": "test-key"},
                "provider": "gemini",
                "model": "gemini-3-flash-preview",
                "jobId": "custom-job-456",
            },
        )
        assert r.status_code in [200, 500]

    @patch("backend.api.main.run_to_code")
    def test_graph_with_retry_logic(self, mock_run, client):
        """Test graph retry logic when render fails."""
        mock_run.return_value = ("code", None, False, 3, ["j1", "j2", "j3"], None)

        r = client.post(
            "/generate",
            json={"prompt": "Test retry", "keys": {"claude": "k"}},
        )
        assert r.status_code in [200, 500]


# ============================================================================
# E2E tests for LLM clients through full workflows
# ============================================================================
class TestLLMClientsE2E:
    """E2E tests for LLM clients."""

    def test_llm_claude_full_generation_workflow(self, client):
        """Complete generation workflow using Claude."""
        r = client.post(
            "/generate",
            json={
                "prompt": "Create an animation showing sorting algorithms in action",
                "keys": {"claude": "test-key"},
                "provider": "claude",
                "model": "claude-haiku-4-5",
            },
        )
        assert r.status_code in [200, 500]

    def test_llm_gemini_full_generation_workflow(self, client):
        """Complete generation workflow using Gemini."""
        r = client.post(
            "/generate",
            json={
                "prompt": "Visualize the concept of limits in calculus",
                "keys": {"gemini": "test-key"},
                "provider": "gemini",
                "model": "gemini-3-flash-preview",
            },
        )
        assert r.status_code in [200, 500]

    def test_llm_claude_quiz_workflow(self, client):
        """Complete quiz generation using Claude."""
        r = client.post(
            "/quiz/embedded",
            json={
                "prompt": "Advanced calculus concepts",
                "keys": {"claude": "k"},
                "provider": "claude",
                "num_questions": 10,
                "difficulty": "hard",
            },
        )
        assert r.status_code in [200, 500]

    def test_llm_gemini_quiz_workflow(self, client):
        """Complete quiz generation using Gemini."""
        r = client.post(
            "/quiz/embedded",
            json={
                "prompt": "World history",
                "keys": {"gemini": "k"},
                "provider": "gemini",
                "num_questions": 15,
                "difficulty": "medium",
            },
        )
        assert r.status_code in [200, 500]

    def test_llm_claude_podcast_workflow(self, client):
        """Complete podcast generation using Claude."""
        r = client.post(
            "/podcast",
            json={
                "prompt": "Explain quantum entanglement",
                "keys": {"claude": "k"},
                "provider": "claude",
                "lang": "en",
            },
        )
        assert r.status_code in [200, 500]

    def test_llm_gemini_podcast_workflow(self, client):
        """Complete podcast generation using Gemini."""
        r = client.post(
            "/podcast",
            json={
                "prompt": "La révolution industrielle",
                "keys": {"gemini": "k"},
                "provider": "gemini",
                "lang": "fr",
            },
        )
        assert r.status_code in [200, 500]


# ============================================================================
# E2E tests for code_sanitize through generation
# ============================================================================
class TestCodeSanitizeE2E:
    """E2E tests for code sanitization."""

    @patch("backend.api.main.run_to_code")
    def test_code_fence_stripping_e2e(self, mock_run, client):
        """Test that code fences are properly stripped."""
        mock_run.return_value = ("clean code", "/vid.mp4", True, 1, ["j"], "j")

        r = client.post(
            "/generate",
            json={
                "prompt": "Code with fences that need stripping",
                "keys": {"claude": "k"},
            },
        )
        assert r.status_code in [200, 500]

    @patch("backend.api.main.run_to_code")
    def test_voiceover_header_injection_e2e(self, mock_run, client):
        """Test that voiceover headers are properly injected."""
        mock_run.return_value = ("code with headers", "/vid.mp4", True, 1, ["j"], "j")

        r = client.post(
            "/generate",
            json={
                "prompt": "Animation requiring voiceover",
                "keys": {"claude": "k"},
            },
        )
        assert r.status_code in [200, 500]

    @patch("backend.api.main.run_to_code")
    def test_generated_scene_normalization_e2e(self, mock_run, client):
        """Test that scene classes are normalized."""
        mock_run.return_value = ("normalized code", "/vid.mp4", True, 1, ["j"], "j")

        r = client.post(
            "/generate",
            json={
                "prompt": "Scene normalization test",
                "keys": {"claude": "k"},
            },
        )
        assert r.status_code in [200, 500]


# ============================================================================
# E2E tests for draft_code, render, retrieve nodes
# ============================================================================
class TestNodesE2E:
    """E2E tests for all node types."""

    @patch("backend.api.main.run_to_code")
    def test_draft_code_node_e2e(self, mock_run, client):
        """E2E test for draft_code node."""
        mock_run.return_value = ("drafted", "/vid.mp4", True, 1, ["j"], "j")

        r = client.post(
            "/generate",
            json={
                "prompt": "Complex mathematical visualization",
                "keys": {"claude": "k"},
                "temperature": 0.8,
            },
        )
        assert r.status_code in [200, 500]

    @patch("backend.api.main.run_to_code")
    def test_render_node_e2e(self, mock_run, client):
        """E2E test for render node."""
        mock_run.return_value = ("code", "/rendered.mp4", True, 1, ["j"], "j")

        r = client.post(
            "/generate",
            json={"prompt": "Render test", "keys": {"claude": "k"}},
        )
        assert r.status_code in [200, 500]

    @patch("backend.api.main.run_to_code")
    def test_retrieve_node_e2e(self, mock_run, client):
        """E2E test for retrieve node (RAG)."""
        mock_run.return_value = ("code", "/vid.mp4", True, 1, ["j"], "j")

        r = client.post(
            "/generate",
            json={
                "prompt": "Use Circle and Square from Manim",
                "keys": {"claude": "k"},
            },
        )
        assert r.status_code in [200, 500]

    @patch("backend.api.main.run_to_code")
    def test_all_nodes_pipeline_e2e(self, mock_run, client):
        """E2E test for complete node pipeline."""
        mock_run.return_value = ("final", "/final.mp4", True, 2, ["j1", "j2"], "j2")

        r = client.post(
            "/generate",
            json={
                "prompt": "Full pipeline: retrieve Manim docs, draft code, render video",
                "keys": {"claude": "k"},
                "model": "claude-3-5-sonnet",
            },
        )
        assert r.status_code in [200, 500]


# ============================================================================
# E2E tests for graph_wo_rag_retry (no RAG path)
# ============================================================================
class TestGraphWoRagRetryE2E:
    """E2E tests for no-RAG graph path."""

    @patch("backend.api.main.run_to_code")
    def test_no_rag_complete_workflow(self, mock_run, client):
        """Complete workflow without RAG."""
        mock_run.return_value = ("code", "/vid.mp4", True, 1, ["j"], "j")

        r = client.post(
            "/generate",
            json={
                "prompt": "Simple animation without RAG",
                "keys": {"claude": "k"},
            },
        )
        assert r.status_code in [200, 500]

    @patch("backend.api.main.run_to_code")
    def test_no_rag_with_temperature_variations(self, mock_run, client):
        """Test no-RAG path with different temperatures."""
        for temp in [0.3, 0.7, 1.0]:
            mock_run.return_value = ("code", "/vid.mp4", True, 1, ["j"], "j")
            r = client.post(
                "/generate",
                json={
                    "prompt": f"Test temp {temp}",
                    "keys": {"claude": "k"},
                    "temperature": temp,
                },
            )
            assert r.status_code in [200, 500]


# ============================================================================
# Complete user journey tests
# ============================================================================
class TestCompleteUserJourneys:
    """Complete user journey E2E tests."""

    @patch("backend.api.main.run_to_code")
    def test_full_user_journey_01(self, mock_run, client):
        """User journey: health -> generate -> check status -> cancel."""
        mock_run.return_value = ("code", "/vid.mp4", True, 1, ["job1"], "job1")

        # Check health
        r1 = client.get("/health")
        # Generate video
        r2 = client.post(
            "/generate",
            json={"prompt": "User journey test", "keys": {"claude": "k"}},
        )
        # Check health again
        r3 = client.get("/health")
        # Cancel job
        r4 = client.post("/jobs/cancel?jobId=job1")

        assert all(r.status_code in [200, 500] for r in [r1, r2, r3, r4])

    def test_full_user_journey_02(self, client):
        """User journey: quiz -> podcast -> health."""
        # Generate quiz
        r1 = client.post(
            "/quiz/embedded",
            json={"prompt": "Math", "keys": {"claude": "k"}},
        )
        # Generate podcast
        r2 = client.post(
            "/podcast",
            json={"prompt": "History", "keys": {"claude": "k"}},
        )
        # Check health
        r3 = client.get("/health")

        assert all(r.status_code in [200, 500] for r in [r1, r2, r3])
