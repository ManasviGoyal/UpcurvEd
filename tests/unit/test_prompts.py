"""Unit tests for agent prompts module."""

from backend.agent.prompts import CODE_SYSTEM, build_code_user_prompt


class TestCodeSystemPrompt:
    """Test the CODE_SYSTEM constant."""

    def test_code_system_is_string(self):
        """CODE_SYSTEM should be a non-empty string."""
        assert isinstance(CODE_SYSTEM, str)
        assert len(CODE_SYSTEM) > 0

    def test_code_system_contains_manim_instructions(self):
        """CODE_SYSTEM should contain Manim-related instructions."""
        assert "Manim" in CODE_SYSTEM or "manim" in CODE_SYSTEM

    def test_code_system_contains_voiceover_instructions(self):
        """CODE_SYSTEM should contain voiceover instructions."""
        assert "VoiceoverScene" in CODE_SYSTEM

    def test_code_system_contains_gtts_reference(self):
        """CODE_SYSTEM should reference GTTSService."""
        assert "GTTSService" in CODE_SYSTEM

    def test_code_system_contains_3d_instructions(self):
        """CODE_SYSTEM should contain 3D scene instructions."""
        assert "ThreeDScene" in CODE_SYSTEM or "3D" in CODE_SYSTEM

    def test_code_system_contains_latex_warnings(self):
        """CODE_SYSTEM should warn about LaTeX usage."""
        assert "LaTeX" in CODE_SYSTEM or "MathTex" in CODE_SYSTEM

    def test_code_system_contains_code_mobject_instructions(self):
        """CODE_SYSTEM should contain Code mobject instructions."""
        assert "Code" in CODE_SYSTEM

    def test_code_system_mentions_generated_scene(self):
        """CODE_SYSTEM should mention GeneratedScene class."""
        assert "GeneratedScene" in CODE_SYSTEM


class TestBuildCodeUserPrompt:
    """Test the build_code_user_prompt function."""

    def test_basic_prompt_with_goal_only(self):
        """Should build prompt with just the goal."""
        result = build_code_user_prompt("Explain the Pythagorean theorem")
        assert "Pythagorean theorem" in result
        assert isinstance(result, str)
        assert len(result) > 0

    def test_prompt_with_retrieved_docs(self):
        """Should include retrieved documentation."""
        result = build_code_user_prompt(
            "Create animation",
            retrieved_docs="[Doc 1] Sample documentation about Transform",
        )
        assert "Sample documentation" in result
        assert "Transform" in result

    def test_prompt_with_previous_code_for_repair(self):
        """Should include previous code for repair mode."""
        previous = "class Scene:\n    pass"
        result = build_code_user_prompt(
            "Fix the scene",
            previous_code=previous,
        )
        assert "LAST ATTEMPT CODE" in result
        assert "class Scene" in result

    def test_prompt_with_error_context_for_repair(self):
        """Should include error context for repair mode."""
        error = "NameError: name 'undefined' is not defined"
        result = build_code_user_prompt(
            "Fix the error",
            error_context=error,
        )
        assert "ERROR CONTEXT" in result
        assert "NameError" in result

    def test_prompt_with_all_parameters(self):
        """Should handle all parameters together."""
        result = build_code_user_prompt(
            "Complex animation",
            retrieved_docs="[Doc 1] Circle documentation",
            previous_code="class OldScene(Scene): pass",
            error_context="SyntaxError at line 5",
        )
        assert "Complex animation" in result
        assert "Circle documentation" in result
        assert "LAST ATTEMPT CODE" in result
        assert "SyntaxError" in result

    def test_prompt_with_empty_retrieved_docs(self):
        """Should handle empty retrieved docs."""
        result = build_code_user_prompt("Goal", retrieved_docs="")
        assert "Goal" in result

    def test_prompt_contains_voiceover_structure_instructions(self):
        """Prompt should contain voiceover structure guidance."""
        result = build_code_user_prompt("Any goal")
        assert "voiceover" in result.lower()
        assert "GTTSService" in result

    def test_prompt_contains_cleanup_instructions(self):
        """Prompt should contain cleanup instructions."""
        result = build_code_user_prompt("Any goal")
        assert "cleanup" in result.lower() or "FadeOut" in result

    def test_prompt_with_only_previous_code(self):
        """Should handle repair mode with only previous code."""
        result = build_code_user_prompt(
            "Goal",
            previous_code="some code",
            error_context=None,
        )
        assert "LAST ATTEMPT CODE" in result
        assert "some code" in result

    def test_prompt_with_only_error_context(self):
        """Should handle repair mode with only error context."""
        result = build_code_user_prompt(
            "Goal",
            previous_code=None,
            error_context="some error",
        )
        assert "ERROR CONTEXT" in result
        assert "some error" in result
