"""Tests for learner-level validation and model prompt guidance."""

import pytest

from backend.api.main import GenerateIn, _with_audience_guidance


def test_audience_defaults_to_auto():
    data = GenerateIn(prompt="test")

    assert data.audience == "auto"


def test_supported_audience_is_accepted():
    data = GenerateIn(prompt="test", audience="middle_school")

    assert data.audience == "middle_school"


def test_unknown_audience_is_ignored_for_guidance():
    data = GenerateIn(prompt="test", audience="college_freshman")

    assert data.audience == "college_freshman"

    result = _with_audience_guidance("Explain gravity", data.audience)
    assert result == "Explain gravity"


def test_auto_keeps_prompt_unchanged():
    assert _with_audience_guidance("Explain gravity", "auto") == "Explain gravity"


def test_selected_level_adds_instructional_requirements():
    result = _with_audience_guidance("Explain gravity", "middle_school")

    assert result.startswith("Explain gravity\n\n")
    assert "Target audience: Middle school" in result
    assert "vocabulary, examples, pacing, visuals, interactions" in result
    assert result.endswith("</LEARNER_LEVEL_REQUIREMENTS>")
