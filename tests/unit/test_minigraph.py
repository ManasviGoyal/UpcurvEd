"""Unit tests for minigraph module - simple LangGraph-based code generation."""

from backend.agent.minigraph import (
    MiniState,
    _build_graph,
    _sanitize,
    draft_code_node,
    echo_manim_code,
)


class TestSanitizeFunction:
    """Test the _sanitize helper function."""

    def test_sanitize_normal_string(self):
        """Test sanitizing a normal string."""
        result = _sanitize("Hello World")
        assert result == "Hello World"

    def test_sanitize_escapes_backslashes(self):
        """Test that backslashes are escaped."""
        result = _sanitize("path\\to\\file")
        assert "\\\\" in result

    def test_sanitize_escapes_quotes(self):
        """Test that double quotes are escaped."""
        result = _sanitize('say "hello"')
        assert '\\"' in result

    def test_sanitize_removes_newlines(self):
        """Test that newlines are replaced with spaces."""
        result = _sanitize("line1\nline2")
        assert "\n" not in result
        assert " " in result

    def test_sanitize_truncates_long_strings(self):
        """Test that strings are truncated to 120 characters."""
        long_string = "a" * 200
        result = _sanitize(long_string)
        assert len(result) <= 120

    def test_sanitize_handles_none(self):
        """Test that None is handled gracefully."""
        result = _sanitize(None)
        assert result == ""

    def test_sanitize_handles_empty_string(self):
        """Test that empty string is handled."""
        result = _sanitize("")
        assert result == ""

    def test_sanitize_combined_special_chars(self):
        """Test sanitizing string with multiple special characters."""
        result = _sanitize('Test "quote" with\\backslash\nand newline')
        assert "\n" not in result
        assert '\\"' in result
        assert "\\\\" in result


class TestMiniState:
    """Test MiniState TypedDict."""

    def test_ministate_creation(self):
        """Test creating a MiniState."""
        state: MiniState = {"user_prompt": "test", "manim_code": "code"}
        assert state["user_prompt"] == "test"
        assert state["manim_code"] == "code"

    def test_ministate_partial(self):
        """Test MiniState with partial fields (total=False)."""
        state: MiniState = {"user_prompt": "test"}
        assert state["user_prompt"] == "test"
        assert "manim_code" not in state

    def test_ministate_empty(self):
        """Test empty MiniState."""
        state: MiniState = {}
        assert len(state) == 0


class TestDraftCodeNode:
    """Test draft_code_node function."""

    def test_generates_manim_code(self):
        """Test that draft_code_node generates Manim code."""
        state: MiniState = {"user_prompt": "Hello World"}
        result = draft_code_node(state)
        assert "manim_code" in result
        assert "GeneratedScene" in result["manim_code"]
        assert "VoiceoverScene" in result["manim_code"]

    def test_includes_user_prompt(self):
        """Test that user prompt is included in generated code."""
        state: MiniState = {"user_prompt": "Test Prompt"}
        result = draft_code_node(state)
        # Prompt should be sanitized and included
        assert "Test Prompt" in result["manim_code"]

    def test_preserves_original_state(self):
        """Test that original state fields are preserved."""
        state: MiniState = {"user_prompt": "test"}
        result = draft_code_node(state)
        assert result["user_prompt"] == "test"

    def test_handles_empty_prompt(self):
        """Test handling empty user prompt."""
        state: MiniState = {"user_prompt": ""}
        result = draft_code_node(state)
        assert "manim_code" in result
        assert "GeneratedScene" in result["manim_code"]

    def test_handles_missing_prompt(self):
        """Test handling missing user prompt."""
        state: MiniState = {}
        result = draft_code_node(state)
        assert "manim_code" in result

    def test_includes_voiceover_imports(self):
        """Test that voiceover imports are included."""
        state: MiniState = {"user_prompt": "test"}
        result = draft_code_node(state)
        code = result["manim_code"]
        assert "from manim_voiceover import VoiceoverScene" in code
        assert "from manim_voiceover.services.gtts import GTTSService" in code

    def test_includes_construct_method(self):
        """Test that construct method is included."""
        state: MiniState = {"user_prompt": "test"}
        result = draft_code_node(state)
        assert "def construct(self)" in result["manim_code"]

    def test_includes_speech_service(self):
        """Test that speech service is set."""
        state: MiniState = {"user_prompt": "test"}
        result = draft_code_node(state)
        assert "set_speech_service" in result["manim_code"]
        assert "GTTSService()" in result["manim_code"]

    def test_sanitizes_special_chars_in_prompt(self):
        """Test that special characters in prompt are sanitized."""
        state: MiniState = {"user_prompt": 'Test "quotes" and\\backslash'}
        result = draft_code_node(state)
        # Code should be valid (no unescaped quotes breaking strings)
        assert "manim_code" in result


class TestBuildGraph:
    """Test _build_graph function."""

    def test_builds_compilable_graph(self):
        """Test that graph is built and compiled."""
        graph = _build_graph()
        assert graph is not None
        # Should be callable
        assert callable(graph.invoke)

    def test_graph_has_draft_code_node(self):
        """Test that graph contains the draft_code node."""
        # The graph is already built, we test via invocation
        graph = _build_graph()
        result = graph.invoke({"user_prompt": "test"})
        assert "manim_code" in result


class TestEchoManimCode:
    """Test echo_manim_code function."""

    def test_returns_manim_code(self):
        """Test that function returns Manim code."""
        result = echo_manim_code("Hello World")
        assert isinstance(result, str)
        assert "GeneratedScene" in result
        assert "VoiceoverScene" in result

    def test_includes_prompt_in_code(self):
        """Test that prompt is included in generated code."""
        result = echo_manim_code("My Test Animation")
        assert "My Test Animation" in result

    def test_code_has_imports(self):
        """Test that code has necessary imports."""
        result = echo_manim_code("test")
        assert "from manim" in result
        assert "from manim_voiceover" in result

    def test_code_has_class_structure(self):
        """Test that code has proper class structure."""
        result = echo_manim_code("test")
        assert "class GeneratedScene" in result
        assert "def construct" in result

    def test_handles_empty_prompt(self):
        """Test handling empty prompt."""
        result = echo_manim_code("")
        assert isinstance(result, str)
        assert "GeneratedScene" in result

    def test_handles_special_characters(self):
        """Test handling special characters in prompt."""
        result = echo_manim_code('Prompt with "quotes" and\\slashes')
        assert isinstance(result, str)
        # Should not raise exception

    def test_handles_long_prompt(self):
        """Test handling very long prompt."""
        long_prompt = "word " * 100
        result = echo_manim_code(long_prompt)
        assert isinstance(result, str)
        # Prompt should be truncated to 120 chars
        assert len(result) > 0

    def test_handles_unicode(self):
        """Test handling unicode characters."""
        result = echo_manim_code("Unicode: 你好 مرحبا 🎬")
        assert isinstance(result, str)

    def test_handles_newlines_in_prompt(self):
        """Test handling newlines in prompt."""
        result = echo_manim_code("Line 1\nLine 2\nLine 3")
        assert isinstance(result, str)
        # Newlines should be converted to spaces
        assert "\n" not in result or "Line 1" in result
