"""Unit tests for cloud_retriever.py, rag_service/main.py, and failure_log.py."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ============================================================================
# Tests for backend/rag_client/cloud_retriever.py
# ============================================================================


class TestCloudRAGRetrieverInit:
    """Test CloudRAGRetriever initialization."""

    def test_init_with_explicit_url(self):
        """Test initialization with explicit service URL."""
        from backend.rag_client.cloud_retriever import CloudRAGRetriever

        retriever = CloudRAGRetriever(service_url="http://example.com:8001")
        assert retriever.service_url == "http://example.com:8001"
        assert retriever.timeout == 30.0

    def test_init_strips_trailing_slash(self):
        """Test that trailing slash is removed from URL."""
        from backend.rag_client.cloud_retriever import CloudRAGRetriever

        retriever = CloudRAGRetriever(service_url="http://example.com:8001/")
        assert retriever.service_url == "http://example.com:8001"

    def test_init_with_custom_timeout(self):
        """Test initialization with custom timeout."""
        from backend.rag_client.cloud_retriever import CloudRAGRetriever

        retriever = CloudRAGRetriever(service_url="http://example.com:8001", timeout=60.0)
        assert retriever.timeout == 60.0

    @patch.dict(os.environ, {"RAG_SERVICE_URL": "http://env-service:8001"})
    def test_init_uses_env_var(self):
        """Test that service URL falls back to environment variable."""
        from backend.rag_client.cloud_retriever import CloudRAGRetriever

        retriever = CloudRAGRetriever()
        assert retriever.service_url == "http://env-service:8001"

    def test_init_default_service_url(self):
        """Test default service URL when no env var or argument provided."""
        from backend.rag_client.cloud_retriever import CloudRAGRetriever

        with patch.dict(os.environ, {}, clear=True):
            retriever = CloudRAGRetriever()
            assert retriever.service_url == "http://localhost:8001"


class TestCloudRAGRetrieverMakeRequest:
    """Test _make_request method."""

    @patch("backend.rag_client.cloud_retriever.httpx.Client")
    def test_make_request_success(self, mock_client_class):
        """Test successful request."""
        from backend.rag_client.cloud_retriever import CloudRAGRetriever

        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "ok", "data": "test"}
        mock_client = MagicMock()
        mock_client.request.return_value = mock_response
        mock_client_class.return_value.__enter__.return_value = mock_client

        retriever = CloudRAGRetriever(service_url="http://localhost:8001")
        result = retriever._make_request("GET", "/health")

        assert result == {"status": "ok", "data": "test"}

    @patch("backend.rag_client.cloud_retriever.httpx.Client")
    def test_make_request_timeout(self, mock_client_class):
        """Test timeout handling."""
        import httpx

        from backend.rag_client.cloud_retriever import CloudRAGRetriever

        mock_client = MagicMock()
        mock_client.request.side_effect = httpx.TimeoutException("Timeout")
        mock_client_class.return_value.__enter__.return_value = mock_client

        retriever = CloudRAGRetriever(service_url="http://localhost:8001", timeout=5.0)

        with pytest.raises(RuntimeError, match="timed out"):
            retriever._make_request("GET", "/health")

    @patch("backend.rag_client.cloud_retriever.httpx.Client")
    def test_make_request_http_error(self, mock_client_class):
        """Test HTTP error handling."""
        import httpx

        from backend.rag_client.cloud_retriever import CloudRAGRetriever

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_error = httpx.HTTPStatusError("Error", request=MagicMock(), response=mock_response)

        mock_client = MagicMock()
        mock_client.request.side_effect = mock_error
        mock_client_class.return_value.__enter__.return_value = mock_client

        retriever = CloudRAGRetriever(service_url="http://localhost:8001")

        with pytest.raises(RuntimeError, match="500"):
            retriever._make_request("GET", "/health")

    @patch("backend.rag_client.cloud_retriever.httpx.Client")
    def test_make_request_connection_error(self, mock_client_class):
        """Test connection error handling."""
        import httpx

        from backend.rag_client.cloud_retriever import CloudRAGRetriever

        mock_client = MagicMock()
        mock_client.request.side_effect = httpx.RequestError("Connection refused")
        mock_client_class.return_value.__enter__.return_value = mock_client

        retriever = CloudRAGRetriever(service_url="http://localhost:8001")

        with pytest.raises(RuntimeError, match="Failed to connect"):
            retriever._make_request("GET", "/health")


class TestCloudRAGRetrieverHealthCheck:
    """Test health_check method."""

    @patch("backend.rag_client.cloud_retriever.CloudRAGRetriever._make_request")
    def test_health_check_healthy(self, mock_make_request):
        """Test health check when service is healthy."""
        from backend.rag_client.cloud_retriever import CloudRAGRetriever

        mock_make_request.return_value = {"status": "healthy"}
        retriever = CloudRAGRetriever()

        result = retriever.health_check()
        assert result is True

    @patch("backend.rag_client.cloud_retriever.CloudRAGRetriever._make_request")
    def test_health_check_unhealthy(self, mock_make_request):
        """Test health check when service is unhealthy."""
        from backend.rag_client.cloud_retriever import CloudRAGRetriever

        mock_make_request.return_value = {"status": "unhealthy"}
        retriever = CloudRAGRetriever()

        result = retriever.health_check()
        assert result is False

    @patch("backend.rag_client.cloud_retriever.CloudRAGRetriever._make_request")
    def test_health_check_exception(self, mock_make_request):
        """Test health check exception handling."""
        from backend.rag_client.cloud_retriever import CloudRAGRetriever

        mock_make_request.side_effect = Exception("Connection failed")
        retriever = CloudRAGRetriever()

        result = retriever.health_check()
        assert result is False


class TestCloudRAGRetrieverQuery:
    """Test query method."""

    @patch("backend.rag_client.cloud_retriever.CloudRAGRetriever._make_request")
    def test_query_success(self, mock_make_request):
        """Test successful query."""
        from backend.rag_client.cloud_retriever import CloudRAGRetriever

        mock_make_request.return_value = {
            "results": [
                {
                    "id": "doc1",
                    "content": "Test content",
                    "score": 0.95,
                    "metadata": {"source": "doc1.md"},
                }
            ]
        }
        retriever = CloudRAGRetriever()

        results = retriever.query("What is Transform?", top_k=5)

        assert len(results) == 1
        assert results[0]["id"] == "doc1"
        assert results[0]["content"] == "Test content"

    @patch("backend.rag_client.cloud_retriever.CloudRAGRetriever._make_request")
    def test_query_empty_query(self, mock_make_request):
        """Test query with empty query text."""
        from backend.rag_client.cloud_retriever import CloudRAGRetriever

        retriever = CloudRAGRetriever()

        results = retriever.query("")
        assert results == []
        mock_make_request.assert_not_called()

    @patch("backend.rag_client.cloud_retriever.CloudRAGRetriever._make_request")
    def test_query_whitespace_only(self, mock_make_request):
        """Test query with only whitespace."""
        from backend.rag_client.cloud_retriever import CloudRAGRetriever

        retriever = CloudRAGRetriever()

        results = retriever.query("   ")
        assert results == []
        mock_make_request.assert_not_called()

    @patch("backend.rag_client.cloud_retriever.CloudRAGRetriever._make_request")
    def test_query_without_metadata(self, mock_make_request):
        """Test query with include_metadata=False."""
        from backend.rag_client.cloud_retriever import CloudRAGRetriever

        mock_make_request.return_value = {"results": []}
        retriever = CloudRAGRetriever()

        retriever.query("test", include_metadata=False)

        call_args = mock_make_request.call_args
        json_payload = call_args[1]["json"]
        assert json_payload["include_metadata"] is False


class TestCloudRAGRetrieverQueryMultiple:
    """Test query_multiple method."""

    @patch("backend.rag_client.cloud_retriever.CloudRAGRetriever._make_request")
    def test_query_multiple_success(self, mock_make_request):
        """Test successful multiple query."""
        from backend.rag_client.cloud_retriever import CloudRAGRetriever

        mock_make_request.return_value = {
            "results": [
                {"id": "doc1", "content": "Content 1", "score": 0.9},
                {"id": "doc2", "content": "Content 2", "score": 0.8},
            ]
        }
        retriever = CloudRAGRetriever()

        results = retriever.query_multiple(
            ["query1", "query2"], top_k_per_query=5, deduplicate=True
        )

        assert len(results) == 2
        assert results[0]["id"] == "doc1"

    @patch("backend.rag_client.cloud_retriever.CloudRAGRetriever._make_request")
    def test_query_multiple_empty_queries(self, mock_make_request):
        """Test multiple query with empty list."""
        from backend.rag_client.cloud_retriever import CloudRAGRetriever

        retriever = CloudRAGRetriever()

        results = retriever.query_multiple([])
        assert results == []
        mock_make_request.assert_not_called()

    @patch("backend.rag_client.cloud_retriever.CloudRAGRetriever._make_request")
    def test_query_multiple_all_whitespace(self, mock_make_request):
        """Test multiple query with only whitespace queries."""
        from backend.rag_client.cloud_retriever import CloudRAGRetriever

        retriever = CloudRAGRetriever()

        results = retriever.query_multiple(["   ", "\t", "\n"])
        assert results == []
        mock_make_request.assert_not_called()

    @patch("backend.rag_client.cloud_retriever.CloudRAGRetriever._make_request")
    def test_query_multiple_filters_empty_queries(self, mock_make_request):
        """Test that empty queries are filtered out."""
        from backend.rag_client.cloud_retriever import CloudRAGRetriever

        mock_make_request.return_value = {"results": []}
        retriever = CloudRAGRetriever()

        retriever.query_multiple(["query1", "", "query2"])

        call_args = mock_make_request.call_args
        json_payload = call_args[1]["json"]
        assert json_payload["queries"] == ["query1", "query2"]


class TestCloudRAGRetrieverQueryFormatted:
    """Test query_formatted method."""

    @patch("backend.rag_client.cloud_retriever.CloudRAGRetriever._make_request")
    def test_query_formatted_success(self, mock_make_request):
        """Test successful formatted query."""
        from backend.rag_client.cloud_retriever import CloudRAGRetriever

        mock_make_request.return_value = {"formatted_docs": "1. Content 1\n2. Content 2\n"}
        retriever = CloudRAGRetriever()

        result = retriever.query_formatted("test query", top_k=5, max_length=2000)

        assert "Content 1" in result

    @patch("backend.rag_client.cloud_retriever.CloudRAGRetriever._make_request")
    def test_query_formatted_empty_query(self, mock_make_request):
        """Test formatted query with empty query."""
        from backend.rag_client.cloud_retriever import CloudRAGRetriever

        retriever = CloudRAGRetriever()

        result = retriever.query_formatted("")
        assert result == ""
        mock_make_request.assert_not_called()

    @patch("backend.rag_client.cloud_retriever.CloudRAGRetriever._make_request")
    def test_query_formatted_custom_max_length(self, mock_make_request):
        """Test formatted query with custom max_length."""
        from backend.rag_client.cloud_retriever import CloudRAGRetriever

        mock_make_request.return_value = {"formatted_docs": ""}
        retriever = CloudRAGRetriever()

        retriever.query_formatted("test", max_length=5000)

        call_args = mock_make_request.call_args
        json_payload = call_args[1]["json"]
        assert json_payload["max_length"] == 5000


class TestCloudRAGRetrieverCollectionInfo:
    """Test get_collection_info method."""

    @patch("backend.rag_client.cloud_retriever.CloudRAGRetriever._make_request")
    def test_get_collection_info(self, mock_make_request):
        """Test getting collection info."""
        from backend.rag_client.cloud_retriever import CloudRAGRetriever

        mock_make_request.return_value = {
            "name": "manim_knowledge",
            "doc_count": 100,
        }
        retriever = CloudRAGRetriever()

        result = retriever.get_collection_info()

        assert result["name"] == "manim_knowledge"
        mock_make_request.assert_called_once_with("GET", "/collection/info")


class TestGetRAGRetriever:
    """Test get_rag_retriever factory function."""

    def test_get_rag_retriever_cloud_explicit(self):
        """Test factory returns CloudRAGRetriever when use_cloud=True."""
        from backend.rag_client.cloud_retriever import CloudRAGRetriever, get_rag_retriever

        retriever = get_rag_retriever(use_cloud=True)
        assert isinstance(retriever, CloudRAGRetriever)

    @patch.dict(os.environ, {"RAG_USE_CLOUD": "true"})
    def test_get_rag_retriever_env_true(self):
        """Test factory checks RAG_USE_CLOUD environment variable."""
        from backend.rag_client.cloud_retriever import CloudRAGRetriever, get_rag_retriever

        retriever = get_rag_retriever()
        assert isinstance(retriever, CloudRAGRetriever)


# ============================================================================
# Tests for backend/utils/failure_log.py
# ============================================================================


class TestAppendFailureLog:
    """Test append_failure_log function."""

    def test_append_failure_log_creates_directory(self):
        """Test that parent directory is created if it doesn't exist."""
        from backend.utils.failure_log import append_failure_log

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "logs" / "subdir" / "failure.jsonl"
            entry = {"job_id": "test-123", "error": "test error"}

            append_failure_log(str(log_path), entry)

            assert log_path.exists()
            assert log_path.parent.exists()

    def test_append_failure_log_adds_timestamp(self):
        """Test that timestamp is added to entry."""
        from backend.utils.failure_log import append_failure_log

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "failure.jsonl"
            entry = {"job_id": "test-123"}

            append_failure_log(str(log_path), entry)

            with log_path.open("r") as f:
                logged_entry = json.loads(f.readline())

            assert "ts" in logged_entry
            assert logged_entry["ts"]  # Should have a value

    def test_append_failure_log_preserves_existing_timestamp(self):
        """Test that existing timestamp is not overwritten."""
        from backend.utils.failure_log import append_failure_log

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "failure.jsonl"
            timestamp = "2024-01-01T12:00:00+00:00"
            entry = {"job_id": "test-123", "ts": timestamp}

            append_failure_log(str(log_path), entry)

            with log_path.open("r") as f:
                logged_entry = json.loads(f.readline())

            assert logged_entry["ts"] == timestamp

    def test_append_failure_log_truncates_context(self):
        """Test that error_context is truncated if too long."""
        from backend.utils.failure_log import append_failure_log

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "failure.jsonl"
            long_context = "x" * 1000
            entry = {"job_id": "test-123", "error_context": long_context}

            append_failure_log(str(log_path), entry, max_context_chars=100)

            with log_path.open("r") as f:
                logged_entry = json.loads(f.readline())

            context = logged_entry["error_context"]
            assert len(context) == 101  # 100 chars + "…"
            assert context.endswith("…")

    def test_append_failure_log_no_truncate_when_short(self):
        """Test that short context is not truncated."""
        from backend.utils.failure_log import append_failure_log

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "failure.jsonl"
            entry = {"job_id": "test-123", "error_context": "short error"}

            append_failure_log(str(log_path), entry, max_context_chars=100)

            with log_path.open("r") as f:
                logged_entry = json.loads(f.readline())

            assert logged_entry["error_context"] == "short error"
            assert "…" not in logged_entry["error_context"]

    def test_append_failure_log_appends_multiple_entries(self):
        """Test that multiple entries are appended as separate lines."""
        from backend.utils.failure_log import append_failure_log

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "failure.jsonl"

            append_failure_log(str(log_path), {"job_id": "1"})
            append_failure_log(str(log_path), {"job_id": "2"})
            append_failure_log(str(log_path), {"job_id": "3"})

            with log_path.open("r") as f:
                lines = f.readlines()

            assert len(lines) == 3
            assert json.loads(lines[0])["job_id"] == "1"
            assert json.loads(lines[1])["job_id"] == "2"
            assert json.loads(lines[2])["job_id"] == "3"

    def test_append_failure_log_no_truncate_without_max_chars(self):
        """Test that context is not truncated when max_context_chars is None."""
        from backend.utils.failure_log import append_failure_log

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "failure.jsonl"
            long_context = "x" * 10000
            entry = {"job_id": "test", "error_context": long_context}

            append_failure_log(str(log_path), entry, max_context_chars=None)

            with log_path.open("r") as f:
                logged_entry = json.loads(f.readline())

            assert logged_entry["error_context"] == long_context
            assert "…" not in logged_entry["error_context"]

    def test_append_failure_log_no_truncate_when_zero(self):
        """Test that context is not truncated when max_context_chars is 0."""
        from backend.utils.failure_log import append_failure_log

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "failure.jsonl"
            long_context = "x" * 1000
            entry = {"job_id": "test", "error_context": long_context}

            append_failure_log(str(log_path), entry, max_context_chars=0)

            with log_path.open("r") as f:
                logged_entry = json.loads(f.readline())

            assert logged_entry["error_context"] == long_context


class TestCleanupJobDir:
    """Test cleanup_job_dir function."""

    @patch("shutil.rmtree")
    def test_cleanup_job_dir_within_storage_jobs(self, mock_rmtree):
        """Test successful cleanup of job directory within storage/jobs."""
        from backend.utils.failure_log import cleanup_job_dir

        job_dir = Path("storage/jobs/test-123")

        result = cleanup_job_dir(job_dir)

        assert result is True
        mock_rmtree.assert_called_once()

    @patch("shutil.rmtree")
    def test_cleanup_job_dir_string_path(self, mock_rmtree):
        """Test cleanup with string path."""
        from backend.utils.failure_log import cleanup_job_dir

        job_dir = "storage/jobs/test-456"

        result = cleanup_job_dir(job_dir)

        assert result is True
        mock_rmtree.assert_called_once()

    @patch("shutil.rmtree")
    def test_cleanup_job_dir_outside_storage_jobs(self, mock_rmtree):
        """Test that cleanup refuses to delete outside storage/jobs."""
        from backend.utils.failure_log import cleanup_job_dir

        job_dir = Path("/tmp/random-dir")

        result = cleanup_job_dir(job_dir)

        assert result is False
        mock_rmtree.assert_not_called()

    @patch("shutil.rmtree")
    def test_cleanup_job_dir_exception_handling(self, mock_rmtree):
        """Test that exceptions are handled gracefully."""
        from backend.utils.failure_log import cleanup_job_dir

        mock_rmtree.side_effect = Exception("Permission denied")

        result = cleanup_job_dir("storage/jobs/test-789")

        assert result is False

    def test_cleanup_job_dir_ignore_errors(self):
        """Test that cleanup ignores errors when deleting."""
        from backend.utils.failure_log import cleanup_job_dir

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a subdirectory under a mock storage/jobs structure
            job_dir = Path(tmpdir) / "storage" / "jobs" / "test-job"
            job_dir.mkdir(parents=True)
            test_file = job_dir / "test.txt"
            test_file.write_text("test")

            with patch("backend.utils.failure_log.JOBS_ROOT", Path(tmpdir) / "storage" / "jobs"):
                result = cleanup_job_dir(job_dir)

            assert result is True
            # Directory should be removed
            assert not job_dir.exists()

    @patch("shutil.rmtree")
    def test_cleanup_job_dir_nonexistent_path(self, mock_rmtree):
        """Test cleanup of nonexistent directory."""
        from backend.utils.failure_log import cleanup_job_dir

        # rmtree with ignore_errors=True should return True
        mock_rmtree.return_value = None

        result = cleanup_job_dir("storage/jobs/nonexistent-123")

        assert result is True


# ============================================================================
# Tests for backend/rag_service/main.py (RAG service endpoints)
# ============================================================================


class TestRAGServiceHealth:
    """Test health check endpoint."""

    @patch("backend.rag_service.main.get_chroma_client")
    def test_health_check_healthy(self, mock_get_client):
        """Test health check when ChromaDB is healthy."""
        from fastapi.testclient import TestClient

        from backend.rag_service.main import app

        mock_client = MagicMock()
        mock_client.heartbeat.return_value = None
        mock_get_client.return_value = mock_client

        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    @patch("backend.rag_service.main.get_chroma_client")
    def test_health_check_chroma_error(self, mock_get_client):
        """Test health check when ChromaDB is unavailable."""
        from fastapi.testclient import TestClient

        from backend.rag_service.main import app

        mock_client = MagicMock()
        mock_client.heartbeat.side_effect = Exception("Connection failed")
        mock_get_client.return_value = mock_client

        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 503


class TestRAGServiceQuery:
    """Test /query endpoint."""

    def test_query_invalid_top_k_too_high(self):
        """Test query with top_k > 20."""
        from fastapi.testclient import TestClient

        from backend.rag_service.main import app

        client = TestClient(app)
        response = client.post("/query", json={"query": "test", "top_k": 25})

        assert response.status_code == 422

    def test_query_invalid_top_k_zero(self):
        """Test query with top_k < 1."""
        from fastapi.testclient import TestClient

        from backend.rag_service.main import app

        client = TestClient(app)
        response = client.post("/query", json={"query": "test", "top_k": 0})

        assert response.status_code == 422

    def test_query_missing_query_field(self):
        """Test query with missing query field."""
        from fastapi.testclient import TestClient

        from backend.rag_service.main import app

        client = TestClient(app)
        response = client.post("/query", json={"top_k": 5})

        assert response.status_code == 422


class TestRAGServiceMultiQuery:
    """Test /query-multiple endpoint."""

    def test_multi_query_invalid_top_k(self):
        """Test multi-query with invalid top_k_per_query."""
        from fastapi.testclient import TestClient

        from backend.rag_service.main import app

        client = TestClient(app)
        response = client.post(
            "/query-multiple",
            json={"queries": ["query1", "query2"], "top_k_per_query": 15},
        )

        assert response.status_code == 422


class TestRAGServiceFormatted:
    """Test /query-formatted endpoint."""

    def test_query_formatted_invalid_max_length_too_small(self):
        """Test formatted query with max_length < 100."""
        from fastapi.testclient import TestClient

        from backend.rag_service.main import app

        client = TestClient(app)
        response = client.post(
            "/query-formatted",
            json={"query": "test", "top_k": 5, "max_length": 50},
        )

        assert response.status_code == 422

    def test_query_formatted_invalid_max_length_too_large(self):
        """Test formatted query with max_length > 10000."""
        from fastapi.testclient import TestClient

        from backend.rag_service.main import app

        client = TestClient(app)
        response = client.post(
            "/query-formatted",
            json={"query": "test", "top_k": 5, "max_length": 15000},
        )

        assert response.status_code == 422


class TestRAGServiceCollectionInfo:
    """Test /collection/info endpoint."""

    @patch("backend.rag_service.main.get_collection")
    def test_collection_info_success(self, mock_get_collection):
        """Test successful collection info retrieval."""
        from fastapi.testclient import TestClient

        from backend.rag_service.main import app

        mock_collection = MagicMock()
        mock_collection.count.return_value = 150
        mock_get_collection.return_value = mock_collection

        client = TestClient(app)
        response = client.get("/collection/info")

        assert response.status_code == 200
        data = response.json()
        assert data["document_count"] == 150
        assert data["name"] == "manim_knowledge"

    @patch("backend.rag_service.main.get_collection")
    def test_collection_info_error(self, mock_get_collection):
        """Test collection info error handling."""
        from fastapi.testclient import TestClient

        from backend.rag_service.main import app

        mock_get_collection.side_effect = Exception("Collection not found")

        client = TestClient(app)
        response = client.get("/collection/info")

        assert response.status_code == 500


class TestRAGServiceInitialization:
    """Test ChromaDB client and collection initialization."""

    def test_get_chroma_client_lazy_loads(self):
        """Test that ChromaDB client is lazily loaded."""
        from backend.rag_service import main

        # Reset global state
        main._client = None

        with patch("chromadb.HttpClient") as mock_http_client:
            mock_instance = MagicMock()
            mock_http_client.return_value = mock_instance

            client1 = main.get_chroma_client()
            client2 = main.get_chroma_client()

            assert client1 is client2
            assert mock_http_client.call_count == 1

    def test_get_collection_lazy_loads(self):
        """Test that collection is lazily loaded."""
        from backend.rag_service import main

        # Reset global state
        main._collection = None
        main._client = None

        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_client.get_collection.return_value = mock_collection

        with patch("backend.rag_service.main.get_chroma_client") as mock_get_client:
            mock_get_client.return_value = mock_client

            coll1 = main.get_collection()
            coll2 = main.get_collection()

            assert coll1 is coll2

    def test_get_collection_error_handling(self):
        """Test collection initialization error handling."""
        from backend.rag_service import main

        main._collection = None
        main._client = None

        mock_client = MagicMock()
        mock_client.get_collection.side_effect = Exception("Collection not found")

        with patch("backend.rag_service.main.get_chroma_client") as mock_get_client:
            mock_get_client.return_value = mock_client

            with pytest.raises(RuntimeError, match="Collection"):
                main.get_collection()
