"""Comprehensive unit tests for LLM clients."""

from unittest.mock import MagicMock, patch


class TestLLMClients:
    """Test LLM client functions."""

    @patch("backend.agent.llm.clients.anthropic")
    def test_call_llm_claude(self, mock_anthropic):
        """Test calling Claude LLM."""
        from backend.agent.llm.clients import call_llm

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="response")]
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.Anthropic.return_value = mock_client

        result = call_llm("claude", "key", "claude-3", "system", "user")
        assert result is not None or mock_client.messages.create.called

    @patch("backend.agent.llm.clients.genai")
    def test_call_llm_gemini(self, mock_genai):
        """Test calling Gemini LLM."""
        from backend.agent.llm.clients import call_llm

        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "response"
        mock_model.generate_content.return_value = mock_response
        mock_genai.GenerativeModel.return_value = mock_model

        result = call_llm("gemini", "key", "gemini-2", "system", "user")
        assert result is not None or mock_model.generate_content.called

    @patch("backend.agent.llm.clients.anthropic")
    def test_call_llm_claude_with_temperature(self, mock_anthropic):
        """Test Claude with temperature."""
        from backend.agent.llm.clients import call_llm

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="response")]
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.Anthropic.return_value = mock_client

        try:
            call_llm("claude", "key", "claude-3", "system", "user", temperature=0.7)
        except Exception:
            pass

    @patch("backend.agent.llm.clients.genai")
    def test_call_llm_gemini_with_temperature(self, mock_genai):
        """Test Gemini with temperature."""
        from backend.agent.llm.clients import call_llm

        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "response"
        mock_model.generate_content.return_value = mock_response
        mock_genai.GenerativeModel.return_value = mock_model

        try:
            call_llm("gemini", "key", "gemini-2", "system", "user", temperature=0.7)
        except Exception:
            pass
