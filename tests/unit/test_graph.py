"""Unit tests for agent graph modules."""

from unittest.mock import MagicMock, patch

import pytest


class TestTimedNode:
    """Test the _timed_node wrapper function."""

    def test_timed_node_records_duration(self):
        """Should record execution duration in timings."""
        from backend.agent.graph import _timed_node

        def sample_node(state):
            return {"result": "done", "timings": []}

        wrapped = _timed_node("test_node", sample_node)
        result = wrapped({})

        assert "timings" in result
        assert len(result["timings"]) == 1
        assert result["timings"][0]["step"] == "test_node"
        assert "duration_s" in result["timings"][0]
        assert result["timings"][0]["duration_s"] >= 0

    def test_timed_node_preserves_existing_timings(self):
        """Should append to existing timings."""
        from backend.agent.graph import _timed_node

        def sample_node(state):
            return {"timings": [{"step": "previous", "duration_s": 1.0}]}

        wrapped = _timed_node("new_node", sample_node)
        result = wrapped({})

        assert len(result["timings"]) == 2
        assert result["timings"][0]["step"] == "previous"
        assert result["timings"][1]["step"] == "new_node"

    def test_timed_node_handles_none_return(self):
        """Should handle None return from node."""
        from backend.agent.graph import _timed_node

        def bad_node(state):
            return None

        wrapped = _timed_node("bad", bad_node)
        result = wrapped({})

        # Should return None without crashing
        assert result is None

    def test_timed_node_records_tries(self):
        """Should record tries count in timing entry."""
        from backend.agent.graph import _timed_node

        def node_with_tries(state):
            return {"tries": 3, "timings": []}

        wrapped = _timed_node("retry_node", node_with_tries)
        result = wrapped({})

        assert result["timings"][0]["tries"] == 3

    def test_timed_node_uses_state_tries_if_not_in_result(self):
        """Should use state tries if not in result."""
        from backend.agent.graph import _timed_node

        def simple_node(state):
            return {"timings": []}

        wrapped = _timed_node("simple", simple_node)
        result = wrapped({"tries": 5})

        assert result["timings"][0]["tries"] == 5


class TestRouteAfterRender:
    """Test the _route_after_render function."""

    def test_route_ok_when_render_ok_true(self):
        """Should return 'ok' when render_ok is True."""
        from backend.agent.graph import _route_after_render

        result = _route_after_render({"render_ok": True})
        assert result == "ok"

    def test_route_need_fix_when_render_ok_false(self):
        """Should return 'need_fix' when render_ok is False."""
        from backend.agent.graph import _route_after_render

        result = _route_after_render({"render_ok": False})
        assert result == "need_fix"

    def test_route_need_fix_when_render_ok_missing(self):
        """Should return 'need_fix' when render_ok is missing."""
        from backend.agent.graph import _route_after_render

        result = _route_after_render({})
        assert result == "need_fix"


class TestRouteAfterLogFailure:
    """Test the _route_after_log_failure function."""

    def test_retry_when_tries_less_than_max(self):
        """Should return 'retry' when tries < max_tries."""
        from backend.agent.graph import _route_after_log_failure

        result = _route_after_log_failure({"tries": 1, "max_tries": 3})
        assert result == "retry"

    def test_give_up_when_tries_equals_max(self):
        """Should return 'give_up' when tries >= max_tries."""
        from backend.agent.graph import _route_after_log_failure

        result = _route_after_log_failure({"tries": 3, "max_tries": 3})
        assert result == "give_up"

    def test_give_up_when_tries_exceeds_max(self):
        """Should return 'give_up' when tries > max_tries."""
        from backend.agent.graph import _route_after_log_failure

        result = _route_after_log_failure({"tries": 5, "max_tries": 3})
        assert result == "give_up"

    def test_default_max_tries(self):
        """Should use default max_tries of 2 if not specified."""
        from backend.agent.graph import _route_after_log_failure

        result = _route_after_log_failure({"tries": 1})
        assert result == "retry"

        result = _route_after_log_failure({"tries": 2})
        assert result == "give_up"


class TestBuildGraph:
    """Test the build_graph function."""

    def test_build_graph_returns_compiled_graph(self):
        """Should return a compiled LangGraph."""
        from backend.agent.graph import build_graph

        graph = build_graph()
        assert graph is not None
        # Should have invoke method
        assert hasattr(graph, "invoke")


class TestRunToCode:
    """Test the run_to_code function."""

    @patch("backend.agent.graph.build_graph")
    def test_run_to_code_returns_tuple(self, mock_build):
        """Should return 6-tuple with expected values."""
        from backend.agent.graph import run_to_code

        mock_app = MagicMock()
        mock_app.invoke.return_value = {
            "manim_code": "class GeneratedScene:\n    pass",
            "video_url": "/static/video.mp4",
            "render_ok": True,
            "tries": 1,
            "attempt_job_ids": ["job1"],
            "succeeded_job_id": "job1",
            "timings": [],
            "provider": "claude",
            "model": "claude-3",
            "compile_log": "",
        }
        mock_build.return_value = mock_app

        result = run_to_code("Test prompt")

        assert len(result) == 6
        code, video_url, render_ok, tries, job_ids, succeeded_id = result
        assert code == "class GeneratedScene:\n    pass"
        assert video_url == "/static/video.mp4"
        assert render_ok is True
        assert tries == 1
        assert job_ids == ["job1"]
        assert succeeded_id == "job1"

    @patch("backend.agent.graph.build_graph")
    def test_run_to_code_with_provider_keys(self, mock_build):
        """Should pass provider_keys to initial state."""
        from backend.agent.graph import run_to_code

        mock_app = MagicMock()
        mock_app.invoke.return_value = {
            "manim_code": "code",
            "render_ok": True,
            "timings": [],
        }
        mock_build.return_value = mock_app

        run_to_code("prompt", provider_keys={"claude": "key123"})

        call_args = mock_app.invoke.call_args[0][0]
        assert call_args["provider_keys"] == {"claude": "key123"}

    @patch("backend.agent.graph.build_graph")
    def test_run_to_code_with_provider(self, mock_build):
        """Should pass provider to initial state."""
        from backend.agent.graph import run_to_code

        mock_app = MagicMock()
        mock_app.invoke.return_value = {
            "manim_code": "code",
            "render_ok": True,
            "timings": [],
        }
        mock_build.return_value = mock_app

        run_to_code("prompt", provider="gemini")

        call_args = mock_app.invoke.call_args[0][0]
        assert call_args["provider"] == "gemini"

    @patch("backend.agent.graph.build_graph")
    def test_run_to_code_with_model(self, mock_build):
        """Should pass model to initial state."""
        from backend.agent.graph import run_to_code

        mock_app = MagicMock()
        mock_app.invoke.return_value = {
            "manim_code": "code",
            "render_ok": True,
            "timings": [],
        }
        mock_build.return_value = mock_app

        run_to_code("prompt", model="claude-3-opus")

        call_args = mock_app.invoke.call_args[0][0]
        assert call_args["model"] == "claude-3-opus"

    @patch("backend.agent.graph.build_graph")
    def test_run_to_code_raises_on_no_code(self, mock_build):
        """Should raise RuntimeError when no manim_code produced."""
        from backend.agent.graph import run_to_code

        mock_app = MagicMock()
        mock_app.invoke.return_value = {
            "manim_code": None,
            "compile_log": "Some error",
        }
        mock_build.return_value = mock_app

        with pytest.raises(RuntimeError) as exc_info:
            run_to_code("prompt")

        assert "no 'manim_code'" in str(exc_info.value)

    @patch("backend.agent.graph.build_graph")
    def test_run_to_code_handles_failed_render(self, mock_build):
        """Should handle failed render gracefully."""
        from backend.agent.graph import run_to_code

        mock_app = MagicMock()
        mock_app.invoke.return_value = {
            "manim_code": "code",
            "render_ok": False,
            "video_url": None,
            "tries": 3,
            "attempt_job_ids": ["j1", "j2", "j3"],
            "succeeded_job_id": None,
            "timings": [],
        }
        mock_build.return_value = mock_app

        code, video_url, render_ok, tries, job_ids, succeeded_id = run_to_code("prompt")

        assert render_ok is False
        assert video_url is None
        assert succeeded_id is None


class TestGraphWoRagRetry:
    """Test the graph_wo_rag_retry module."""

    def test_build_graph_returns_compiled_graph(self):
        """Should return a compiled LangGraph."""
        from backend.agent.graph_wo_rag_retry import build_graph

        graph = build_graph()
        assert graph is not None
        assert hasattr(graph, "invoke")

    @patch("backend.agent.graph_wo_rag_retry.draft_code_node")
    def test_run_to_code_returns_string(self, mock_draft):
        """Should return just the code string."""
        from backend.agent.graph_wo_rag_retry import run_to_code

        mock_draft.return_value = {"manim_code": "generated code"}

        result = run_to_code("prompt", provider_keys={"claude": "key"})

        assert result == "generated code"

    @patch("backend.agent.graph_wo_rag_retry.draft_code_node")
    def test_run_to_code_with_provider(self, mock_draft):
        """Should accept provider parameter."""
        from backend.agent.graph_wo_rag_retry import run_to_code

        mock_draft.return_value = {"manim_code": "code"}

        result = run_to_code("prompt", provider="gemini")
        assert result == "code"

    @patch("backend.agent.graph_wo_rag_retry.draft_code_node")
    def test_run_to_code_with_model(self, mock_draft):
        """Should accept model parameter."""
        from backend.agent.graph_wo_rag_retry import run_to_code

        mock_draft.return_value = {"manim_code": "code"}

        result = run_to_code("prompt", model="custom-model")
        assert result == "code"

    @patch("backend.agent.graph_wo_rag_retry.draft_code_node")
    def test_run_to_code_raises_on_no_code(self, mock_draft):
        """Should raise RuntimeError when no code produced."""
        from backend.agent.graph_wo_rag_retry import run_to_code

        mock_draft.return_value = {"manim_code": None, "compile_log": "error"}

        with pytest.raises(RuntimeError) as exc_info:
            run_to_code("prompt")

        assert "no 'manim_code'" in str(exc_info.value)
