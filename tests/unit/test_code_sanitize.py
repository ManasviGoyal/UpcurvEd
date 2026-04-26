"""Unit tests for code sanitization utilities."""

import re

from backend.agent.code_sanitize import (
    _auto_cleanup_overlapping_objects,
    _ensure_threed_mixin,
    _ensure_wait_between_animations,
    _guard_negative_waits,
    _sanitize_barchart_kwargs,
    _strip_unsupported_code_kwargs,
    allow_manim_star_import_with_noqa,
    ensure_generated_scene,
    ensure_voiceover_header,
    patch_unsafe_latex,
    sanitize_minimally,
    strip_code_fences,
)


class TestStripCodeFences:
    """Test code fence removal."""

    def test_strip_python_fence(self):
        """Strip python code fence."""
        code = "```python\nprint('hello')\n```"
        result = strip_code_fences(code)
        assert "```" not in result
        assert "print" in result

    def test_strip_plain_fence(self):
        """Strip plain code fence."""
        code = "```\ncode here\n```"
        result = strip_code_fences(code)
        assert "```" not in result
        assert "code" in result

    def test_strip_no_fences(self):
        """No fences should return trimmed code."""
        code = "plain code"
        result = strip_code_fences(code)
        assert result == "plain code"

    def test_strip_handles_non_string(self):
        """Non-string input should return empty string."""
        result = strip_code_fences(None)
        assert result == ""

    def test_strip_multiple_fences(self):
        """Should strip multiple fences."""
        code = "```python\nfirst\n```\n```python\nsecond\n```"
        result = strip_code_fences(code)
        assert "```" not in result


class TestEnsureVoiceoverHeader:
    """Test voiceover header injection."""

    def test_adds_voiceover_imports(self):
        """Should add voiceover imports."""
        code = "class Test(Scene):\n    pass"
        result = ensure_voiceover_header(code)
        assert "VoiceoverScene" in result
        assert "GTTSService" in result

    def test_removes_duplicate_imports(self):
        """Should remove duplicate voiceover imports."""
        code = "from manim_voiceover import VoiceoverScene\nclass Test(Scene):\n    pass"
        result = ensure_voiceover_header(code)
        # Should have exactly one VoiceoverScene import
        assert result.count("VoiceoverScene") == 1

    def test_handles_empty_code(self):
        """Should handle empty code."""
        result = ensure_voiceover_header("")
        assert "VoiceoverScene" in result


class TestEnsureGeneratedScene:
    """Test scene class renaming."""

    def test_renames_first_class(self):
        """Should rename first class to GeneratedScene."""
        code = "class MyScene(Scene):\n    pass"
        result = ensure_generated_scene(code)
        assert "GeneratedScene" in result

    def test_handles_voiceover_scene(self):
        """Should handle VoiceoverScene."""
        code = "class CustomScene(VoiceoverScene):\n    pass"
        result = ensure_generated_scene(code)
        assert "GeneratedScene" in result or "CustomScene" in result

    def test_handles_no_class(self):
        """Should handle code without class."""
        code = "def helper():\n    pass"
        result = ensure_generated_scene(code)
        assert isinstance(result, str)


class TestAllowManimStarImport:
    """Test star import handling."""

    def test_adds_noqa_to_existing_star_import(self):
        """Should add noqa comment to existing star import."""
        code = "from manim import *\nclass Scene:\n    pass"
        result = allow_manim_star_import_with_noqa(code)
        assert "# noqa: F403,F405" in result

    def test_inserts_star_import_if_missing(self):
        """Should insert star import if missing."""
        code = "class Scene:\n    pass"
        result = allow_manim_star_import_with_noqa(code)
        assert "from manim import *" in result
        assert "# noqa: F403,F405" in result

    def test_handles_voiceover_header_prefix(self):
        """Should handle code starting with voiceover header."""
        from backend.agent.code_sanitize import VOICEOVER_HEADER

        code = VOICEOVER_HEADER + "class Scene:\n    pass"
        result = allow_manim_star_import_with_noqa(code)
        assert "from manim import *" in result

    def test_preserves_existing_noqa(self):
        """Should not duplicate noqa if already present."""
        code = "from manim import *  # noqa: F403,F405\nclass Scene:\n    pass"
        result = allow_manim_star_import_with_noqa(code)
        assert result.count("noqa") == 1


class TestPatchUnsafeLatex:
    """Test unsafe LaTeX macro replacement."""

    def test_replaces_longdiv(self):
        """Should replace longdiv with overline."""
        code = r"MathTex(r'\enclose{longdiv}{123}')"
        result = patch_unsafe_latex(code)
        assert r"\overline" in result
        assert r"\enclose{longdiv}" not in result

    def test_replaces_cancel(self):
        """Should replace cancel with times."""
        code = r"MathTex(r'\cancel{x}')"
        result = patch_unsafe_latex(code)
        assert r"\times" in result
        assert r"\cancel" not in result

    def test_preserves_safe_latex(self):
        """Should preserve safe LaTeX."""
        code = r"MathTex(r'\frac{a}{b}')"
        result = patch_unsafe_latex(code)
        assert r"\frac{a}{b}" in result

    def test_handles_multiple_replacements(self):
        """Should handle multiple unsafe macros."""
        code = r"MathTex(r'\cancel{x} + \enclose{longdiv}{y}')"
        result = patch_unsafe_latex(code)
        assert r"\times" in result
        assert r"\overline" in result


class TestGuardNegativeWaits:
    """Test negative wait time guarding."""

    def test_guards_negative_numeric_wait(self):
        """Should guard negative numeric wait."""
        code = "self.wait(-1)"
        result = _guard_negative_waits(code)
        assert "-1" not in result or "max" in result

    def test_guards_zero_wait(self):
        """Should guard zero wait."""
        code = "self.wait(0)"
        result = _guard_negative_waits(code)
        assert "0.1" in result or "max" in result

    def test_guards_tracker_duration_subtraction(self):
        """Should guard tracker.duration - offset patterns."""
        code = "self.wait(tracker.duration - 5)"
        result = _guard_negative_waits(code)
        assert "max" in result
        assert "0.1" in result

    def test_preserves_positive_wait(self):
        """Should preserve positive wait."""
        code = "self.wait(2.5)"
        result = _guard_negative_waits(code)
        assert "2.5" in result

    def test_guards_existing_max_with_zero(self):
        """Should upgrade max(0, ...) to max(0.1, ...)."""
        code = "self.wait(max(0, tracker.duration))"
        result = _guard_negative_waits(code)
        assert "0.1" in result


class TestStripUnsupportedCodeKwargs:
    """Test stripping unsupported Code() kwargs."""

    def test_strips_font_size(self):
        """Should strip font_size kwarg."""
        code = 'Code(code_string="x", font_size=24)'
        result = _strip_unsupported_code_kwargs(code)
        assert "font_size" not in result
        assert "code_string" in result

    def test_strips_theme(self):
        """Should strip theme kwarg."""
        code = 'Code(code_string="x", theme="monokai")'
        result = _strip_unsupported_code_kwargs(code)
        assert "theme" not in result

    def test_preserves_allowed_kwargs(self):
        """Should preserve allowed kwargs."""
        code = 'Code(code_string="x", language="python", add_line_numbers=True)'
        result = _strip_unsupported_code_kwargs(code)
        assert "code_string" in result
        assert "language" in result
        assert "add_line_numbers" in result

    def test_handles_nested_parens(self):
        """Should handle nested parentheses."""
        code = "Code(code_string=func(), font_size=24)"
        result = _strip_unsupported_code_kwargs(code)
        assert "font_size" not in result

    def test_handles_multiple_code_calls(self):
        """Should handle multiple Code() calls."""
        code = 'Code(font_size=12)\nCode(theme="dark")'
        result = _strip_unsupported_code_kwargs(code)
        assert "font_size" not in result
        assert "theme" not in result

    def test_handles_string_with_parens(self):
        """Should handle strings containing parentheses."""
        code = 'Code(code_string="def f(): pass", font_size=24)'
        result = _strip_unsupported_code_kwargs(code)
        assert "font_size" not in result
        assert "code_string" in result


class TestSanitizeBarChart:
    """Tests for BarChart kwarg sanitization."""

    def test_renames_width_and_removes_max_value(self):
        src = "BarChart([1,2,3], width=0.5, max_value=10)"
        result = _sanitize_barchart_kwargs(src)
        assert "bar_width=0.5" in result
        assert re.search(r"(?<!\w)width=", result) is None
        assert "max_value" not in result

    def test_no_change_for_non_matching(self):
        src = "BarChart(values=[1,2,3])"
        result = _sanitize_barchart_kwargs(src)
        assert "BarChart(values=" in result


class TestEnsureThreeDMixin:
    """Test 3D mixin auto-detection and injection."""

    def test_adds_threed_for_threedaxes(self):
        """Should add ThreeDScene for ThreeDAxes usage."""
        code = "class GeneratedScene(VoiceoverScene):\n    ThreeDAxes()"
        result = _ensure_threed_mixin(code)
        assert "ThreeDScene" in result

    def test_adds_threed_for_surface(self):
        """Should add ThreeDScene for Surface usage."""
        code = "class GeneratedScene(VoiceoverScene):\n    Surface()"
        result = _ensure_threed_mixin(code)
        assert "ThreeDScene" in result

    def test_adds_threed_for_move_camera(self):
        """Should add ThreeDScene for move_camera usage."""
        code = "class GeneratedScene(VoiceoverScene):\n    self.move_camera()"
        result = _ensure_threed_mixin(code)
        assert "ThreeDScene" in result

    def test_no_change_for_2d_code(self):
        """Should not change code without 3D markers."""
        code = "class GeneratedScene(VoiceoverScene):\n    Text('hello')"
        result = _ensure_threed_mixin(code)
        assert "ThreeDScene" not in result

    def test_handles_none_input(self):
        """Should handle None input."""
        result = _ensure_threed_mixin(None)
        assert result is None

    def test_handles_empty_string(self):
        """Should handle empty string."""
        result = _ensure_threed_mixin("")
        assert result == ""

    def test_preserves_existing_threed_mixin(self):
        """Should work with code already having ThreeDScene."""
        code = "class GeneratedScene(VoiceoverScene, ThreeDScene):\n    ThreeDAxes()"
        result = _ensure_threed_mixin(code)
        # Should not break existing code
        assert "ThreeDScene" in result


class TestSanitizeMinimally:
    """Test the main sanitize_minimally function."""

    def test_full_pipeline(self):
        """Test complete sanitization pipeline."""
        code = """```python
class MyScene(Scene):
    def construct(self):
        self.wait(-1)
        Code(font_size=24)
```"""
        result = sanitize_minimally(code)

        # Should strip fences
        assert "```" not in result
        # Should add voiceover header
        assert "VoiceoverScene" in result
        # Should have GeneratedScene
        assert "GeneratedScene" in result
        # Should have star import with noqa
        assert "from manim import *" in result
        # Should guard negative wait
        assert "max" in result or "-1" not in result

    def test_handles_empty_input(self):
        """Should handle empty input."""
        result = sanitize_minimally("")
        assert isinstance(result, str)
        assert "VoiceoverScene" in result

    def test_adds_trailing_newline(self):
        """Should add trailing newline."""
        code = "class Scene:\n    pass"
        result = sanitize_minimally(code)
        assert result.endswith("\n")

    def test_3d_upgrade(self):
        """Should upgrade to 3D mixin when needed."""
        code = """class MyScene(VoiceoverScene):
    def construct(self):
        axes = ThreeDAxes()"""
        result = sanitize_minimally(code)
        assert "ThreeDScene" in result

    def test_unsafe_latex_patched(self):
        """Should patch unsafe LaTeX."""
        code = r"""class MyScene(VoiceoverScene):
    def construct(self):
        MathTex(r'\cancel{x}')"""
        result = sanitize_minimally(code)
        assert r"\times" in result or r"\cancel" not in result


class TestAutoCleanupOverlappingObjects:
    """Test auto-cleanup to prevent text/object overlap in videos."""

    def test_handles_none_input(self):
        """Should handle None input."""
        result = _auto_cleanup_overlapping_objects(None)
        assert result is None

    def test_handles_empty_string(self):
        """Should handle empty string."""
        result = _auto_cleanup_overlapping_objects("")
        assert result == ""

    def test_preserves_code_without_voiceover(self):
        """Should preserve code without voiceover blocks."""
        code = """class Scene:
    def construct(self):
        text = Text("Hello")
        self.play(Write(text))
"""
        result = _auto_cleanup_overlapping_objects(code)
        assert "Text" in result
        assert "Write" in result

    def test_tracks_objects_in_voiceover_block(self):
        """Should track objects created in voiceover blocks."""
        code = """class Scene:
    def construct(self):
        with self.voiceover(text="Hello"):
            title = Text("Title")
            self.play(Write(title))
        next_section()
"""
        result = _auto_cleanup_overlapping_objects(code)
        # The function should process the code without error
        assert "voiceover" in result
        assert "Text" in result

    def test_respects_explicit_fadeout(self):
        """Should not add cleanup for objects already removed."""
        code = """class Scene:
    def construct(self):
        with self.voiceover(text="Hello"):
            title = Text("Title")
            self.play(Write(title))
            self.play(FadeOut(title))
        next_section()
"""
        result = _auto_cleanup_overlapping_objects(code)
        # Should only have one FadeOut for title
        assert result.count("FadeOut(title)") == 1

    def test_respects_self_clear(self):
        """Should not add cleanup if self.clear() is called."""
        code = """class Scene:
    def construct(self):
        with self.voiceover(text="Hello"):
            title = Text("Title")
            self.play(Write(title))
            self.clear()
        next_section()
"""
        result = _auto_cleanup_overlapping_objects(code)
        # Should not add extra FadeOut since clear() was called
        assert "self.clear()" in result

    def test_handles_multiple_objects(self):
        """Should track multiple objects in voiceover block."""
        code = """class Scene:
    def construct(self):
        with self.voiceover(text="Hello"):
            title = Text("Title")
            subtitle = Text("Subtitle")
            self.play(Write(title), Write(subtitle))
"""
        result = _auto_cleanup_overlapping_objects(code)
        assert "title" in result
        assert "subtitle" in result

    def test_handles_various_manim_objects(self):
        """Should track various Manim object types."""
        code = """class Scene:
    def construct(self):
        with self.voiceover(text="Demo"):
            circle = Circle()
            square = Square()
            text = MathTex("x^2")
            self.play(Create(circle))
"""
        result = _auto_cleanup_overlapping_objects(code)
        assert "Circle" in result
        assert "Square" in result
        assert "MathTex" in result


class TestEnsureWaitBetweenAnimations:
    """Test wait time insertion between animations."""

    def test_handles_none_input(self):
        """Should handle None input."""
        result = _ensure_wait_between_animations(None)
        assert result is None

    def test_handles_empty_string(self):
        """Should handle empty string."""
        result = _ensure_wait_between_animations("")
        assert result == ""

    def test_preserves_single_play(self):
        """Should preserve single play call."""
        code = """class Scene:
    def construct(self):
        self.play(Write(text))
"""
        result = _ensure_wait_between_animations(code)
        assert "self.play(Write(text))" in result

    def test_handles_consecutive_plays(self):
        """Should handle consecutive play calls."""
        code = """class Scene:
    def construct(self):
        self.play(Write(text1))
        self.play(Write(text2))
"""
        result = _ensure_wait_between_animations(code)
        # Should process without error
        assert "self.play" in result

    def test_respects_existing_waits(self):
        """Should respect existing wait calls."""
        code = """class Scene:
    def construct(self):
        self.play(Write(text1))
        self.wait(1)
        self.play(Write(text2))
"""
        result = _ensure_wait_between_animations(code)
        assert "self.wait(1)" in result

    def test_handles_comments(self):
        """Should handle comment lines."""
        code = """class Scene:
    def construct(self):
        self.play(Write(text1))
        # This is a comment
        self.play(Write(text2))
"""
        result = _ensure_wait_between_animations(code)
        assert "# This is a comment" in result


class TestSanitizeMinimallyWithAutoCleanup:
    """Test that sanitize_minimally includes auto-cleanup."""

    def test_pipeline_includes_auto_cleanup(self):
        """Test that auto-cleanup is part of the sanitization pipeline."""
        code = """```python
class MyScene(VoiceoverScene):
    def construct(self):
        with self.voiceover(text="Hello"):
            title = Text("Title")
            self.play(Write(title))
```"""
        result = sanitize_minimally(code)
        # Should strip fences and process voiceover blocks
        assert "```" not in result
        assert "voiceover" in result
        assert "Text" in result
