# tests/conftest.py
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ensure `backend` is importable
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["GCP_PROJECT"] = os.environ.get("GCP_PROJECT", "dummy_project")


@pytest.fixture(autouse=True)
def mock_dependencies(monkeypatch):
    """Mock external dependencies for all tests automatically."""
    from backend.api.main import app, require_firebase_user

    # Mock Firebase auth using FastAPI's dependency_overrides
    def fake_auth(authorization: str = None):
        return "test-uid"

    app.dependency_overrides[require_firebase_user] = fake_auth

    # Smart mock that returns different responses based on the request
    def create_mock_response(messages):
        """Create appropriate mock response based on message content."""
        user_content = str(messages)

        # Check if this is a quiz request
        if "quiz" in user_content.lower() or "question" in user_content.lower():
            return json.dumps(
                {
                    "title": "Math Quiz",
                    "questions": [
                        {
                            "id": "q1",
                            "question": "What is 2+2?",
                            "options": ["3", "4", "5", "6"],
                            "correct_answer": "4",
                        }
                    ],
                }
            )
        # Default video generation response
        else:
            return json.dumps(
                {
                    "title": "Test Video",
                    "description": "Test description",
                    "contexts": [],
                    "scenes": [
                        {
                            "id": "s1",
                            "duration_seconds": 2.0,
                            "voiceover_text": "Test voiceover",
                            "code_plan": None,
                            "language": "en",
                        }
                    ],
                    "code_plan": (
                        "from manim import *\n"
                        "class TestScene(Scene):\n"
                        "    def construct(self):\n"
                        "        pass"
                    ),
                }
            )

    # Mock Anthropic client
    def mock_anthropic_create(**kwargs):
        response_text = create_mock_response(kwargs.get("messages", []))
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text=response_text)]
        return mock_response

    mock_anthropic_client = MagicMock()
    mock_anthropic_client.messages.create = mock_anthropic_create

    # Patch the Anthropic class constructor
    with patch("anthropic.Anthropic", return_value=mock_anthropic_client):
        # Mock Gemini client
        def mock_gemini_generate(*args, **kwargs):
            # Gemini passes prompt as positional argument
            prompt = str(args) + str(kwargs)
            response_text = create_mock_response(prompt)
            mock_response = MagicMock()
            mock_response.text = response_text
            return mock_response

        mock_gemini_model = MagicMock()
        mock_gemini_model.generate_content = mock_gemini_generate

        with patch("google.generativeai.configure"):
            with patch("google.generativeai.GenerativeModel", return_value=mock_gemini_model):
                yield

    # Cleanup
    app.dependency_overrides.clear()
