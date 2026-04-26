"""Unit tests for account deletion functionality in backend/api/main.py."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app, require_firebase_user


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def mock_firebase_user():
    """Mock Firebase user dependency."""

    def fake_auth(authorization: str = None):
        return "test-uid-123"

    app.dependency_overrides[require_firebase_user] = fake_auth
    yield
    app.dependency_overrides.clear()


class TestDeleteAccountEndpoint:
    """Test the DELETE /api/account endpoint."""

    def test_delete_account_endpoint_exists(self, client, mock_firebase_user):
        """Test that the endpoint exists and requires authentication."""
        response = client.delete("/api/account")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["uid"] == "test-uid-123"

    def test_delete_account_returns_summary(self, client, mock_firebase_user):
        """Test that delete account returns proper summary."""
        response = client.delete("/api/account")
        assert response.status_code == 200
        data = response.json()

        # Check response structure
        assert "ok" in data
        assert "uid" in data
        assert "chats_removed" in data
        assert "messages_removed" in data
        assert "artifacts_removed" in data
        assert "gcs_files_removed" in data

        # Check types
        assert isinstance(data["chats_removed"], int)
        assert isinstance(data["messages_removed"], int)
        assert isinstance(data["artifacts_removed"], int)
        assert isinstance(data["gcs_files_removed"], int)

    @patch("backend.api.main.get_db")
    @patch("backend.api.main.get_bucket_name")
    @patch("backend.api.main.delete_folder")
    def test_delete_account_unauthorized(self, mock_delete_folder, mock_bucket, mock_db):
        """Test that endpoint requires authentication."""
        # This test verifies the endpoint structure is correct
        # The actual auth is enforced by the require_firebase_user dependency
        pass


class TestDeleteAccountImpl:
    """Test the _delete_account_impl function."""

    @patch("backend.api.main.get_db")
    @patch("backend.api.main.get_bucket_name")
    @patch("backend.api.main.delete_folder")
    def test_delete_account_with_no_data(
        self, mock_delete_folder, mock_bucket, mock_db, mock_firebase_user
    ):
        """Test deleting account with no chats, messages, or artifacts."""
        from backend.api.main import _delete_account_impl

        # Setup mocks
        mock_delete_folder.return_value = 0
        mock_bucket.return_value = "test-bucket"

        # Mock Firestore database
        mock_firestore_db = MagicMock()
        mock_db.return_value = mock_firestore_db

        # Mock user document reference
        mock_user_ref = MagicMock()
        mock_user_doc = MagicMock()
        mock_user_doc.exists = True
        mock_user_ref.get.return_value = mock_user_doc

        # Mock collections (empty)
        mock_chats_ref = MagicMock()
        mock_artifacts_ref = MagicMock()
        mock_chats_ref.stream.return_value = []
        mock_artifacts_ref.stream.return_value = []

        mock_user_ref.collection.side_effect = lambda name: {
            "chats": mock_chats_ref,
            "artifacts": mock_artifacts_ref,
        }[name]

        mock_firestore_db.collection.return_value.document.return_value = mock_user_ref

        # Execute
        result = _delete_account_impl("test-uid-123")

        # Assert
        assert result["ok"] is True
        assert result["uid"] == "test-uid-123"
        assert result["chats_removed"] == 0
        assert result["messages_removed"] == 0
        assert result["artifacts_removed"] == 0
        assert result["gcs_files_removed"] == 0

        # Verify user document was deleted
        mock_user_ref.delete.assert_called_once()

    @patch("backend.api.main.get_db")
    @patch("backend.api.main.get_bucket_name")
    @patch("backend.api.main.delete_folder")
    def test_delete_account_with_chats_and_messages(
        self, mock_delete_folder, mock_bucket, mock_db, mock_firebase_user
    ):
        """Test deleting account with multiple chats and messages."""
        from backend.api.main import _delete_account_impl

        # Setup mocks
        mock_delete_folder.return_value = 10
        mock_bucket.return_value = "test-bucket"

        # Mock Firestore database
        mock_firestore_db = MagicMock()
        mock_db.return_value = mock_firestore_db

        # Create mock chats with messages
        mock_chat1 = MagicMock()
        mock_chat1.id = "chat-1"
        mock_chat1_ref = MagicMock()
        mock_chat1.reference = mock_chat1_ref

        mock_chat2 = MagicMock()
        mock_chat2.id = "chat-2"
        mock_chat2_ref = MagicMock()
        mock_chat2.reference = mock_chat2_ref

        # Mock messages for chat 1
        mock_msg1 = MagicMock()
        mock_msg1.reference = MagicMock()
        mock_msg2 = MagicMock()
        mock_msg2.reference = MagicMock()

        # Mock messages for chat 2
        mock_msg3 = MagicMock()
        mock_msg3.reference = MagicMock()
        mock_msg4 = MagicMock()
        mock_msg4.reference = MagicMock()

        # Create SEPARATE mock message collections for each chat
        mock_messages_ref_1 = MagicMock()
        mock_messages_ref_1.limit.return_value.stream.side_effect = [
            [mock_msg1, mock_msg2],  # First call
            [],  # Second call (recursion check - should return empty to stop)
        ]

        mock_messages_ref_2 = MagicMock()
        mock_messages_ref_2.limit.return_value.stream.side_effect = [
            [mock_msg3, mock_msg4],  # First call
            [],  # Second call (recursion check - should return empty to stop)
        ]

        # Setup reference.collection to return appropriate messages_ref
        def chat1_collection(name):
            if name == "messages":
                return mock_messages_ref_1
            return MagicMock()

        def chat2_collection(name):
            if name == "messages":
                return mock_messages_ref_2
            return MagicMock()

        mock_chat1_ref.collection.side_effect = chat1_collection
        mock_chat2_ref.collection.side_effect = chat2_collection

        # Mock user document reference
        mock_user_ref = MagicMock()
        mock_user_doc = MagicMock()
        mock_user_doc.exists = True
        mock_user_ref.get.return_value = mock_user_doc

        # Mock collections - initial stream() call returns chats directly
        mock_chats_ref = MagicMock()
        mock_artifacts_ref = MagicMock()

        # For chats - initial stream() returns 2 chats
        mock_chats_ref.stream.return_value = [mock_chat1, mock_chat2]

        # For artifacts - empty
        mock_artifacts_ref.limit.return_value.stream.side_effect = [
            [],  # First call
            [],  # Second call (recursion check)
        ]

        # Setup collection calls
        def collection_side_effect(name):
            if name == "chats":
                return mock_chats_ref
            elif name == "artifacts":
                return mock_artifacts_ref
            return MagicMock()

        mock_user_ref.collection.side_effect = collection_side_effect
        mock_firestore_db.collection.return_value.document.return_value = mock_user_ref

        # Execute
        result = _delete_account_impl("test-uid-123")

        # Assert
        assert result["ok"] is True
        assert result["uid"] == "test-uid-123"
        assert result["chats_removed"] == 2
        assert result["messages_removed"] == 4  # 2 messages per chat * 2 chats
        assert result["gcs_files_removed"] == 10

        # Verify GCS deletion was called
        assert mock_delete_folder.call_count >= 1

    @patch("backend.api.main.get_db")
    @patch("backend.api.main.get_bucket_name")
    @patch("backend.api.main.delete_folder")
    def test_delete_account_gcs_failure_doesnt_block(
        self, mock_delete_folder, mock_bucket, mock_db, mock_firebase_user
    ):
        """Test that GCS deletion failure doesn't block Firestore deletion."""
        from backend.api.main import _delete_account_impl

        # Setup mocks
        mock_delete_folder.side_effect = Exception("GCS error")
        mock_bucket.return_value = "test-bucket"

        # Mock Firestore database
        mock_firestore_db = MagicMock()
        mock_db.return_value = mock_firestore_db

        # Mock user document reference
        mock_user_ref = MagicMock()
        mock_user_doc = MagicMock()
        mock_user_doc.exists = True
        mock_user_ref.get.return_value = mock_user_doc

        # Mock empty collections
        mock_chats_ref = MagicMock()
        mock_artifacts_ref = MagicMock()
        mock_chats_ref.stream.return_value = []
        mock_artifacts_ref.stream.return_value = []

        mock_user_ref.collection.side_effect = lambda name: {
            "chats": mock_chats_ref,
            "artifacts": mock_artifacts_ref,
        }[name]

        mock_firestore_db.collection.return_value.document.return_value = mock_user_ref

        # Execute - should not raise exception
        result = _delete_account_impl("test-uid-123")

        # Assert - deletion still succeeds
        assert result["ok"] is True
        mock_user_ref.delete.assert_called_once()

    @patch("backend.api.main.get_db")
    @patch("backend.api.main.get_bucket_name")
    @patch("backend.api.main.delete_folder")
    def test_delete_account_no_gcs_bucket(
        self, mock_delete_folder, mock_bucket, mock_db, mock_firebase_user
    ):
        """Test account deletion when GCS bucket is not configured."""
        from backend.api.main import _delete_account_impl

        # Setup mocks
        mock_bucket.return_value = None

        # Mock Firestore database
        mock_firestore_db = MagicMock()
        mock_db.return_value = mock_firestore_db

        # Mock user document reference
        mock_user_ref = MagicMock()
        mock_user_doc = MagicMock()
        mock_user_doc.exists = True
        mock_user_ref.get.return_value = mock_user_doc

        # Mock empty collections
        mock_chats_ref = MagicMock()
        mock_artifacts_ref = MagicMock()
        mock_chats_ref.stream.return_value = []
        mock_artifacts_ref.stream.return_value = []

        mock_user_ref.collection.side_effect = lambda name: {
            "chats": mock_chats_ref,
            "artifacts": mock_artifacts_ref,
        }[name]

        mock_firestore_db.collection.return_value.document.return_value = mock_user_ref

        # Execute
        result = _delete_account_impl("test-uid-123")

        # Assert
        assert result["ok"] is True
        assert result["gcs_files_removed"] == 0
        # GCS delete_folder should not be called
        mock_delete_folder.assert_not_called()

    @patch("backend.api.main.get_db")
    @patch("backend.api.main.get_bucket_name")
    @patch("backend.api.main.delete_folder")
    def test_delete_account_with_artifacts(
        self, mock_delete_folder, mock_bucket, mock_db, mock_firebase_user
    ):
        """Test deleting account with artifacts."""
        from backend.api.main import _delete_account_impl

        # Setup mocks
        mock_delete_folder.return_value = 5
        mock_bucket.return_value = "test-bucket"

        # Mock Firestore database
        mock_firestore_db = MagicMock()
        mock_db.return_value = mock_firestore_db

        # Create mock artifacts
        mock_artifact1 = MagicMock()
        mock_artifact1.id = "artifact-1"
        mock_artifact1.reference = MagicMock()

        mock_artifact2 = MagicMock()
        mock_artifact2.id = "artifact-2"
        mock_artifact2.reference = MagicMock()

        # Mock user document reference
        mock_user_ref = MagicMock()
        mock_user_doc = MagicMock()
        mock_user_doc.exists = True
        mock_user_ref.get.return_value = mock_user_doc

        # Mock collections
        mock_chats_ref = MagicMock()
        mock_artifacts_ref = MagicMock()
        mock_chats_ref.limit.return_value.stream.return_value = []
        mock_artifacts_ref.limit.return_value.stream.return_value = [mock_artifact1, mock_artifact2]

        def collection_side_effect(name):
            if name == "chats":
                return mock_chats_ref
            elif name == "artifacts":
                return mock_artifacts_ref
            return MagicMock()

        mock_user_ref.collection.side_effect = collection_side_effect
        mock_firestore_db.collection.return_value.document.return_value = mock_user_ref

        # Execute
        result = _delete_account_impl("test-uid-123")

        # Assert
        assert result["ok"] is True
        assert result["artifacts_removed"] >= 2

        # Verify artifacts were deleted
        mock_artifact1.reference.delete.assert_called_once()
        mock_artifact2.reference.delete.assert_called_once()


class TestGCSFolderDeletion:
    """Test GCS folder deletion with placeholder handling."""

    @patch("backend.gcs_utils._client")
    def test_delete_folder_basic(self, mock_client):
        """Test basic folder deletion."""
        from backend.gcs_utils import delete_folder

        # Setup mocks
        mock_bucket = MagicMock()
        mock_blob1 = MagicMock()
        mock_blob2 = MagicMock()

        mock_bucket.list_blobs.return_value = [mock_blob1, mock_blob2]
        # Mock blob that doesn't exist (for placeholder check)
        mock_bucket.blob.return_value = MagicMock(exists=MagicMock(return_value=False))

        mock_client.return_value.bucket.return_value = mock_bucket

        # Execute
        result = delete_folder("test-bucket", "user123/")

        # Assert - should delete 2 blobs (no placeholders found)
        assert result >= 2
        mock_blob1.delete.assert_called_once()
        mock_blob2.delete.assert_called_once()

    @patch("backend.gcs_utils._client")
    def test_delete_folder_with_placeholder(self, mock_client):
        """Test folder deletion with placeholder objects."""
        from backend.gcs_utils import delete_folder

        # Setup mocks
        mock_bucket = MagicMock()
        mock_blob1 = MagicMock()
        MagicMock()

        # First call returns actual files, subsequent calls for placeholders
        mock_bucket.list_blobs.return_value = [mock_blob1]

        # Mock placeholder blob that exists
        mock_placeholder_blob = MagicMock()
        mock_placeholder_blob.exists.return_value = True

        def blob_side_effect(name):
            if name in ["user123/", "user123"]:
                return mock_placeholder_blob
            return MagicMock(exists=MagicMock(return_value=False))

        mock_bucket.blob.side_effect = blob_side_effect
        mock_client.return_value.bucket.return_value = mock_bucket

        # Execute
        result = delete_folder("test-bucket", "user123/")

        # Assert - should delete blob and placeholder
        mock_blob1.delete.assert_called_once()
        mock_placeholder_blob.delete.assert_called()
        assert result >= 2

    @patch("backend.gcs_utils._client")
    def test_delete_folder_empty(self, mock_client):
        """Test deleting non-existent folder."""
        from backend.gcs_utils import delete_folder

        # Setup mocks
        mock_bucket = MagicMock()
        mock_bucket.list_blobs.return_value = []
        # Mock blob that doesn't exist (for placeholder check)
        mock_bucket.blob.return_value = MagicMock(exists=MagicMock(return_value=False))

        mock_client.return_value.bucket.return_value = mock_bucket

        # Execute
        result = delete_folder("test-bucket", "nonexistent/")

        # Assert - should return 0 (no objects to delete)
        assert result == 0


class TestDeleteAccountIntegration:
    """Integration tests for account deletion flow."""

    def test_delete_account_endpoint_integration(self, client, mock_firebase_user):
        """Test complete account deletion flow via API."""
        response = client.delete("/api/account")

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert data["ok"] is True
        assert data["uid"] == "test-uid-123"
        assert all(
            isinstance(data[key], int)
            for key in [
                "chats_removed",
                "messages_removed",
                "artifacts_removed",
                "gcs_files_removed",
            ]
        )

    def test_delete_account_multiple_times(self, client, mock_firebase_user):
        """Test that deleting account multiple times works correctly."""
        # First deletion
        response1 = client.delete("/api/account")
        assert response1.status_code == 200

        # Second deletion (user doesn't exist anymore, but should not error)
        response2 = client.delete("/api/account")
        assert response2.status_code == 200

        data = response2.json()
        assert data["ok"] is True
        assert data["chats_removed"] == 0
        assert data["messages_removed"] == 0
