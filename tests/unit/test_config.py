"""Unit tests for backend config module."""

import os
from unittest.mock import patch


class TestMaxContextChars:
    """Test MAX_CONTEXT_CHARS configuration."""

    @patch.dict(os.environ, {"MAX_CONTEXT_CHARS": "1000"})
    def test_custom_value(self):
        """Test custom MAX_CONTEXT_CHARS value."""
        # Re-import to pick up new env var
        import importlib

        import backend.config

        importlib.reload(backend.config)

        assert backend.config.MAX_CONTEXT_CHARS == 1000

    @patch.dict(os.environ, {}, clear=True)
    def test_default_value(self):
        """Test default MAX_CONTEXT_CHARS value."""
        os.environ.pop("MAX_CONTEXT_CHARS", None)
        import importlib

        import backend.config

        importlib.reload(backend.config)

        assert backend.config.MAX_CONTEXT_CHARS == 500


class TestCleanupFailedJobs:
    """Test CLEANUP_FAILED_JOBS configuration."""

    @patch.dict(os.environ, {"CLEANUP_FAILED_JOBS": "true"})
    def test_true_value(self):
        """Test CLEANUP_FAILED_JOBS set to true."""
        import importlib

        import backend.config

        importlib.reload(backend.config)

        assert backend.config.CLEANUP_FAILED_JOBS is True

    @patch.dict(os.environ, {"CLEANUP_FAILED_JOBS": "false"})
    def test_false_value(self):
        """Test CLEANUP_FAILED_JOBS set to false."""
        import importlib

        import backend.config

        importlib.reload(backend.config)

        assert backend.config.CLEANUP_FAILED_JOBS is False

    @patch.dict(os.environ, {"CLEANUP_FAILED_JOBS": "TRUE"})
    def test_case_insensitive(self):
        """Test case insensitive comparison."""
        import importlib

        import backend.config

        importlib.reload(backend.config)

        assert backend.config.CLEANUP_FAILED_JOBS is True


class TestFailureLogPath:
    """Test FAILURE_LOG_PATH configuration."""

    @patch.dict(os.environ, {"FAILURE_LOG_PATH": "/custom/path/failures.jsonl"})
    def test_custom_path(self):
        """Test custom failure log path."""
        import importlib

        import backend.config

        importlib.reload(backend.config)

        assert backend.config.FAILURE_LOG_PATH == "/custom/path/failures.jsonl"

    @patch.dict(os.environ, {}, clear=True)
    def test_default_path(self):
        """Test default failure log path."""
        os.environ.pop("FAILURE_LOG_PATH", None)
        import importlib

        import backend.config

        importlib.reload(backend.config)

        assert backend.config.FAILURE_LOG_PATH == "storage/failure_log.jsonl"


class TestRagConfiguration:
    """Test RAG-related configuration."""

    @patch.dict(os.environ, {"RAG_USE_CLOUD": "true"})
    def test_rag_use_cloud_true(self):
        """Test RAG_USE_CLOUD set to true."""
        import importlib

        import backend.config

        importlib.reload(backend.config)

        assert backend.config.RAG_USE_CLOUD is True

    @patch.dict(os.environ, {"RAG_USE_CLOUD": "false"})
    def test_rag_use_cloud_false(self):
        """Test RAG_USE_CLOUD set to false."""
        import importlib

        import backend.config

        importlib.reload(backend.config)

        assert backend.config.RAG_USE_CLOUD is False

    @patch.dict(os.environ, {"RAG_SERVICE_URL": "http://rag-service:9000"})
    def test_custom_rag_service_url(self):
        """Test custom RAG service URL."""
        import importlib

        import backend.config

        importlib.reload(backend.config)

        assert backend.config.RAG_SERVICE_URL == "http://rag-service:9000"

    @patch.dict(os.environ, {"RAG_DB_PATH": "/data/chroma"})
    def test_custom_rag_db_path(self):
        """Test custom RAG database path."""
        import importlib

        import backend.config

        importlib.reload(backend.config)

        assert backend.config.RAG_DB_PATH == "/data/chroma"

    @patch.dict(os.environ, {"RAG_COLLECTION_NAME": "custom_collection"})
    def test_custom_collection_name(self):
        """Test custom collection name."""
        import importlib

        import backend.config

        importlib.reload(backend.config)

        assert backend.config.RAG_COLLECTION_NAME == "custom_collection"


class TestDefaultValues:
    """Test all default configuration values."""

    @patch.dict(os.environ, {}, clear=True)
    def test_all_defaults(self):
        """Test all default values together."""
        # Clear all config-related env vars
        for key in [
            "MAX_CONTEXT_CHARS",
            "CLEANUP_FAILED_JOBS",
            "FAILURE_LOG_PATH",
            "RAG_USE_CLOUD",
            "RAG_SERVICE_URL",
            "RAG_DB_PATH",
            "RAG_COLLECTION_NAME",
        ]:
            os.environ.pop(key, None)

        import importlib

        import backend.config

        importlib.reload(backend.config)

        assert backend.config.MAX_CONTEXT_CHARS == 500
        assert backend.config.CLEANUP_FAILED_JOBS is False
        assert backend.config.FAILURE_LOG_PATH == "storage/failure_log.jsonl"
        assert backend.config.RAG_USE_CLOUD is True
        assert backend.config.RAG_SERVICE_URL == "http://localhost:8001"
        assert backend.config.RAG_DB_PATH == "rag-data/processed/chroma_db"
        assert backend.config.RAG_COLLECTION_NAME == "manim_knowledge"
