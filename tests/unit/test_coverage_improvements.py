"""Unit tests for job_runner.py, rag_service/main.py, and log_failure.py."""

from unittest.mock import MagicMock, patch

import pytest

from backend.agent.nodes.log_failure import log_failure_node
from backend.runner.job_runner import (
    STORAGE,
    _inject_watermark,
    _kill_proc_tree,
    _truncate,
    to_static_url,
)


class TestToStaticUrl:
    """Test static URL generation."""

    def test_converts_path_to_url(self):
        """Test basic path to URL conversion."""
        path = STORAGE / "jobs" / "test-123" / "video.mp4"
        url = to_static_url(path)
        assert url.startswith("/static/")
        assert "test-123" in url
        assert "video.mp4" in url

    def test_url_format(self):
        """Test URL format is correct."""
        path = STORAGE / "jobs" / "abc" / "out" / "output.mp4"
        url = to_static_url(path)
        assert url == "/static/jobs/abc/out/output.mp4"


class TestTruncate:
    """Test log truncation."""

    def test_truncate_long_string(self):
        """Test truncating long strings."""
        long_text = "x" * 10000
        truncated = _truncate(long_text, limit=100)
        assert len(truncated) == 100
        assert truncated == "x" * 100

    def test_keep_short_string(self):
        """Test short strings are not truncated."""
        short_text = "hello world"
        result = _truncate(short_text, limit=100)
        assert result == short_text

    def test_none_returns_empty(self):
        """Test None returns empty string."""
        result = _truncate(None)
        assert result == ""

    def test_empty_string_returns_empty(self):
        """Test empty string returns empty string."""
        result = _truncate("")
        assert result == ""

    def test_custom_limit(self):
        """Test custom truncation limit."""
        text = "a" * 50
        result = _truncate(text, limit=10)
        assert len(result) == 10


class TestKillProcTree:
    """Test process tree killing."""

    @patch("os.killpg")
    @patch("os.waitpid")
    def test_kill_proc_tree_success(self, mock_waitpid, mock_killpg):
        """Test successful process tree killing."""
        mock_proc = MagicMock()
        mock_proc.pid = 1234
        mock_proc.wait = MagicMock()

        _kill_proc_tree(mock_proc)

        mock_killpg.assert_called()
        mock_proc.wait.assert_called()

    @patch("os.killpg", side_effect=Exception("Permission denied"))
    def test_kill_proc_tree_exception_ignored(self, mock_killpg):
        """Test that exceptions in process killing are ignored."""
        mock_proc = MagicMock()
        mock_proc.pid = 1234
        # Should not raise
        _kill_proc_tree(mock_proc)


class TestInjectWatermark:
    """Test watermark injection."""

    def test_inject_watermark_adds_code(self):
        """Test that watermark code is added."""
        code = """class TestScene(Scene):
    def construct(self):
        pass"""
        result = _inject_watermark(code)
        assert "watermark" in result.lower()
        assert "Generated using UpcurvEd" in result

    def test_inject_watermark_preserves_code(self):
        """Test that original code is preserved."""
        code = """class TestScene(Scene):
    def construct(self):
        self.play(Create(Circle()))"""
        result = _inject_watermark(code)
        assert "TestScene" in result
        assert "Circle" in result

    def test_inject_watermark_handles_empty_code(self):
        """Test watermark injection with empty code."""
        result = _inject_watermark("")
        assert result is not None
        assert isinstance(result, str)


class TestRunJobFromCode:
    """Test job execution from code - uses mocks to avoid actual file I/O."""

    def test_truncate_function(self):
        """Test truncate helper function."""
        result = _truncate("short")
        assert result == "short"

        result = _truncate("x" * 10000, limit=100)
        assert len(result) == 100

    def test_to_static_url_with_job_id(self):
        """Test URL generation for job output."""
        path = STORAGE / "jobs" / "abc123" / "out" / "video.mp4"
        url = to_static_url(path)
        assert "/static/jobs/abc123/out/video.mp4" in url


class TestLogFailure:
    """Test failure logging node."""

    def test_log_failure_node_skips_successful_render(self):
        """Test that node returns state unchanged for successful render."""
        state = {
            "render_ok": True,
            "job_id": "test-123",
            "provider": "claude",
        }
        result = log_failure_node(state)
        assert result == state

    @patch("backend.agent.nodes.log_failure.logger")
    def test_log_failure_node_logs_failure(self, mock_logger):
        """Test that node logs failure information."""
        state = {
            "render_ok": False,
            "job_id": "test-456",
            "provider": "gemini",
            "model": "gemini-pro",
            "error": "render_failed",
            "error_context": "Test error context",
            "retrieved_docs": "Test docs",
            "tries": "2",
            "attempt_job_ids": ["job-1", "job-2"],
        }

        result = log_failure_node(state)

        assert result == state
        assert mock_logger.info.called

    @patch("backend.agent.nodes.log_failure.logger")
    def test_log_failure_node_handles_missing_fields(self, mock_logger):
        """Test logging with missing optional fields."""
        state = {
            "render_ok": False,
            "job_id": "test-789",
        }

        result = log_failure_node(state)

        assert result == state
        assert mock_logger.info.called

    @patch("backend.agent.nodes.log_failure.logger")
    def test_log_failure_node_handles_invalid_tries(self, mock_logger):
        """Test logging with invalid tries value."""
        state = {
            "render_ok": False,
            "job_id": "test-999",
            "tries": "not_a_number",
        }

        result = log_failure_node(state)

        assert result == state
        # Should default tries to 0
        assert mock_logger.info.called

    @patch("backend.agent.nodes.log_failure.logger")
    def test_log_failure_node_handles_logging_exception(self, mock_logger):
        """Test that logging exceptions don't break the node."""
        state = {
            "render_ok": False,
            "job_id": "test-fail",
        }

        # Make logger.info raise an exception
        mock_logger.info.side_effect = Exception("Logging failed")
        mock_logger.exception = MagicMock()

        result = log_failure_node(state)

        # Should still return state and log the exception
        assert result == state
        assert mock_logger.exception.called


class TestRagServiceEndpoints:
    """Test RAG service endpoints."""

    @patch("backend.rag_service.main.get_chroma_client")
    def test_health_check_healthy(self, mock_get_client):
        """Test health check returns healthy status."""
        from fastapi.testclient import TestClient

        from backend.rag_service.main import app

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    @patch("backend.rag_service.main.get_chroma_client")
    def test_health_check_unhealthy(self, mock_get_client):
        """Test health check returns unhealthy status."""
        from fastapi.testclient import TestClient

        from backend.rag_service.main import app

        mock_client = MagicMock()
        mock_client.heartbeat.side_effect = Exception("Connection failed")
        mock_get_client.return_value = mock_client

        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 503

    @patch("backend.rag_service.main.get_collection")
    def test_query_rag_endpoint(self, mock_get_collection):
        """Test RAG query endpoint with invalid top_k."""
        from fastapi.testclient import TestClient

        from backend.rag_service.main import app

        client = TestClient(app)
        response = client.post(
            "/query",
            json={
                "query": "test query",
                "top_k": 25,  # > 20 is invalid
            },
        )

        # Should return validation error
        assert response.status_code == 422

    @patch("backend.rag_service.main.get_collection")
    def test_query_rag_invalid_top_k(self, mock_get_collection):
        """Test RAG query endpoint with invalid top_k."""
        from fastapi.testclient import TestClient

        from backend.rag_service.main import app

        client = TestClient(app)
        response = client.post(
            "/query",
            json={
                "query": "test query",
                "top_k": 0,  # < 1 is invalid
            },
        )

        # Should return validation error
        assert response.status_code == 422

    @patch("backend.rag_service.main.get_collection")
    def test_multi_query_endpoint(self, mock_get_collection):
        """Test multi-query endpoint with invalid top_k."""
        from fastapi.testclient import TestClient

        from backend.rag_service.main import app

        client = TestClient(app)
        response = client.post(
            "/query-multiple",
            json={
                "queries": ["query1", "query2"],
                "top_k_per_query": 15,  # > 10 is invalid
            },
        )

        assert response.status_code == 422

    @patch("backend.rag_service.main.get_collection")
    def test_format_endpoint(self, mock_get_collection):
        """Test format endpoint with invalid max_length."""
        from fastapi.testclient import TestClient

        from backend.rag_service.main import app

        client = TestClient(app)
        response = client.post(
            "/query-formatted",
            json={
                "query": "test",
                "top_k": 5,
                "max_length": 15000,  # > 10000 is invalid
            },
        )

        assert response.status_code == 422


class TestRagServiceCollections:
    """Test RAG service collection management."""

    @patch("chromadb.HttpClient")
    def test_get_collection_success(self, mock_http_client):
        """Test successful collection retrieval."""
        from backend.rag_service import main

        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_client.get_collection.return_value = mock_collection
        mock_http_client.return_value = mock_client

        # Reset globals
        main._client = None
        main._collection = None

        result = main.get_collection()
        assert result == mock_collection

    @patch("chromadb.HttpClient")
    def test_get_collection_not_found(self, mock_http_client):
        """Test collection not found error."""
        from backend.rag_service import main

        mock_client = MagicMock()
        mock_client.get_collection.side_effect = Exception("Collection not found")
        mock_http_client.return_value = mock_client

        # Reset globals
        main._client = None
        main._collection = None

        with pytest.raises(RuntimeError, match="Collection"):
            main.get_collection()
