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
        ]:
            os.environ.pop(key, None)

        import importlib

        import backend.config

        importlib.reload(backend.config)

        assert backend.config.MAX_CONTEXT_CHARS == 500
        assert backend.config.CLEANUP_FAILED_JOBS is False
        assert backend.config.FAILURE_LOG_PATH == "storage/failure_log.jsonl"
