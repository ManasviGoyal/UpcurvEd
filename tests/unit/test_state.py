"""Unit tests for agent state management."""

from backend.agent.state import AgentState, Provider


class TestAgentState:
    """Test AgentState TypedDict structure and usage."""

    def test_basic_state_creation(self):
        """Create basic state with required fields."""
        state: AgentState = {
            "user_prompt": "Test prompt",
            "provider_keys": {"claude": "test-key"},
            "provider": "claude",
        }
        assert state["user_prompt"] == "Test prompt"
        assert state["provider"] == "claude"
        assert state["provider_keys"]["claude"] == "test-key"

    def test_state_with_all_fields(self):
        """Create state with all fields populated."""
        state: AgentState = {
            "user_prompt": "Draw a circle",
            "provider_keys": {"claude": "key1", "gemini": "key2"},
            "provider": "gemini",
            "model": "gemini-2.5-pro",
            "retrieved_docs": "Some docs",
            "manim_code": "class Scene...",
            "previous_code": "old code",
            "compile_log": "Building...",
            "error_log": "No errors",
            "error_context": "",
            "render_ok": True,
            "video_url": "/static/jobs/123/video.mp4",
            "tries": 1,
            "max_tries": 3,
            "attempt_job_ids": ["job1"],
            "succeeded_job_id": "job1",
            "artifacts": {"key": "value"},
        }
        assert state["user_prompt"] == "Draw a circle"
        assert state["tries"] == 1
        assert state["max_tries"] == 3
        assert state["render_ok"] is True
        assert state["video_url"] == "/static/jobs/123/video.mp4"

    def test_partial_state(self):
        """TypedDict with total=False allows partial states."""
        state: AgentState = {
            "user_prompt": "Test",
        }
        assert "user_prompt" in state
        # Other fields not required
        assert "provider" not in state

    def test_provider_literal(self):
        """Provider should be 'claude' or 'gemini'."""
        state: AgentState = {"provider": "claude"}
        assert state["provider"] in ["claude", "gemini"]

    def test_retry_tracking(self):
        """State tracks retry attempts."""
        state: AgentState = {
            "tries": 0,
            "max_tries": 3,
            "attempt_job_ids": [],
        }
        # simulate the retry
        state["tries"] = state.get("tries", 0) + 1
        state["attempt_job_ids"] = state.get("attempt_job_ids", []) + ["job1"]
        assert state["tries"] == 1
        assert "job1" in state["attempt_job_ids"]

    def test_render_success_state(self):
        """State after successful render."""
        state: AgentState = {
            "render_ok": True,
            "video_url": "/static/jobs/abc/video.mp4",
            "succeeded_job_id": "abc",
        }
        assert state["render_ok"] is True
        assert state["video_url"] is not None
        assert state["succeeded_job_id"] == "abc"

    def test_render_failure_state(self):
        """State after failed render with error logs."""
        state: AgentState = {
            "render_ok": False,
            "error_log": "ModuleNotFoundError: No module named 'manim'",
            "error_context": "Error: Module not found",
            "tries": 1,
        }
        assert state["render_ok"] is False
        assert "ModuleNotFoundError" in state["error_log"]
        assert state["tries"] == 1


class TestProviderType:
    """Test Provider literal type."""

    def test_valid_providers(self):
        """Valid provider values."""
        claude: Provider = "claude"
        gemini: Provider = "gemini"
        assert claude == "claude"
        assert gemini == "gemini"

    def test_provider_list(self):
        """Test provider in list."""
        providers = ["claude", "gemini"]
        for p in providers:
            assert p in ["claude", "gemini"]
