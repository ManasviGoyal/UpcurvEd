"""Unit tests for failure logging and job-directory cleanup."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest


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
