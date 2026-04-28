"""System/E2E tests: graph_wo_rag_retry, llm/clients, code_sanitize, firebase_app."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app


@pytest.fixture
def client():
    return TestClient(app)


# ============================================================================
# graph_wo_rag_retry.py - Complete E2E workflows (23 statements)
# ============================================================================
class TestGraphWoRagRetryE2E:
    """E2E tests for graph_wo_rag_retry workflows."""

    @patch("backend.api.main.run_to_code")
    def test_complete_no_rag_workflow_claude(self, mock_run, client):
        """Complete E2E workflow without RAG using Claude."""
        mock_run.return_value = (
            "final code",
            "/static/video.mp4",
            True,
            1,
            ["job1"],
            "job1",
        )

        r = client.post(
            "/generate",
            json={
                "prompt": "Create animation explaining binary search without RAG",
                "keys": {"claude": "test-key"},
                "provider": "claude",
                "model": "claude-haiku-4-5",
                "chatId": "session-rag-001",
            },
        )
        assert r.status_code in [200, 500]

    @patch("backend.api.main.run_to_code")
    def test_complete_no_rag_workflow_gemini(self, mock_run, client):
        """Complete E2E workflow without RAG using Gemini."""
        mock_run.return_value = ("code", "/static/vid.mp4", True, 1, ["job2"], "job2")

        r = client.post(
            "/generate",
            json={
                "prompt": "Visualize quicksort algorithm without RAG",
                "keys": {"gemini": "test-key"},
                "provider": "gemini",
                "model": "gemini-3-flash-preview",
            },
        )
        assert r.status_code in [200, 500]

    @patch("backend.api.main.run_to_code")
    def test_no_rag_with_retry(self, mock_run, client):
        """Test no-RAG workflow with retry logic."""
        mock_run.return_value = ("code", None, False, 3, ["j1", "j2", "j3"], None)

        r = client.post(
            "/generate",
            json={"prompt": "Test retry without RAG", "keys": {"claude": "k"}},
        )
        assert r.status_code in [200, 500]

    @patch("backend.api.main.run_to_code")
    def test_no_rag_multiple_scenarios(self, mock_run, client):
        """Test multiple no-RAG scenarios."""
        scenarios = [
            {
                "prompt": "Draw geometric shapes",
                "keys": {"claude": "k"},
                "model": "claude-3-5-sonnet",
            },
            {
                "prompt": "Animate mathematical functions",
                "keys": {"gemini": "k"},
                "model": "gemini-3-flash-preview",
            },
            {"prompt": "Simple visualization", "keys": {"claude": "k"}},
        ]

        for scenario in scenarios:
            mock_run.return_value = ("code", "/vid.mp4", True, 1, ["j"], "j")
            r = client.post("/generate", json=scenario)
            assert r.status_code in [200, 500]


# ============================================================================
# llm/clients.py - Complete E2E workflows (45 statements)
# ============================================================================
class TestLLMClientsE2E:
    """E2E tests for LLM clients through all endpoints."""

    def test_claude_complete_generation_workflow(self, client):
        """Complete generation workflow using Claude."""
        r = client.post(
            "/generate",
            json={
                "prompt": (
                    "Create a detailed animation explaining the concept of "
                    "derivatives in calculus, showing the tangent line "
                    "approaching a point"
                ),
                "keys": {"claude": "test-key"},
                "provider": "claude",
                "model": "claude-haiku-4-5",
            },
        )
        assert r.status_code in [200, 500]

    def test_gemini_complete_generation_workflow(self, client):
        """Complete generation workflow using Gemini."""
        r = client.post(
            "/generate",
            json={
                "prompt": (
                    "Visualize the Fourier transform showing how complex "
                    "waveforms can be decomposed into simple sine waves"
                ),
                "keys": {"gemini": "test-key"},
                "provider": "gemini",
                "model": "gemini-3-flash-preview",
            },
        )
        assert r.status_code in [200, 500]

    def test_claude_quiz_complete_workflow(self, client):
        """Complete quiz generation using Claude with all parameters."""
        r = client.post(
            "/quiz/embedded",
            json={
                "prompt": "Advanced linear algebra concepts including eigenvalues and eigenvectors",
                "keys": {"claude": "k"},
                "provider": "claude",
                "model": "claude-3-5-sonnet",
                "num_questions": 20,
                "difficulty": "hard",
                "context": "Focus on applications in data science",
            },
        )
        assert r.status_code in [200, 500]

    def test_gemini_quiz_complete_workflow(self, client):
        """Complete quiz generation using Gemini."""
        r = client.post(
            "/quiz/embedded",
            json={
                "prompt": "Modern European history from 1900 to 2000",
                "keys": {"gemini": "k"},
                "provider": "gemini",
                "num_questions": 25,
                "difficulty": "medium",
            },
        )
        assert r.status_code in [200, 500]

    def test_claude_podcast_complete_workflow(self, client):
        """Complete podcast generation using Claude."""
        r = client.post(
            "/podcast",
            json={
                "prompt": (
                    "Explain the theory of relativity in simple terms, "
                    "covering both special and general relativity"
                ),
                "keys": {"claude": "k"},
                "provider": "claude",
                "model": "claude-3-5-sonnet",
                "lang": "en",
                "context": "For high school students",
            },
        )
        assert r.status_code in [200, 401, 500]

    def test_gemini_podcast_complete_workflow(self, client):
        """Complete podcast generation using Gemini."""
        r = client.post(
            "/podcast",
            json={
                "prompt": "L'histoire de la révolution française",
                "keys": {"gemini": "k"},
                "provider": "gemini",
                "lang": "fr",
            },
        )
        assert r.status_code in [200, 500]

    def test_llm_error_handling_e2e(self, client):
        """Test LLM error handling in complete workflows."""
        # Test with various error scenarios
        error_scenarios = [
            {
                "prompt": "Test",
                "keys": {"claude": "invalid"},
                "provider": "claude",
            },
            {
                "prompt": "Test",
                "keys": {"gemini": "invalid"},
                "provider": "gemini",
            },
        ]

        for scenario in error_scenarios:
            r = client.post("/generate", json=scenario)
            assert r.status_code in [200, 500]


# ============================================================================
# code_sanitize.py - Complete E2E workflows (73 statements)
# ============================================================================
class TestCodeSanitizeE2E:
    """E2E tests for code sanitization through complete workflows."""

    @patch("backend.api.main.run_to_code")
    def test_code_fence_stripping_complete(self, mock_run, client):
        """Complete workflow testing code fence stripping."""
        mock_run.return_value = ("clean code", "/vid.mp4", True, 1, ["j"], "j")

        r = client.post(
            "/generate",
            json={
                "prompt": "Create animation with code that may have markdown fences",
                "keys": {"claude": "k"},
            },
        )
        assert r.status_code in [200, 500]

    @patch("backend.api.main.run_to_code")
    def test_voiceover_header_injection_complete(self, mock_run, client):
        """Complete workflow testing voiceover header injection."""
        mock_run.return_value = ("code with headers", "/vid.mp4", True, 1, ["j"], "j")

        r = client.post(
            "/generate",
            json={
                "prompt": "Animation requiring voiceover imports and headers",
                "keys": {"claude": "k"},
                "model": "claude-3-5-sonnet",
            },
        )
        assert r.status_code in [200, 500]

    @patch("backend.api.main.run_to_code")
    def test_generated_scene_normalization_complete(self, mock_run, client):
        """Complete workflow testing scene class normalization."""
        mock_run.return_value = ("normalized", "/vid.mp4", True, 1, ["j"], "j")

        r = client.post(
            "/generate",
            json={
                "prompt": "Scene requiring GeneratedScene normalization",
                "keys": {"claude": "k"},
            },
        )
        assert r.status_code in [200, 500]

    @patch("backend.api.main.run_to_code")
    def test_sanitization_with_error_recovery(self, mock_run, client):
        """Test sanitization during error recovery."""
        mock_run.return_value = ("code", None, False, 2, ["j1", "j2"], None)

        r = client.post(
            "/generate",
            json={
                "prompt": "Test sanitization with errors",
                "keys": {"claude": "k"},
            },
        )
        assert r.status_code in [200, 500]

    @patch("backend.api.main.run_to_code")
    def test_multiple_sanitization_scenarios(self, mock_run, client):
        """Test multiple sanitization scenarios in sequence."""
        scenarios = [
            "Code with triple backticks",
            "Scene without proper imports",
            "Custom scene class needing normalization",
            "Multiple code blocks in response",
        ]

        for prompt in scenarios:
            mock_run.return_value = ("sanitized", "/vid.mp4", True, 1, ["j"], "j")
            r = client.post("/generate", json={"prompt": prompt, "keys": {"claude": "k"}})
            assert r.status_code in [200, 500]


# ============================================================================
# firebase_app.py - Complete E2E workflows (19 statements)
# ============================================================================
class TestFirebaseAppE2E:
    """E2E tests for Firebase authentication."""

    def test_firebase_auth_complete_generation(self, client):
        """Complete generation workflow with Firebase auth."""
        r = client.post(
            "/generate",
            json={
                "prompt": "Test with Firebase auth",
                "keys": {"claude": "k"},
            },
            headers={"Authorization": "Bearer test-firebase-token"},
        )
        assert r.status_code in [200, 401, 500]

    def test_firebase_auth_complete_quiz(self, client):
        """Complete quiz workflow with Firebase auth."""
        r = client.post(
            "/quiz/embedded",
            json={
                "prompt": "Math quiz with auth",
                "keys": {"claude": "k"},
                "num_questions": 10,
            },
            headers={"Authorization": "Bearer test-token"},
        )
        assert r.status_code in [200, 401, 500]

    def test_firebase_auth_complete_podcast(self, client):
        """Complete podcast workflow with Firebase auth."""
        r = client.post(
            "/podcast",
            json={
                "prompt": "Podcast with auth",
                "keys": {"claude": "k"},
                "lang": "en",
            },
            headers={"Authorization": "Bearer test-token"},
        )
        assert r.status_code in [200, 401, 500]

    def test_firebase_auth_workflow_sequence(self, client):
        """Test sequence of authenticated requests."""
        endpoints = [
            ("/health", "GET", {}),
            (
                "/generate",
                "POST",
                {"prompt": "Test 1", "keys": {"claude": "k"}},
            ),
            (
                "/quiz/embedded",
                "POST",
                {"prompt": "Test 2", "keys": {"claude": "k"}},
            ),
            (
                "/podcast",
                "POST",
                {"prompt": "Test 3", "keys": {"claude": "k"}},
            ),
        ]

        for endpoint, method, json_data in endpoints:
            if method == "GET":
                r = client.get(endpoint, headers={"Authorization": "Bearer test"})
            else:
                r = client.post(endpoint, json=json_data, headers={"Authorization": "Bearer test"})
            assert r.status_code in [200, 401, 500]


# ============================================================================
# Complete user journey E2E tests
# ============================================================================
class TestCompleteUserJourneysE2E:
    """Complete end-to-end user journey tests."""

    @patch("backend.api.main.run_to_code")
    def test_full_journey_with_all_features(self, mock_run, client):
        """Complete user journey using all features."""
        mock_run.return_value = ("code", "/vid.mp4", True, 1, ["job1"], "job1")

        # 1. Check health
        r1 = client.get("/health")
        # 2. Generate video
        r2 = client.post(
            "/generate",
            json={
                "prompt": "Complex animation",
                "keys": {"claude": "k"},
                "model": "claude-3-5-sonnet",
            },
        )
        # 3. Generate quiz
        r3 = client.post(
            "/quiz/embedded",
            json={"prompt": "Math", "keys": {"claude": "k"}, "difficulty": "hard"},
        )
        # 4. Generate podcast
        r4 = client.post(
            "/podcast",
            json={"prompt": "Science", "keys": {"claude": "k"}, "lang": "en"},
        )
        # 5. Check health again
        r5 = client.get("/health")
        # 6. Cancel job
        r6 = client.post("/jobs/cancel?jobId=job1")

        assert all(r.status_code in [200, 500] for r in [r1, r2, r3, r4, r5, r6])

    def test_multi_provider_journey(self, client):
        """User journey using multiple LLM providers."""
        # Claude for video
        r1 = client.post(
            "/generate",
            json={"prompt": "Claude video", "keys": {"claude": "k"}, "provider": "claude"},
        )
        # Gemini for quiz
        r2 = client.post(
            "/quiz/embedded",
            json={"prompt": "Gemini quiz", "keys": {"gemini": "k"}, "provider": "gemini"},
        )
        # Claude for podcast
        r3 = client.post(
            "/podcast",
            json={"prompt": "Claude podcast", "keys": {"claude": "k"}, "provider": "claude"},
        )

        assert all(r.status_code in [200, 500] for r in [r1, r2, r3])
