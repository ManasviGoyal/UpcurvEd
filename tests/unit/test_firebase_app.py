"""Unit tests for firebase_app module."""

from unittest.mock import MagicMock, patch


class TestInitFirebase:
    """Test Firebase initialization."""

    @patch("backend.firebase_app.firestore")
    @patch("backend.firebase_app.firebase_admin")
    def test_init_firebase_creates_db(self, mock_admin, mock_firestore):
        """Test that init_firebase creates Firestore client."""
        import backend.firebase_app

        # Reset globals
        backend.firebase_app._app = None
        backend.firebase_app._db = None

        mock_client = MagicMock()
        mock_firestore.client.return_value = mock_client
        mock_admin.get_app.side_effect = ValueError("No app")
        mock_admin._apps = {}

        result = backend.firebase_app.init_firebase()

        assert result == mock_client
        mock_firestore.client.assert_called_once()

    @patch("backend.firebase_app.firestore")
    @patch("backend.firebase_app.firebase_admin")
    def test_init_firebase_returns_cached_db(self, mock_admin, mock_firestore):
        """Test that init_firebase returns cached client."""
        import backend.firebase_app

        mock_client = MagicMock()
        backend.firebase_app._db = mock_client

        result = backend.firebase_app.init_firebase()

        assert result == mock_client
        # Should not create new client
        mock_firestore.client.assert_not_called()

        # Reset for other tests
        backend.firebase_app._db = None

    @patch("backend.firebase_app.firestore")
    @patch("backend.firebase_app.firebase_admin")
    def test_init_firebase_uses_existing_app(self, mock_admin, mock_firestore):
        """Test that init_firebase uses existing default app."""
        import backend.firebase_app

        backend.firebase_app._app = None
        backend.firebase_app._db = None

        mock_app = MagicMock()
        mock_admin.get_app.return_value = mock_app
        mock_admin._apps = {backend.firebase_app._APP_NAME: mock_app}

        backend.firebase_app.init_firebase()

        # Should not try to initialize new app since one exists
        mock_admin.initialize_app.assert_not_called()

        # Reset
        backend.firebase_app._app = None
        backend.firebase_app._db = None

    @patch("backend.firebase_app.firestore")
    @patch("backend.firebase_app.firebase_admin")
    @patch("backend.firebase_app.credentials")
    @patch("os.environ.get")
    @patch("os.path.isfile")
    def test_init_with_json_credentials(
        self, mock_isfile, mock_env_get, mock_creds, mock_admin, mock_firestore
    ):
        """Test initialization with JSON credentials file."""
        import backend.firebase_app

        backend.firebase_app._app = None
        backend.firebase_app._db = None

        mock_env_get.return_value = "/path/to/creds.json"
        mock_isfile.return_value = True
        mock_admin.get_app.side_effect = ValueError("No app")
        mock_admin._apps = {}

        backend.firebase_app.init_firebase()

        mock_creds.Certificate.assert_called_once_with("/path/to/creds.json")

        # Reset
        backend.firebase_app._app = None
        backend.firebase_app._db = None


class TestGetDb:
    """Test get_db function."""

    @patch("backend.firebase_app.init_firebase")
    def test_get_db_calls_init(self, mock_init):
        """Test that get_db calls init_firebase."""
        from backend.firebase_app import get_db

        mock_client = MagicMock()
        mock_init.return_value = mock_client

        result = get_db()

        assert result == mock_client
        mock_init.assert_called_once()


class TestAppName:
    """Test app naming."""

    def test_app_name_constant(self):
        """Test that APP_NAME is set correctly."""
        from backend.firebase_app import _APP_NAME

        assert _APP_NAME == "ac215-core"
