"""Comprehensive unit tests targeting ALL missing statement lines specified by user."""

import os
from unittest.mock import MagicMock, patch

import pytest


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
