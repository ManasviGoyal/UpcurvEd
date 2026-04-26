"""Unit tests for utility modules."""

import logging

# Import to trigger app-level logging configuration (handlers, format, level).
from backend.utils import app_logging  # noqa: F401
from backend.utils.helpers import truncate

# Get the root 'app' logger that is configured in app_logging
root_app_logger = logging.getLogger("app")
# Child logger for this test module
logger = logging.getLogger(f"app.{__name__}")


class TestLogging:
    """Test logging configuration."""

    def test_logger_exists(self):
        """Logger should be properly initialized."""
        assert root_app_logger is not None
        assert root_app_logger.name == "app"

    def test_logger_has_handlers(self):
        """Root app logger should have at least one handler."""
        assert len(root_app_logger.handlers) >= 1

    def test_logger_level(self):
        """Root app logger should have a valid level set."""
        assert root_app_logger.level > 0  # Should not be NOTSET (0)

    def test_logger_can_log(self):
        """Logger should be able to log messages without error."""
        # This shouldn't raise an exception
        logger.info("Test log message")
        logger.debug("Debug message")
        logger.warning("Warning message")


class TestTruncate:
    """Test text truncation."""

    def test_truncate_none_returns_empty(self):
        assert truncate(None, 10) == ""

    def test_truncate_empty_returns_empty(self):
        assert truncate("", 5) == ""

    def test_truncate_shorter_returns_same(self):
        assert truncate("short", 10) == "short"

    def test_truncate_exact_length_returns_same(self):
        s = "12345"
        assert truncate(s, 5) == s

    def test_truncate_longer_truncates_and_ellipsis(self):
        s = "abcdef"
        # max_chars = 4 -> keep first 3 chars + ellipsis
        assert truncate(s, 4) == "abc…"

    def test_truncate_zero_max_returns_original(self):
        # max_chars falsy -> should return unchanged string
        assert truncate("abc", 0) == "abc"
