"""Comprehensive unit tests targeting ALL missing statement lines specified by user."""

import os
from unittest.mock import MagicMock, patch

import pytest


class TestGraphComprehensive:
    """Comprehensive tests for graph.py - 26 statements."""

    def test_route_after_render_ok(self):
        """Test _route_after_render when render succeeds."""
        from backend.agent.graph import _route_after_render

        state = {"render_ok": True}
        assert _route_after_render(state) == "ok"

    def test_route_after_render_need_fix(self):
        """Test _route_after_render when render fails."""
        from backend.agent.graph import _route_after_render

        state = {"render_ok": False}
        assert _route_after_render(state) == "need_fix"

    def test_route_after_log_failure_retry(self):
        """Test _route_after_log_failure when should retry."""
        from backend.agent.graph import _route_after_log_failure

        state = {"tries": 1, "max_tries": 2}
        assert _route_after_log_failure(state) == "retry"

    def test_route_after_log_failure_give_up(self):
        """Test _route_after_log_failure when should give up."""
        from backend.agent.graph import _route_after_log_failure

        state = {"tries": 2, "max_tries": 2}
        assert _route_after_log_failure(state) == "give_up"

    def test_route_after_log_failure_defaults(self):
        """Test _route_after_log_failure with default values."""
        from backend.agent.graph import _route_after_log_failure

        state = {}
        assert _route_after_log_failure(state) == "retry"

    @patch("backend.agent.graph.StateGraph")
    def test_build_graph_structure(self, mock_state_graph):
        """Test build_graph creates correct structure."""
        from backend.agent.graph import build_graph

        mock_graph = MagicMock()
        mock_state_graph.return_value = mock_graph
        mock_graph.compile.return_value = MagicMock()

        build_graph()

        # Verify nodes were added (draft_code, render, retrieve, log_failure)
        assert mock_graph.add_node.call_count == 4
        # Verify entry point was set
        mock_graph.set_entry_point.assert_called_once()
        # Verify edges were added
        assert mock_graph.add_edge.call_count >= 1
        # Verify conditional edges were added
        assert mock_graph.add_conditional_edges.call_count == 2
        # Verify graph was compiled
        mock_graph.compile.assert_called_once()

    @patch("backend.agent.graph.build_graph")
    def test_run_to_code_basic(self, mock_build_graph):
        """Test run_to_code with basic parameters."""
        from backend.agent.graph import run_to_code

        mock_app = MagicMock()
        mock_build_graph.return_value = mock_app
        mock_app.invoke.return_value = {
            "manim_code": "test code",
            "video_url": "/test.mp4",
            "render_ok": True,
            "tries": 1,
            "attempt_job_ids": ["j1"],
            "succeeded_job_id": "j1",
        }

        result = run_to_code("Draw circle")
        assert result[0] == "test code"
        assert result[1] == "/test.mp4"
        assert result[2] is True

    @patch("backend.agent.graph.build_graph")
    def test_run_to_code_with_provider_keys(self, mock_build_graph):
        """Test run_to_code with provider_keys."""
        from backend.agent.graph import run_to_code

        mock_app = MagicMock()
        mock_build_graph.return_value = mock_app
        mock_app.invoke.return_value = {
            "manim_code": "code",
            "render_ok": True,
        }

        run_to_code("Test", provider_keys={"claude": "key"})
        call_args = mock_app.invoke.call_args[0][0]
        assert "provider_keys" in call_args
        assert call_args["provider_keys"]["claude"] == "key"

    @patch("backend.agent.graph.build_graph")
    def test_run_to_code_with_provider(self, mock_build_graph):
        """Test run_to_code with provider parameter."""
        from backend.agent.graph import run_to_code

        mock_app = MagicMock()
        mock_build_graph.return_value = mock_app
        mock_app.invoke.return_value = {
            "manim_code": "code",
            "render_ok": True,
        }

        run_to_code("Test", provider="gemini")
        call_args = mock_app.invoke.call_args[0][0]
        assert call_args["provider"] == "gemini"

    @patch("backend.agent.graph.build_graph")
    def test_run_to_code_with_model(self, mock_build_graph):
        """Test run_to_code with model parameter."""
        from backend.agent.graph import run_to_code

        mock_app = MagicMock()
        mock_build_graph.return_value = mock_app
        mock_app.invoke.return_value = {
            "manim_code": "code",
            "render_ok": True,
        }

        run_to_code("Test", model="claude-3-5-sonnet")
        call_args = mock_app.invoke.call_args[0][0]
        assert call_args["model"] == "claude-3-5-sonnet"

    @patch("backend.agent.graph.build_graph")
    def test_run_to_code_no_code_error(self, mock_build_graph):
        """Test run_to_code raises error when no code produced."""
        from backend.agent.graph import run_to_code

        mock_app = MagicMock()
        mock_build_graph.return_value = mock_app
        mock_app.invoke.return_value = {}

        with pytest.raises(RuntimeError, match="Graph produced no 'manim_code'"):
            run_to_code("Test")


class TestGraphWoRagRetryComprehensive:
    """Comprehensive tests for graph_wo_rag_retry.py - 18 statements."""

    @patch("backend.agent.graph_wo_rag_retry.StateGraph")
    def test_build_graph_structure(self, mock_state_graph):
        """Test build_graph creates simple structure."""
        from backend.agent.graph_wo_rag_retry import build_graph

        mock_graph = MagicMock()
        mock_state_graph.return_value = mock_graph
        mock_graph.compile.return_value = MagicMock()

        build_graph()

        # Verify single node was added
        mock_graph.add_node.assert_called_once()
        # Verify entry point was set
        mock_graph.set_entry_point.assert_called_once()
        # Verify edge to END was added
        mock_graph.add_edge.assert_called_once()
        # Verify graph was compiled
        mock_graph.compile.assert_called_once()

    @patch("backend.agent.graph_wo_rag_retry.build_graph")
    def test_run_to_code_basic(self, mock_build_graph):
        """Test run_to_code returns code."""
        from backend.agent.graph_wo_rag_retry import run_to_code

        mock_app = MagicMock()
        mock_build_graph.return_value = mock_app
        mock_app.invoke.return_value = {"manim_code": "test code"}

        result = run_to_code("Draw circle")
        assert result == "test code"

    @patch("backend.agent.graph_wo_rag_retry.build_graph")
    def test_run_to_code_with_all_params(self, mock_build_graph):
        """Test run_to_code with all parameters."""
        from backend.agent.graph_wo_rag_retry import run_to_code

        mock_app = MagicMock()
        mock_build_graph.return_value = mock_app
        mock_app.invoke.return_value = {"manim_code": "code"}

        run_to_code(
            "Test",
            provider_keys={"claude": "k"},
            provider="claude",
            model="claude-3",
            max_tries=3,
        )

        call_args = mock_app.invoke.call_args[0][0]
        assert call_args["user_prompt"] == "Test"
        assert call_args["provider_keys"]["claude"] == "k"
        assert call_args["provider"] == "claude"
        assert call_args["model"] == "claude-3"
        assert call_args["max_tries"] == 3

    @patch("backend.agent.graph_wo_rag_retry.build_graph")
    def test_run_to_code_no_code_error(self, mock_build_graph):
        """Test run_to_code raises error when no code."""
        from backend.agent.graph_wo_rag_retry import run_to_code

        mock_app = MagicMock()
        mock_build_graph.return_value = mock_app
        mock_app.invoke.return_value = {}

        with pytest.raises(RuntimeError, match="Graph produced no 'manim_code'"):
            run_to_code("Test")


class TestFirebaseAppComprehensive:
    """Comprehensive tests for firebase_app.py - 19 statements."""

    @patch("backend.firebase_app.firestore.client")
    @patch("backend.firebase_app.firebase_admin.get_app")
    def test_init_firebase_existing_app(self, mock_get_app, mock_firestore_client):
        """Test init_firebase when app already exists."""
        from backend.firebase_app import init_firebase

        mock_app = MagicMock()
        mock_get_app.return_value = mock_app
        mock_db = MagicMock()
        mock_firestore_client.return_value = mock_db

        # Reset global state
        import backend.firebase_app as fb_module

        fb_module._db = None
        fb_module._app = None

        result = init_firebase()
        assert result == mock_db
        mock_get_app.assert_called_once()

    @patch("backend.firebase_app.firestore.client")
    @patch("backend.firebase_app.firebase_admin.initialize_app")
    @patch("backend.firebase_app.firebase_admin.get_app")
    @patch("backend.firebase_app.credentials.ApplicationDefault")
    def test_init_firebase_no_app(
        self, mock_app_default, mock_get_app, mock_init_app, mock_firestore_client
    ):
        """Test init_firebase when no app exists."""
        from backend.firebase_app import init_firebase

        mock_get_app.side_effect = ValueError("No app")
        mock_cred = MagicMock()
        mock_app_default.return_value = mock_cred
        mock_app = MagicMock()
        mock_init_app.return_value = mock_app
        mock_db = MagicMock()
        mock_firestore_client.return_value = mock_db

        # Reset global state
        import backend.firebase_app as fb_module

        fb_module._db = None
        fb_module._app = None

        result = init_firebase()
        assert result == mock_db
        mock_init_app.assert_called()

    @patch("backend.firebase_app.firestore.client")
    @patch("backend.firebase_app.firebase_admin.initialize_app")
    @patch("backend.firebase_app.firebase_admin.get_app")
    @patch("backend.firebase_app.credentials.Certificate")
    @patch("backend.firebase_app.os.path.isfile")
    def test_init_firebase_with_json_creds(
        self,
        mock_isfile,
        mock_certificate,
        mock_get_app,
        mock_init_app,
        mock_firestore_client,
    ):
        """Test init_firebase with JSON credentials."""
        from backend.firebase_app import init_firebase

        mock_get_app.side_effect = ValueError("No app")
        mock_isfile.return_value = True
        mock_cred = MagicMock()
        mock_certificate.return_value = mock_cred
        mock_app = MagicMock()
        mock_init_app.return_value = mock_app
        mock_db = MagicMock()
        mock_firestore_client.return_value = mock_db

        # Reset global state
        import backend.firebase_app as fb_module

        fb_module._db = None
        fb_module._app = None

        with patch.dict(os.environ, {"GOOGLE_APPLICATION_CREDENTIALS": "/path/to/creds.json"}):
            result = init_firebase()

        assert result == mock_db
        mock_certificate.assert_called_with("/path/to/creds.json")

    def test_get_db_calls_init(self):
        """Test get_db calls init_firebase."""
        from backend.firebase_app import get_db

        with patch("backend.firebase_app.init_firebase") as mock_init:
            mock_db = MagicMock()
            mock_init.return_value = mock_db

            result = get_db()
            assert result == mock_db
            mock_init.assert_called_once()

    @patch("backend.firebase_app.firestore.client")
    @patch("backend.firebase_app.firebase_admin.get_app")
    def test_init_firebase_caches_db(self, mock_get_app, mock_firestore_client):
        """Test init_firebase caches db instance."""
        from backend.firebase_app import init_firebase

        mock_app = MagicMock()
        mock_get_app.return_value = mock_app
        mock_db = MagicMock()
        mock_firestore_client.return_value = mock_db

        # Reset global state
        import backend.firebase_app as fb_module

        fb_module._db = None
        fb_module._app = None

        result1 = init_firebase()
        result2 = init_firebase()

        # Should return same instance
        assert result1 is result2
        # Firestore client should only be called once
        mock_firestore_client.assert_called_once()
