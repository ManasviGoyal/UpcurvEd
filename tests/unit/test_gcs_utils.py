"""Unit tests for GCS utilities."""

import datetime as dt
from unittest.mock import MagicMock, patch


class TestGcsClient:
    """Test GCS client initialization."""

    @patch("backend.gcs_utils.storage.Client")
    def test_client_singleton(self, mock_storage_client):
        """Test that storage client is created as singleton."""
        # Reset the global client
        import backend.gcs_utils
        from backend.gcs_utils import _client

        backend.gcs_utils._storage_client = None

        mock_client = MagicMock()
        mock_storage_client.return_value = mock_client

        # First call creates client
        result1 = _client()
        # Second call returns same client
        result2 = _client()

        assert result1 is result2
        mock_storage_client.assert_called_once()

        # Reset for other tests
        backend.gcs_utils._storage_client = None


class TestUploadBytes:
    """Test upload_bytes function."""

    @patch("backend.gcs_utils._client")
    def test_upload_bytes_success(self, mock_client):
        """Test successful bytes upload."""
        from backend.gcs_utils import upload_bytes

        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_client.return_value.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        result = upload_bytes("test-bucket", "path/to/file.mp4", b"video data", "video/mp4")

        assert result == "gs://test-bucket/path/to/file.mp4"
        mock_bucket.blob.assert_called_with("path/to/file.mp4")
        mock_blob.upload_from_string.assert_called_with(b"video data", content_type="video/mp4")

    @patch("backend.gcs_utils._client")
    def test_upload_bytes_different_content_types(self, mock_client):
        """Test upload with different content types."""
        from backend.gcs_utils import upload_bytes

        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_client.return_value.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        content_types = ["video/mp4", "audio/mpeg", "text/vtt", "application/json"]
        for ct in content_types:
            upload_bytes("bucket", "file", b"data", ct)
            mock_blob.upload_from_string.assert_called_with(b"data", content_type=ct)


class TestSignUrl:
    """Test sign_url function."""

    @patch("google.auth.impersonated_credentials.Credentials")
    @patch.dict(
        "os.environ",
        {"GCS_SIGNER_SERVICE_ACCOUNT": "gcs-signer@test-project.iam.gserviceaccount.com"},
    )
    @patch("google.auth.default", return_value=(MagicMock(), "test-project"))
    @patch("backend.gcs_utils._client")
    def test_sign_url_default_expiration(
        self, mock_client, mock_auth_default, mock_impersonated_creds
    ):
        """Test signed URL generation with default expiration."""
        from backend.gcs_utils import sign_url

        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_blob.generate_signed_url.return_value = "https://signed-url.example.com"
        mock_client.return_value.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        result = sign_url("test-bucket", "path/to/file.mp4")

        assert result == "https://signed-url.example.com"
        mock_blob.generate_signed_url.assert_called_once()
        call_kwargs = mock_blob.generate_signed_url.call_args[1]
        assert call_kwargs["method"] == "GET"
        assert call_kwargs["expiration"] == dt.timedelta(minutes=60)

    @patch("google.auth.impersonated_credentials.Credentials")
    @patch.dict(
        "os.environ",
        {"GCS_SIGNER_SERVICE_ACCOUNT": "gcs-signer@test-project.iam.gserviceaccount.com"},
    )
    @patch("google.auth.default", return_value=(MagicMock(), "test-project"))
    @patch("backend.gcs_utils._client")
    def test_sign_url_custom_expiration(
        self, mock_client, mock_auth_default, mock_impersonated_creds
    ):
        """Test signed URL with custom expiration."""
        from backend.gcs_utils import sign_url

        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_blob.generate_signed_url.return_value = "https://signed-url.example.com"
        mock_client.return_value.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        sign_url("bucket", "path", minutes=120)

        call_kwargs = mock_blob.generate_signed_url.call_args[1]
        assert call_kwargs["expiration"] == dt.timedelta(minutes=120)


class TestGetBucketName:
    """Test get_bucket_name function."""

    @patch.dict("os.environ", {"GCS_ARTIFACT_BUCKET": "my-bucket"})
    def test_returns_env_bucket(self):
        """Test that environment variable is returned."""
        from backend.gcs_utils import get_bucket_name

        result = get_bucket_name()
        assert result == "my-bucket"

    @patch.dict("os.environ", {}, clear=True)
    def test_returns_none_when_not_set(self):
        """Test that None is returned when env var not set."""
        # Clear GCS_ARTIFACT_BUCKET if set
        import os

        os.environ.pop("GCS_ARTIFACT_BUCKET", None)
        from backend.gcs_utils import get_bucket_name

        result = get_bucket_name()
        assert result is None


class TestObjectExists:
    """Test object_exists function."""

    @patch("backend.gcs_utils._client")
    def test_object_exists_true(self, mock_client):
        """Test when object exists."""
        from backend.gcs_utils import object_exists

        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_blob.exists.return_value = True
        mock_client.return_value.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        result = object_exists("bucket", "path/to/file")

        assert result is True
        mock_blob.exists.assert_called_once()

    @patch("backend.gcs_utils._client")
    def test_object_exists_false(self, mock_client):
        """Test when object does not exist."""
        from backend.gcs_utils import object_exists

        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_blob.exists.return_value = False
        mock_client.return_value.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        result = object_exists("bucket", "nonexistent")

        assert result is False


class TestDownloadBytes:
    """Test download_bytes function."""

    @patch("backend.gcs_utils._client")
    def test_download_bytes_success(self, mock_client):
        """Test successful bytes download."""
        from backend.gcs_utils import download_bytes

        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_blob.download_as_bytes.return_value = b"file content"
        mock_client.return_value.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        result = download_bytes("bucket", "path/to/file")

        assert result == b"file content"
        mock_blob.download_as_bytes.assert_called_once()


class TestDeleteFolder:
    """Test delete_folder function."""

    @patch("backend.gcs_utils._client")
    def test_delete_folder_with_objects(self, mock_client):
        """Test deleting folder with objects."""
        from backend.gcs_utils import delete_folder

        mock_bucket = MagicMock()
        mock_blob1 = MagicMock()
        mock_blob2 = MagicMock()
        mock_bucket.list_blobs.return_value = [mock_blob1, mock_blob2]
        # Mock blob() to return non-existent placeholder
        mock_bucket.blob.return_value = MagicMock(exists=MagicMock(return_value=False))
        mock_client.return_value.bucket.return_value = mock_bucket

        result = delete_folder("bucket", "path/to/folder/")

        # Should delete 2 blobs (no placeholders)
        assert result >= 2
        mock_blob1.delete.assert_called_once()
        mock_blob2.delete.assert_called_once()

    @patch("backend.gcs_utils._client")
    def test_delete_folder_empty(self, mock_client):
        """Test deleting empty folder."""
        from backend.gcs_utils import delete_folder

        mock_bucket = MagicMock()
        mock_bucket.list_blobs.return_value = []
        # Mock blob() to return non-existent placeholder
        mock_bucket.blob.return_value = MagicMock(exists=MagicMock(return_value=False))
        mock_client.return_value.bucket.return_value = mock_bucket

        result = delete_folder("bucket", "empty/folder/")

        assert result == 0
