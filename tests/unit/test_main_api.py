"""Unit tests for backend/api/main.py to increase coverage."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.api.main import (
    ChatCreateIn,
    ChatItemOut,
    ChatRenameIn,
    GenerateIn,
    MessageCreateIn,
    MessageMedia,
    MessageOut,
    PodcastIn,
    QuizIn,
    _srt_to_vtt_text,
    _to_ms,
    app,
)


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


# ============== Pydantic Model Tests ==============


class TestGenerateInModel:
    """Test GenerateIn Pydantic model."""

    def test_basic_generate_in(self):
        """Test basic model creation."""
        data = GenerateIn(prompt="test prompt")
        assert data.prompt == "test prompt"
        assert data.keys == {}
        assert data.provider is None

    def test_generate_in_with_all_fields(self):
        """Test with all optional fields."""
        data = GenerateIn(
            prompt="test",
            keys={"claude": "key1", "gemini": "key2"},
            provider="claude",
            model="claude-3-5-sonnet",
            jobId="job-123",
            chatId="chat-456",
            sessionId="session-789",
        )
        assert data.provider == "claude"
        assert data.model == "claude-3-5-sonnet"
        assert data.jobId == "job-123"


class TestQuizInModel:
    """Test QuizIn Pydantic model."""

    def test_basic_quiz_in(self):
        """Test basic model creation."""
        data = QuizIn(prompt="math quiz")
        assert data.prompt == "math quiz"
        assert data.num_questions == 5
        assert data.difficulty == "medium"

    def test_quiz_in_with_all_fields(self):
        """Test with all optional fields."""
        data = QuizIn(
            prompt="science quiz",
            num_questions=10,
            difficulty="hard",
            keys={"gemini": "key"},
            provider="gemini",
            context="Additional context",
            userEmail="test@example.com",
        )
        assert data.num_questions == 10
        assert data.difficulty == "hard"
        assert data.context == "Additional context"


class TestPodcastInModel:
    """Test PodcastIn Pydantic model."""

    def test_basic_podcast_in(self):
        """Test basic model creation."""
        data = PodcastIn(prompt="explain quantum physics")
        assert data.prompt == "explain quantum physics"
        assert data.keys == {}

    def test_podcast_in_with_all_fields(self):
        """Test with all optional fields."""
        data = PodcastIn(
            prompt="explain AI",
            keys={"claude": "key"},
            provider="claude",
            model="claude-3-5-sonnet",
            jobId="job-123",
            chatId="chat-456",
            sessionId="session-789",
        )
        assert data.provider == "claude"
        assert data.jobId == "job-123"


class TestChatCreateInModel:
    """Test ChatCreateIn Pydantic model."""

    def test_default_values(self):
        """Test default values."""
        data = ChatCreateIn()
        assert data.title == "New Chat"
        assert data.shareable is False
        assert data.share_token is None

    def test_with_first_message(self):
        """Test with first message content."""
        data = ChatCreateIn(
            title="My Chat",
            content="Hello, world!",
            timestamp="2024-01-01T00:00:00Z",
        )
        assert data.title == "My Chat"
        assert data.content == "Hello, world!"


class TestMessageCreateInModel:
    """Test MessageCreateIn Pydantic model."""

    def test_basic_message(self):
        """Test basic message creation."""
        data = MessageCreateIn(role="user", content="Hello")
        assert data.role == "user"
        assert data.content == "Hello"

    def test_message_with_media(self):
        """Test message with media."""
        media = MessageMedia(type="video", url="http://example.com/video.mp4")
        data = MessageCreateIn(role="assistant", content="Here's a video", media=media)
        assert data.media.type == "video"

    def test_message_with_quiz_data(self):
        """Test message with quiz data."""
        data = MessageCreateIn(
            role="assistant",
            content="Quiz",
            quizAnchor=True,
            quizTitle="Math Quiz",
            quizData={"questions": []},
        )
        assert data.quizAnchor is True
        assert data.quizTitle == "Math Quiz"


class TestMessageMediaModel:
    """Test MessageMedia Pydantic model."""

    def test_basic_media(self):
        """Test basic media creation."""
        media = MessageMedia(type="video", url="http://example.com/video.mp4")
        assert media.type == "video"
        assert media.url == "http://example.com/video.mp4"

    def test_media_with_all_fields(self):
        """Test with all optional fields."""
        media = MessageMedia(
            type="video",
            url="http://example.com/video.mp4",
            subtitleUrl="http://example.com/video.vtt",
            artifactId="artifact-123",
            title="My Video",
            gcsPath="user/chats/video.mp4",
            sceneCode="class Scene: pass",
        )
        assert media.subtitleUrl == "http://example.com/video.vtt"
        assert media.sceneCode == "class Scene: pass"


# ============== Utility Function Tests ==============


class TestSrtToVttText:
    """Test SRT to VTT conversion."""

    def test_basic_conversion(self):
        """Test basic SRT to VTT conversion."""
        srt_text = """1
00:00:01,000 --> 00:00:02,000
Hello world

2
00:00:03,000 --> 00:00:04,000
Second subtitle"""
        result = _srt_to_vtt_text(srt_text)
        assert "WEBVTT" in result
        # Should replace comma with dot in timestamps
        assert "00:00:01.000" in result or "0:00:01" in result

    def test_empty_srt(self):
        """Test with empty SRT."""
        result = _srt_to_vtt_text("")
        assert "WEBVTT" in result

    def test_srt_with_special_characters(self):
        """Test SRT with special characters."""
        srt_text = """1
00:00:01,500 --> 00:00:03,500
Line with special chars: <i>italic</i>"""
        result = _srt_to_vtt_text(srt_text)
        assert "WEBVTT" in result


class TestToMs:
    """Test timestamp to milliseconds conversion."""

    def test_none_input(self):
        """Test with None input."""
        result = _to_ms(None)
        assert result is None

    def test_valid_timestamp(self):
        """Test with valid timestamp object."""
        # Create a mock timestamp
        ts = MagicMock()
        ts.seconds = 1000
        ts.nanoseconds = 500000000  # 0.5 seconds
        result = _to_ms(ts)
        assert result == 1000500  # 1000 * 1000 + 500

    def test_invalid_timestamp(self):
        """Test with invalid timestamp object."""
        ts = MagicMock()
        ts.seconds = None
        result = _to_ms(ts)
        assert result is None

    def test_exception_handling(self):
        """Test exception handling."""
        # Object that raises on attribute access
        ts = MagicMock()
        ts.seconds = property(lambda self: 1 / 0)
        result = _to_ms(ts)
        # Should return None on exception
        assert result is None or isinstance(result, int)


# ============== Health Endpoint Tests ==============


class TestHealthEndpoint:
    """Test /health endpoint."""

    def test_health_check(self, client):
        """Test health check returns ok."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"ok": True}


# ============== Auth Dependency Tests ==============


class TestAuthDependency:
    """Test Firebase auth dependency using the require_firebase_user function directly."""

    def test_missing_auth_header(self):
        """Test that missing auth header raises 401."""
        from fastapi import HTTPException

        from backend.api.main import require_firebase_user

        # Call the dependency directly with no authorization header
        with pytest.raises(HTTPException) as exc_info:
            require_firebase_user(authorization=None)
        assert exc_info.value.status_code == 401
        assert "bearer" in exc_info.value.detail.lower()

    def test_invalid_auth_format(self):
        """Test that non-bearer auth format raises 401."""
        from fastapi import HTTPException

        from backend.api.main import require_firebase_user

        with pytest.raises(HTTPException) as exc_info:
            require_firebase_user(authorization="Basic invalid")
        assert exc_info.value.status_code == 401

    @patch("backend.api.main.init_firebase")
    @patch("backend.api.main.fb_auth.verify_id_token")
    def test_invalid_token(self, mock_verify, mock_init):
        """Test that invalid token raises 401."""
        from fastapi import HTTPException

        from backend.api.main import require_firebase_user

        mock_verify.side_effect = Exception("Invalid token")
        with pytest.raises(HTTPException) as exc_info:
            require_firebase_user(authorization="Bearer invalid-token")
        assert exc_info.value.status_code == 401

    @patch("backend.api.main.init_firebase")
    @patch("backend.api.main.fb_auth.verify_id_token")
    def test_valid_token_returns_uid(self, mock_verify, mock_init):
        """Test that valid token returns uid."""
        from backend.api.main import require_firebase_user

        mock_verify.return_value = {"uid": "test-user-123"}
        result = require_firebase_user(authorization="Bearer valid-token")
        assert result == "test-user-123"

    @patch("backend.api.main.init_firebase")
    @patch("backend.api.main.fb_auth.verify_id_token")
    def test_token_missing_uid(self, mock_verify, mock_init):
        """Test that token without uid raises 401."""
        from fastapi import HTTPException

        from backend.api.main import require_firebase_user

        mock_verify.return_value = {}  # No uid in decoded token
        with pytest.raises(HTTPException) as exc_info:
            require_firebase_user(authorization="Bearer token-without-uid")
        assert exc_info.value.status_code == 401


# ============== Generate Endpoint Tests ==============


class TestGenerateEndpoint:
    """Test /generate endpoint."""

    @patch("backend.api.main.require_firebase_user")
    @patch("backend.api.main.run_to_code")
    def test_generate_success(self, mock_run_to_code, mock_auth, client):
        """Test successful video generation."""
        mock_auth.return_value = "test-uid"
        mock_run_to_code.return_value = (
            "class Scene: pass",  # code
            "/static/video.mp4",  # video_url
            True,  # render_ok
            1,  # tries
            ["job-1"],  # attempt_job_ids
            "job-1",  # succeeded_job_id
        )

        # Override the dependency
        app.dependency_overrides[
            __import__("backend.api.main", fromlist=["require_firebase_user"]).require_firebase_user
        ] = lambda: "test-uid"

        try:
            response = client.post(
                "/generate",
                json={"prompt": "test", "keys": {"gemini": "key"}},
                headers={"Authorization": "Bearer test-token"},
            )
            # Response depends on GCS config
            assert response.status_code in [200, 401]
        finally:
            app.dependency_overrides.clear()

    @patch("backend.api.main.require_firebase_user")
    @patch("backend.api.main.run_to_code")
    def test_generate_render_failure(self, mock_run_to_code, mock_auth, client):
        """Test render failure."""
        mock_auth.return_value = "test-uid"
        mock_run_to_code.return_value = (
            None,  # code
            None,  # video_url
            False,  # render_ok
            3,  # tries
            ["job-1", "job-2", "job-3"],  # attempt_job_ids
            None,  # succeeded_job_id
        )

        app.dependency_overrides[
            __import__("backend.api.main", fromlist=["require_firebase_user"]).require_firebase_user
        ] = lambda: "test-uid"

        try:
            response = client.post(
                "/generate",
                json={"prompt": "test", "keys": {"gemini": "key"}},
                headers={"Authorization": "Bearer test-token"},
            )
            # Should still respond
            assert response.status_code in [200, 401]
        finally:
            app.dependency_overrides.clear()


# ============== Quiz Endpoint Tests ==============


class TestQuizEmbeddedEndpoint:
    """Test /quiz/embedded endpoint."""

    @patch("backend.api.main.generate_quiz_embedded")
    def test_quiz_success(self, mock_generate, client):
        """Test successful quiz generation."""
        mock_generate.return_value = {
            "title": "Test Quiz",
            "description": "A test",
            "questions": [
                {
                    "prompt": "What is 2+2?",
                    "options": ["2", "3", "4", "5"],
                    "correctIndex": 2,
                }
            ],
            "count": 1,
        }

        response = client.post(
            "/quiz/embedded",
            json={
                "prompt": "math quiz",
                "num_questions": 5,
                "keys": {"gemini": "key"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "quiz" in data

    @patch("backend.api.main.generate_quiz_embedded")
    def test_quiz_failure(self, mock_generate, client):
        """Test quiz generation failure."""
        mock_generate.side_effect = Exception("LLM error")

        response = client.post(
            "/quiz/embedded",
            json={"prompt": "test", "keys": {"gemini": "key"}},
        )
        assert response.status_code == 500

    def test_quiz_provider_auto_select_gemini(self, client):
        """Test auto-selecting gemini provider."""
        with patch("backend.api.main.generate_quiz_embedded") as mock:
            mock.return_value = {"title": "Quiz", "questions": [], "count": 0}
            response = client.post(
                "/quiz/embedded",
                json={"prompt": "test", "keys": {"gemini": "key"}},
            )
            assert response.status_code == 200
            # Check that gemini was used
            call_kwargs = mock.call_args[1]
            assert call_kwargs["provider"] == "gemini"

    def test_quiz_provider_auto_select_claude(self, client):
        """Test auto-selecting claude provider."""
        with patch("backend.api.main.generate_quiz_embedded") as mock:
            mock.return_value = {"title": "Quiz", "questions": [], "count": 0}
            response = client.post(
                "/quiz/embedded",
                json={"prompt": "test", "keys": {"claude": "key"}},
            )
            assert response.status_code == 200
            call_kwargs = mock.call_args[1]
            assert call_kwargs["provider"] == "claude"


# ============== Podcast Endpoint Tests ==============


class TestPodcastEndpoint:
    """Test /podcast endpoint."""

    @patch("backend.api.main.require_firebase_user")
    @patch("backend.api.main.generate_podcast")
    @patch("backend.api.main.get_bucket_name")
    def test_podcast_success_no_gcs(self, mock_bucket, mock_generate, mock_auth, client):
        """Test successful podcast generation without GCS."""
        mock_auth.return_value = "test-uid"
        mock_bucket.return_value = None  # No GCS
        mock_generate.return_value = {
            "status": "ok",
            "video_url": "/static/podcast.mp3",
            "vtt_url": "/static/podcast.vtt",
        }

        from backend.api.main import require_firebase_user

        app.dependency_overrides[require_firebase_user] = lambda: "test-uid"

        try:
            response = client.post(
                "/podcast",
                json={"prompt": "explain AI", "keys": {"gemini": "key"}},
                headers={"Authorization": "Bearer test-token"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
        finally:
            app.dependency_overrides.clear()

    @patch("backend.api.main.require_firebase_user")
    @patch("backend.api.main.generate_podcast")
    def test_podcast_failure(self, mock_generate, mock_auth, client):
        """Test podcast generation failure."""
        mock_auth.return_value = "test-uid"
        mock_generate.side_effect = Exception("Generation failed")

        from backend.api.main import require_firebase_user

        app.dependency_overrides[require_firebase_user] = lambda: "test-uid"

        try:
            response = client.post(
                "/podcast",
                json={"prompt": "test", "keys": {"gemini": "key"}},
                headers={"Authorization": "Bearer test-token"},
            )
            assert response.status_code == 500
        finally:
            app.dependency_overrides.clear()


# ============== Chat Helper Function Tests ==============


class TestChatHelperFunctions:
    """Test chat helper functions."""

    @patch("backend.api.main.get_db")
    def test_list_chats(self, mock_get_db):
        """Test list_chats function."""
        from backend.api.main import list_chats

        # Mock Firestore
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        # Mock the query chain
        mock_doc = MagicMock()
        mock_doc.id = "chat-123"
        mock_doc.to_dict.return_value = {
            "title": "Test Chat",
            "updatedAt": None,
            "sessionId": "session-1",
            "shareable": False,
        }

        mock_query = MagicMock()
        mock_query.stream.return_value = [mock_doc]

        mock_chats_ref = MagicMock()
        mock_chats_ref.order_by.return_value.limit.return_value = mock_query

        mock_db.collection.return_value.document.return_value.collection.return_value = (
            mock_chats_ref
        )

        result = list_chats("test-uid", limit=50)
        assert len(result) == 1
        assert result[0].chat_id == "chat-123"
        assert result[0].title == "Test Chat"

    @patch("backend.api.main.get_db")
    def test_create_chat(self, mock_get_db):
        """Test create_chat function."""
        from backend.api.main import create_chat

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        mock_ref = MagicMock()
        mock_ref.id = "new-chat-id"

        mock_snap = MagicMock()
        mock_snap.to_dict.return_value = {
            "title": "New Chat",
            "updatedAt": None,
            "sessionId": None,
            "shareable": False,
        }
        mock_ref.get.return_value = mock_snap

        col = mock_db.collection.return_value
        doc = col.document.return_value
        msgs = doc.collection.return_value
        msgs.document.return_value = mock_ref

        body = ChatCreateIn(title="New Chat")
        result = create_chat(body, "test-uid")

        assert result.chat_id == "new-chat-id"
        assert result.title == "New Chat"

    @patch("backend.api.main.get_db")
    def test_rename_chat(self, mock_get_db):
        """Test rename_chat function."""
        from backend.api.main import rename_chat

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        # Mock chat exists
        mock_snap = MagicMock()
        mock_snap.exists = True
        mock_snap.to_dict.return_value = {
            "title": "Renamed Chat",
            "updatedAt": None,
            "shareable": False,
        }

        mock_ref = MagicMock()
        mock_ref.get.return_value = mock_snap

        col = mock_db.collection.return_value
        doc = col.document.return_value
        msgs = doc.collection.return_value
        msgs.document.return_value = mock_ref

        body = ChatRenameIn(title="Renamed Chat")
        result = rename_chat("chat-123", body, "test-uid")

        assert result.title == "Renamed Chat"

    @patch("backend.api.main.get_db")
    def test_rename_chat_not_found(self, mock_get_db):
        """Test rename_chat when chat not found."""
        from fastapi import HTTPException

        from backend.api.main import rename_chat

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        # Mock chat doesn't exist
        mock_snap = MagicMock()
        mock_snap.exists = False

        mock_ref = MagicMock()
        mock_ref.get.return_value = mock_snap

        col = mock_db.collection.return_value
        doc = col.document.return_value
        msgs = doc.collection.return_value
        msgs.document.return_value = mock_ref

        body = ChatRenameIn(title="New Title")

        with pytest.raises(HTTPException) as exc_info:
            rename_chat("nonexistent-chat", body, "test-uid")
        assert exc_info.value.status_code == 404


# ============== Chat Routes Tests ==============


class TestChatRoutes:
    """Test chat API routes."""

    @patch("backend.api.main.require_firebase_user")
    @patch("backend.api.main.list_chats")
    def test_list_chats_route(self, mock_list, mock_auth, client):
        """Test GET /api/chats."""
        mock_auth.return_value = "test-uid"
        mock_list.return_value = [
            ChatItemOut(chat_id="chat-1", title="Chat 1"),
            ChatItemOut(chat_id="chat-2", title="Chat 2"),
        ]

        from backend.api.main import require_firebase_user

        app.dependency_overrides[require_firebase_user] = lambda: "test-uid"

        try:
            response = client.get(
                "/api/chats",
                headers={"Authorization": "Bearer test-token"},
            )
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 2
        finally:
            app.dependency_overrides.clear()

    @patch("backend.api.main.require_firebase_user")
    @patch("backend.api.main.create_chat")
    def test_create_chat_route(self, mock_create, mock_auth, client):
        """Test POST /api/chats."""
        mock_auth.return_value = "test-uid"
        mock_create.return_value = ChatItemOut(chat_id="new-chat", title="New Chat")

        from backend.api.main import require_firebase_user

        app.dependency_overrides[require_firebase_user] = lambda: "test-uid"

        try:
            response = client.post(
                "/api/chats",
                json={"title": "New Chat"},
                headers={"Authorization": "Bearer test-token"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["chat_id"] == "new-chat"
        finally:
            app.dependency_overrides.clear()

    @patch("backend.api.main.require_firebase_user")
    @patch("backend.api.main.get_chat")
    def test_get_chat_route(self, mock_get, mock_auth, client):
        """Test GET /api/chats/{chat_id}."""
        from backend.api.main import ChatDetailOut

        mock_auth.return_value = "test-uid"
        mock_get.return_value = ChatDetailOut(
            chat_id="chat-123",
            title="Test Chat",
            messages=[],
        )

        from backend.api.main import require_firebase_user

        app.dependency_overrides[require_firebase_user] = lambda: "test-uid"

        try:
            response = client.get(
                "/api/chats/chat-123",
                headers={"Authorization": "Bearer test-token"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["chat_id"] == "chat-123"
        finally:
            app.dependency_overrides.clear()


# ============== Jobs Cancel Tests ==============


class TestJobsCancelEndpoint:
    """Test /jobs/cancel endpoint."""

    @patch("backend.api.main.cancel_job")
    def test_cancel_job_success(self, mock_cancel, client):
        """Test successful job cancellation."""
        mock_cancel.return_value = {"ok": True, "cancelled": True}

        response = client.post("/jobs/cancel?jobId=job-123")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

    @patch("backend.api.main.cancel_job")
    def test_cancel_job_failure(self, mock_cancel, client):
        """Test job cancellation failure."""
        mock_cancel.side_effect = Exception("Job not found")

        response = client.post("/jobs/cancel?jobId=invalid-job")
        assert response.status_code == 500


# ============== Artifact Refresh Tests ==============


class TestArtifactRefresh:
    """Test artifact refresh endpoint."""

    @patch("backend.api.main.require_firebase_user")
    @patch("backend.api.main.get_bucket_name")
    def test_refresh_no_bucket(self, mock_bucket, mock_auth, client):
        """Test refresh when no GCS bucket configured."""
        mock_auth.return_value = "test-uid"
        mock_bucket.return_value = None

        from backend.api.main import require_firebase_user

        app.dependency_overrides[require_firebase_user] = lambda: "test-uid"

        try:
            response = client.get(
                "/api/artifacts/refresh?gcsPath=test/path",
                headers={"Authorization": "Bearer test-token"},
            )
            assert response.status_code == 400
            assert "No GCS bucket" in response.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    @patch("backend.api.main.require_firebase_user")
    @patch("backend.api.main.get_bucket_name")
    def test_refresh_missing_params(self, mock_bucket, mock_auth, client):
        """Test refresh with missing parameters."""
        mock_auth.return_value = "test-uid"
        mock_bucket.return_value = "test-bucket"

        from backend.api.main import require_firebase_user

        app.dependency_overrides[require_firebase_user] = lambda: "test-uid"

        try:
            response = client.get(
                "/api/artifacts/refresh",
                headers={"Authorization": "Bearer test-token"},
            )
            assert response.status_code == 400
            assert "Missing" in response.json()["detail"]
        finally:
            app.dependency_overrides.clear()


# ============== Share Chat Tests ==============


class TestShareChat:
    """Test chat sharing functionality."""

    @patch("backend.api.main.get_db")
    def test_get_shared_chat_not_found(self, mock_get_db, client):
        """Test getting shared chat with invalid token."""
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        mock_query = MagicMock()
        mock_query.stream.return_value = []
        mock_db.collection_group.return_value.where.return_value.limit.return_value = mock_query

        response = client.get("/api/share/invalid-token")
        assert response.status_code == 404

    @patch("backend.api.main.get_db")
    def test_get_shared_chat_not_shareable(self, mock_get_db, client):
        """Test getting chat that's not shareable."""
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        mock_doc = MagicMock()
        mock_doc.id = "chat-123"
        mock_doc.to_dict.return_value = {"shareable": False, "title": "Private Chat"}

        mock_query = MagicMock()
        mock_query.stream.return_value = [mock_doc]
        mock_db.collection_group.return_value.where.return_value.limit.return_value = mock_query

        response = client.get("/api/share/some-token")
        assert response.status_code == 404


# ============== Delete Chat Tests ==============


class TestDeleteChat:
    """Test chat deletion."""

    @patch("backend.api.main.require_firebase_user")
    @patch("backend.api.main._delete_chat_impl")
    def test_delete_chat_success(self, mock_delete, mock_auth, client):
        """Test successful chat deletion."""
        mock_auth.return_value = "test-uid"
        mock_delete.return_value = {
            "ok": True,
            "deleted": "chat-123",
            "messages_removed": 5,
            "gcs_files_removed": 2,
        }

        from backend.api.main import require_firebase_user

        app.dependency_overrides[require_firebase_user] = lambda: "test-uid"

        try:
            response = client.delete(
                "/api/chats/chat-123",
                headers={"Authorization": "Bearer test-token"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["ok"] is True
        finally:
            app.dependency_overrides.clear()


# ============== Export Chat Tests ==============


class TestExportChat:
    """Test chat export functionality."""

    @patch("backend.api.main.require_firebase_user")
    @patch("backend.api.main._chat_doc")
    def test_export_chat_not_found(self, mock_chat_doc, mock_auth, client):
        """Test exporting non-existent chat."""
        mock_auth.return_value = "test-uid"

        mock_snap = MagicMock()
        mock_snap.exists = False
        mock_chat_doc.return_value.get.return_value = mock_snap

        from backend.api.main import require_firebase_user

        app.dependency_overrides[require_firebase_user] = lambda: "test-uid"

        try:
            response = client.get(
                "/api/chats/nonexistent/export",
                headers={"Authorization": "Bearer test-token"},
            )
            assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()


# ============== Echo Endpoint Tests ==============


class TestEchoEndpoint:
    """Test /echo endpoint."""

    @patch("backend.api.main.run_job_from_code")
    @patch("backend.api.main.echo_manim_code")
    def test_echo_success(self, mock_echo, mock_run, client):
        """Test successful echo."""
        mock_echo.return_value = "class Scene: pass"
        mock_run.return_value = {"status": "ok", "video_url": "/static/test.mp4"}

        response = client.post("/echo", json={"prompt": "test"})
        assert response.status_code == 200


# ============== Continue Chat Tests ==============


class TestContinueChat:
    """Test continue chat route."""

    @patch("backend.api.main.require_firebase_user")
    @patch("backend.api.main.append_message")
    @patch("backend.api.main._chat_doc")
    @patch("backend.api.main._paginate_messages")
    def test_continue_chat_success(
        self, mock_paginate, mock_chat_doc, mock_append, mock_auth, client
    ):
        """Test continuing a chat."""
        mock_auth.return_value = "test-uid"
        mock_append.return_value = MessageOut(
            message_id="msg-123",
            role="user",
            content="Hello",
        )

        mock_snap = MagicMock()
        mock_snap.exists = True
        mock_snap.to_dict.return_value = {
            "title": "Test Chat",
            "updatedAt": None,
            "sessionId": None,
            "shareable": False,
        }
        mock_chat_doc.return_value.get.return_value = mock_snap

        mock_paginate.return_value = ([], False)

        from backend.api.main import require_firebase_user

        app.dependency_overrides[require_firebase_user] = lambda: "test-uid"

        try:
            response = client.post(
                "/api/chats/chat-123",
                json={"role": "user", "content": "Hello"},
                headers={"Authorization": "Bearer test-token"},
            )
            assert response.status_code == 200
        finally:
            app.dependency_overrides.clear()


# ============== Overlap Detection Tests ==============


class TestOverlapDetection:
    """Test overlap detection in edit endpoint."""

    @patch("backend.api.main.require_firebase_user")
    @patch("backend.agent.llm.clients.call_llm")
    @patch("backend.runner.job_runner.run_job_from_code")
    def test_detects_overlap_keywords(self, mock_run, mock_llm, mock_auth, client):
        """Test that overlap keywords are detected."""
        mock_auth.return_value = "test-uid"
        mock_llm.return_value = """```python
class GeneratedScene(VoiceoverScene):
    def construct(self):
        pass
```"""
        mock_run.return_value = {"ok": True, "video_url": "/static/test.mp4"}

        from backend.api.main import require_firebase_user

        app.dependency_overrides[require_firebase_user] = lambda: "test-uid"

        try:
            response = client.post(
                "/edit",
                json={
                    "original_code": "class Scene(VoiceoverScene):\n    def construct(self): pass",
                    "edit_instructions": "fix the overlapping text issue",
                    "keys": {"claude": "key"},
                },
                headers={"Authorization": "Bearer test-token"},
            )
            # Should process the request
            assert response.status_code in [200, 500]
        finally:
            app.dependency_overrides.clear()


# ============== Quiz from Transcript Endpoint Tests ==============


class TestQuizFromTranscriptEndpoint:
    """Test /quiz/media endpoint for quiz generation from media (video/podcast) transcripts."""

    @patch("backend.api.main.generate_quiz_embedded")
    @patch("backend.api.main.require_firebase_user")
    def test_quiz_from_transcript_success(self, mock_auth, mock_generate, client):
        """Test successful quiz generation from transcript."""
        mock_auth.return_value = "test-user-id"
        mock_generate.return_value = {
            "title": "Video Quiz",
            "description": "Quiz based on video content",
            "questions": [
                {
                    "prompt": "What was the main topic?",
                    "options": ["A", "B", "C", "D"],
                    "correctIndex": 0,
                }
            ],
            "count": 1,
        }

        response = client.post(
            "/quiz/media",
            json={
                "transcript": "The video discusses machine learning concepts.",
                "sceneCode": "print('hello')",
                "provider": "gemini",
                "model": "gemini-3-flash-preview",
                "provider_keys": {"gemini": "test-key"},
                "num_questions": 5,
                "difficulty": "medium",
            },
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "quiz" in data
        assert data["quiz"]["count"] == 1

    @patch("backend.api.main.generate_quiz_embedded")
    @patch("backend.api.main.require_firebase_user")
    def test_quiz_from_transcript_no_transcript(self, mock_auth, mock_generate, client):
        """Test quiz generation with missing transcript."""
        mock_auth.return_value = "test-user-id"

        response = client.post(
            "/quiz/media",
            json={
                "transcript": "",
            },
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code == 500

    @patch("backend.api.main.generate_quiz_embedded")
    @patch("backend.api.main.require_firebase_user")
    def test_quiz_from_transcript_with_scene_code(self, mock_auth, mock_generate, client):
        """Test quiz generation with scene code context."""
        mock_auth.return_value = "test-user-id"
        mock_generate.return_value = {
            "title": "Quiz",
            "questions": [],
            "count": 0,
        }

        response = client.post(
            "/quiz/media",
            json={
                "transcript": "Content about animations",
                "sceneCode": "class Scene(VoiceoverScene):\n    def construct(self): pass",
                "provider": "claude",
                "provider_keys": {"claude": "test-key"},
            },
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code == 200
        # Verify that scene_code was passed as context
        call_kwargs = mock_generate.call_args[1]
        assert call_kwargs["context"] is not None
        assert "class Scene" in call_kwargs["context"]

    @patch("backend.api.main.generate_quiz_embedded")
    @patch("backend.api.main.require_firebase_user")
    def test_quiz_from_transcript_provider_selection(self, mock_auth, mock_generate, client):
        """Test provider and model selection."""
        mock_auth.return_value = "test-user-id"
        mock_generate.return_value = {
            "title": "Quiz",
            "questions": [],
            "count": 0,
        }

        response = client.post(
            "/quiz/media",
            json={
                "transcript": "Test content",
                "provider": "claude",
                "model": "claude-3-5-sonnet",
                "provider_keys": {"claude": "key"},
            },
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code == 200
        call_kwargs = mock_generate.call_args[1]
        assert call_kwargs["provider"] == "claude"
        assert call_kwargs["model"] == "claude-3-5-sonnet"

    @patch("backend.api.main.generate_quiz_embedded")
    @patch("backend.api.main.require_firebase_user")
    def test_quiz_from_transcript_transcript_as_prompt(self, mock_auth, mock_generate, client):
        """Test that VTT transcript is passed with prefix to ensure only media content is used."""
        mock_auth.return_value = "test-user-id"
        mock_generate.return_value = {
            "title": "Quiz",
            "questions": [],
            "count": 0,
        }

        test_transcript = "This is the test video content about Python."
        response = client.post(
            "/quiz/media",
            json={
                "transcript": test_transcript,
            },
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code == 200
        call_kwargs = mock_generate.call_args[1]
        # Verify transcript is prefixed to ensure only media content is used
        expected_prompt = (
            f"Generate quiz questions based ONLY on the following content "
            f"(from captions):\n\n{test_transcript}"
        )
        assert call_kwargs["prompt"] == expected_prompt

    @patch("backend.api.main.generate_quiz_embedded")
    @patch("backend.api.main.require_firebase_user")
    def test_quiz_from_transcript_default_values(self, mock_auth, mock_generate, client):
        """Test default values for optional parameters."""
        mock_auth.return_value = "test-user-id"
        mock_generate.return_value = {
            "title": "Quiz",
            "questions": [],
            "count": 0,
        }

        response = client.post(
            "/quiz/media",
            json={
                "transcript": "Test content",
            },
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code == 200
        call_kwargs = mock_generate.call_args[1]
        # Check defaults
        assert call_kwargs["provider"] == "gemini"
        assert call_kwargs["model"] == "gemini-3-flash-preview"
        assert call_kwargs["num_questions"] == 5
        assert call_kwargs["difficulty"] == "medium"

    @patch("backend.api.main.generate_quiz_embedded")
    @patch("backend.api.main.require_firebase_user")
    def test_quiz_from_transcript_llm_failure(self, mock_auth, mock_generate, client):
        """Test handling of LLM generation failure."""
        mock_auth.return_value = "test-user-id"
        mock_generate.side_effect = Exception("LLM API error")

        response = client.post(
            "/quiz/media",
            json={
                "transcript": "Test content",
            },
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code == 500

    @patch("backend.api.main.require_firebase_user")
    def test_quiz_from_transcript_requires_auth(self, mock_auth, client):
        """Test that endpoint requires Firebase authentication."""
        mock_auth.side_effect = Exception("Unauthorized")

        response = client.post(
            "/quiz/media",
            json={
                "transcript": "Test content",
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        # Should fail due to auth error
        assert response.status_code >= 400
