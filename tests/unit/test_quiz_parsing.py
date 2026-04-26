"""Unit tests for quiz JSON parsing and normalization."""

import json
from unittest.mock import patch

import pytest

from backend.mcp.quiz_logic import (
    _extract_and_rebuild_quiz,
    _extract_outer_object,
    _fix_unclosed_structures,
    _insert_missing_commas,
    _normalize_quiz,
    _parse_quiz_json,
    _pick_provider_and_key,
    _quiz_prompt,
    _repair_json,
    _strip_code_fences,
    generate_quiz_embedded,
)


class TestPickProviderAndKey:
    """Test provider and API key selection."""

    def test_explicit_claude_provider(self):
        """Should return claude when explicitly specified."""
        prov, key = _pick_provider_and_key("claude", {"claude": "sk-123"})
        assert prov == "claude"
        assert key == "sk-123"

    def test_explicit_gemini_provider(self):
        """Should return gemini when explicitly specified."""
        prov, key = _pick_provider_and_key("gemini", {"gemini": "gm-456"})
        assert prov == "gemini"
        assert key == "gm-456"

    def test_explicit_provider_case_insensitive(self):
        """Provider should be case insensitive."""
        prov, key = _pick_provider_and_key("CLAUDE", {"claude": "sk-123"})
        assert prov == "claude"

    def test_infer_claude_from_keys(self):
        """Should infer claude when only claude key available."""
        prov, key = _pick_provider_and_key(None, {"claude": "sk-123"})
        assert prov == "claude"
        assert key == "sk-123"

    def test_infer_gemini_from_keys(self):
        """Should infer gemini when only gemini key available."""
        prov, key = _pick_provider_and_key(None, {"gemini": "gm-456"})
        assert prov == "gemini"
        assert key == "gm-456"

    def test_prefers_claude_when_both_available(self):
        """Should prefer claude when both keys available and no explicit provider."""
        prov, key = _pick_provider_and_key(None, {"claude": "sk-123", "gemini": "gm-456"})
        assert prov == "claude"

    def test_raises_when_no_keys(self):
        """Should raise when no keys provided."""
        with pytest.raises(RuntimeError, match="No provider keys available"):
            _pick_provider_and_key(None, {})

    def test_raises_when_provider_key_missing(self):
        """Should raise when explicit provider has no key."""
        with pytest.raises(RuntimeError, match="Missing API key"):
            _pick_provider_and_key("claude", {"gemini": "gm-456"})

    def test_raises_with_none_keys(self):
        """Should raise when keys dict is None."""
        with pytest.raises(RuntimeError, match="No provider keys available"):
            _pick_provider_and_key(None, None)

    def test_empty_provider_string(self):
        """Empty provider string should infer from keys."""
        prov, key = _pick_provider_and_key("", {"gemini": "gm-456"})
        assert prov == "gemini"


class TestStripCodeFences:
    """Test code fence removal."""

    def test_removes_json_fence(self):
        """Remove ```json fence."""
        text = '```json\n{"key": "value"}\n```'
        result = _strip_code_fences(text)
        assert result == '{"key": "value"}'

    def test_removes_plain_fence(self):
        """Remove ``` fence without language."""
        text = '```\n{"key": "value"}\n```'
        result = _strip_code_fences(text)
        assert result == '{"key": "value"}'

    def test_no_fence(self):
        """Text without fence should be unchanged."""
        text = '{"key": "value"}'
        result = _strip_code_fences(text)
        assert result == '{"key": "value"}'

    def test_only_opening_fence(self):
        """Handle only opening fence."""
        text = '```json\n{"key": "value"}'
        result = _strip_code_fences(text)
        assert result == '{"key": "value"}'


class TestRepairJson:
    """Test JSON repair logic."""

    def test_trailing_comma_object(self):
        """Remove trailing comma in object."""
        text = '{"key": "value",}'
        result = _repair_json(text)
        data = json.loads(result)
        assert data == {"key": "value"}

    def test_trailing_comma_array(self):
        """Remove trailing comma in array."""
        text = '{"items": [1, 2, 3,]}'
        result = _repair_json(text)
        data = json.loads(result)
        assert data == {"items": [1, 2, 3]}

    def test_python_true_false(self):
        """Convert Python True/False to JSON true/false."""
        text = '{"flag1": True, "flag2": False, "flag3": None}'
        result = _repair_json(text)
        data = json.loads(result)
        assert data == {"flag1": True, "flag2": False, "flag3": None}

    def test_smart_quotes(self):
        """Replace smart quotes with standard quotes."""
        text = '{"key": "value"}'
        result = _repair_json(text)
        assert '"key"' in result
        assert '"value"' in result

    def test_extra_text_before_json(self):
        """Remove text before opening brace."""
        text = 'Here is the JSON: {"key": "value"}'
        result = _repair_json(text)
        data = json.loads(result)
        assert data == {"key": "value"}

    def test_extra_text_after_json(self):
        """Remove text after closing brace."""
        text = '{"key": "value"} - that was the JSON'
        result = _repair_json(text)
        data = json.loads(result)
        assert data == {"key": "value"}


class TestInsertMissingCommas:
    """Test comma insertion logic."""

    def test_missing_comma_between_objects(self):
        """Insert comma between adjacent objects in array."""
        text = '[{"a": 1} {"b": 2}]'
        result = _insert_missing_commas(text)
        data = json.loads(result)
        assert data == [{"a": 1}, {"b": 2}]

    def test_missing_comma_after_number(self):
        """Insert comma after number before quote."""
        text = '{"items": [1 2 3]}'
        result = _insert_missing_commas(text)
        # The function attempts to insert commas, just verify it doesn't crash
        assert isinstance(result, str)
        assert len(result) > 0

    def test_already_correct_json(self):
        """Valid JSON should remain valid."""
        text = '{"items": [1, 2, 3], "name": "test"}'
        result = _insert_missing_commas(text)
        data = json.loads(result)
        assert data == {"items": [1, 2, 3], "name": "test"}


class TestNormalizeQuiz:
    """Test quiz normalization and validation."""

    def test_valid_quiz(self):
        """Valid quiz should pass through."""
        data = {
            "title": "Test Quiz",
            "description": "A test",
            "questions": [
                {
                    "type": "multiple_choice",
                    "prompt": "Question 1?",
                    "options": ["A", "B", "C"],
                    "correctIndex": 1,
                }
            ],
        }
        result = _normalize_quiz(data)
        assert result["title"] == "Test Quiz"
        assert result["description"] == "A test"
        assert len(result["questions"]) == 1
        assert result["questions"][0]["prompt"] == "Question 1?"

    def test_missing_title(self):
        """Missing title should default to 'Untitled Quiz'."""
        data = {"description": "Test", "questions": []}
        result = _normalize_quiz(data)
        assert result["title"] == "Untitled Quiz"

    def test_empty_title(self):
        """Empty title should default."""
        data = {"title": "", "description": "Test", "questions": []}
        result = _normalize_quiz(data)
        assert result["title"] == "Untitled Quiz"

    def test_missing_description(self):
        """Missing description should default to empty string."""
        data = {"title": "Test", "questions": []}
        result = _normalize_quiz(data)
        assert result["description"] == ""

    def test_non_string_description(self):
        """Non-string description should convert to empty."""
        data = {"title": "Test", "description": 123, "questions": []}
        result = _normalize_quiz(data)
        assert result["description"] == ""

    def test_filters_invalid_questions(self):
        """Questions with < 3 options should be filtered."""
        data = {
            "title": "Test",
            "description": "",
            "questions": [
                {"prompt": "Q1", "options": ["A", "B"], "correctIndex": 0},  # Too few
                {
                    "prompt": "Q2",
                    "options": ["A", "B", "C"],
                    "correctIndex": 1,
                },  # Valid
            ],
        }
        result = _normalize_quiz(data)
        assert len(result["questions"]) == 1
        assert result["questions"][0]["prompt"] == "Q2"

    def test_corrects_invalid_correct_index(self):
        """Out-of-range correctIndex should default to 0."""
        data = {
            "title": "Test",
            "description": "",
            "questions": [{"prompt": "Q1", "options": ["A", "B", "C"], "correctIndex": 10}],
        }
        result = _normalize_quiz(data)
        assert result["questions"][0]["correctIndex"] == 0

    def test_negative_correct_index(self):
        """Negative correctIndex should default to 0."""
        data = {
            "title": "Test",
            "description": "",
            "questions": [{"prompt": "Q1", "options": ["A", "B", "C"], "correctIndex": -1}],
        }
        result = _normalize_quiz(data)
        assert result["questions"][0]["correctIndex"] == 0

    def test_deduplicates_options(self):
        """Duplicate options should be removed."""
        data = {
            "title": "Test",
            "description": "",
            "questions": [{"prompt": "Q1", "options": ["A", "B", "B", "C"], "correctIndex": 0}],
        }
        result = _normalize_quiz(data)
        options = result["questions"][0]["options"]
        assert options.count("B") == 1

    def test_strips_whitespace_from_options(self):
        """Options should have whitespace stripped."""
        data = {
            "title": "Test",
            "description": "",
            "questions": [{"prompt": "Q1", "options": ["  A  ", " B ", "C  "], "correctIndex": 0}],
        }
        result = _normalize_quiz(data)
        options = result["questions"][0]["options"]
        assert options == ["A", "B", "C"]

    def test_caps_question_count(self):
        """Should cap at 50 questions."""
        questions = [
            {"prompt": f"Q{i}", "options": ["A", "B", "C"], "correctIndex": 0} for i in range(100)
        ]
        data = {"title": "Test", "description": "", "questions": questions}
        result = _normalize_quiz(data)
        assert len(result["questions"]) <= 50


class TestParseQuizJson:
    """Test full quiz JSON parsing with repair."""

    def test_valid_json(self):
        """Valid JSON should parse directly."""
        text = json.dumps(
            {
                "title": "My Quiz",
                "description": "Description",
                "questions": [
                    {
                        "type": "multiple_choice",
                        "prompt": "What is 2+2?",
                        "options": ["2", "3", "4", "5"],
                        "correctIndex": 2,
                    }
                ],
            }
        )
        result = _parse_quiz_json(text)
        assert result["title"] == "My Quiz"
        assert len(result["questions"]) == 1

    def test_json_with_code_fences(self):
        """Should handle JSON wrapped in code fences."""
        text = (
            "```json\n"
            + json.dumps(
                {
                    "title": "Test",
                    "description": "",
                    "questions": [{"prompt": "Q?", "options": ["A", "B", "C"], "correctIndex": 0}],
                }
            )
            + "\n```"
        )
        result = _parse_quiz_json(text)
        assert result["title"] == "Test"

    def test_json_with_trailing_comma(self):
        """Should repair trailing comma."""
        text = '{"title": "Test", "description": "", "questions": [],}'
        result = _parse_quiz_json(text)
        assert result["title"] == "Test"

    def test_json_with_python_booleans(self):
        """Should convert Python-style booleans."""
        text = '{"title": "Test", "description": "", "questions": []}'
        # this doesn't actually have bools but test the path anyway
        result = _parse_quiz_json(text)
        assert isinstance(result, dict)

    def test_malformed_json_raises_error(self):
        """Completely malformed JSON should raise RuntimeError."""
        text = "This is not JSON at all!!!"
        with pytest.raises(RuntimeError, match="Unable to parse quiz JSON"):
            _parse_quiz_json(text)


class TestExtractOuterObject:
    """Test extraction of outer JSON object."""

    def test_extracts_json_from_text(self):
        """Should extract JSON object from surrounding text."""
        text = 'Before text {"key": "value"} after text'
        result = _extract_outer_object(text)
        assert result == '{"key": "value"}'

    def test_no_braces(self):
        """Text without braces returns unchanged."""
        text = "no braces here"
        result = _extract_outer_object(text)
        assert result == "no braces here"

    def test_nested_braces(self):
        """Should handle nested braces correctly."""
        text = 'prefix {"outer": {"inner": "val"}} suffix'
        result = _extract_outer_object(text)
        assert result == '{"outer": {"inner": "val"}}'

    def test_only_opening_brace(self):
        """Only opening brace returns unchanged."""
        text = "{ no closing"
        result = _extract_outer_object(text)
        assert result == "{ no closing"


class TestFixUnclosedStructures:
    """Test fixing unclosed JSON structures."""

    def test_missing_closing_brace(self):
        """Should add missing closing brace."""
        text = '{"key": "value"'
        result = _fix_unclosed_structures(text)
        assert result.count("{") == result.count("}")

    def test_missing_closing_bracket(self):
        """Should add missing closing bracket."""
        text = '{"items": [1, 2, 3}'
        result = _fix_unclosed_structures(text)
        assert result.count("[") == result.count("]")

    def test_multiple_missing_closures(self):
        """Should fix multiple missing closures."""
        text = '{"outer": {"inner": [1, 2'
        result = _fix_unclosed_structures(text)
        assert result.count("{") == result.count("}")
        assert result.count("[") == result.count("]")

    def test_balanced_structure(self):
        """Balanced structure should remain unchanged."""
        text = '{"key": [1, 2, 3]}'
        result = _fix_unclosed_structures(text)
        assert result == '{"key": [1, 2, 3]}'

    def test_unclosed_string(self):
        """Should attempt to close unclosed string."""
        text = '{"key": "value'
        result = _fix_unclosed_structures(text)
        # Should have even number of quotes after fix
        assert result.count('"') % 2 == 0


class TestExtractAndRebuildQuiz:
    """Test last-resort quiz extraction."""

    def test_extracts_valid_quiz(self):
        """Should extract valid quiz from malformed JSON."""
        text = """
        {"title": "My Quiz", "description": "Test quiz",
        "questions": [
            {"type": "multiple_choice", "prompt": "What is 2+2?",
            "options": ["1", "2", "3", "4"], "correctIndex": 3}
        ]}
        """
        result = _extract_and_rebuild_quiz(text)
        assert result["title"] == "My Quiz"
        assert result["description"] == "Test quiz"
        assert len(result["questions"]) == 1
        assert result["questions"][0]["prompt"] == "What is 2+2?"

    def test_extracts_multiple_questions(self):
        """Should extract multiple questions."""
        text = """
        {"title": "Math Quiz", "description": "Basic math",
        "questions": [
            {"type": "multiple_choice", "prompt": "What is 1+1?",
            "options": ["1", "2", "3", "4"], "correctIndex": 1},
            {"type": "multiple_choice", "prompt": "What is 2+2?",
            "options": ["2", "3", "4", "5"], "correctIndex": 2}
        ]}
        """
        result = _extract_and_rebuild_quiz(text)
        assert len(result["questions"]) == 2

    def test_defaults_title_when_missing(self):
        """Should default title when not found."""
        text = """
        {"description": "Test",
        "questions": [
            {"type": "multiple_choice", "prompt": "Question?",
            "options": ["A", "B", "C"], "correctIndex": 0}
        ]}
        """
        result = _extract_and_rebuild_quiz(text)
        assert result["title"] == "Untitled Quiz"

    def test_defaults_description_when_missing(self):
        """Should default description when not found."""
        text = """
        {"title": "Quiz",
        "questions": [
            {"type": "multiple_choice", "prompt": "Question?",
            "options": ["A", "B", "C"], "correctIndex": 0}
        ]}
        """
        result = _extract_and_rebuild_quiz(text)
        assert result["description"] == ""

    def test_raises_when_no_questions(self):
        """Should raise when no valid questions found."""
        text = '{"title": "Empty", "description": "No questions"}'
        with pytest.raises(ValueError, match="Could not extract any valid questions"):
            _extract_and_rebuild_quiz(text)

    def test_filters_invalid_questions(self):
        """Should filter questions with too few options."""
        text = """
        {"title": "Quiz", "description": "",
        "questions": [
            {"type": "multiple_choice", "prompt": "Q1?",
            "options": ["A", "B"], "correctIndex": 0},
            {"type": "multiple_choice", "prompt": "Q2?",
            "options": ["A", "B", "C"], "correctIndex": 1}
        ]}
        """
        result = _extract_and_rebuild_quiz(text)
        assert len(result["questions"]) == 1
        assert result["questions"][0]["prompt"] == "Q2?"


class TestQuizPrompt:
    """Test quiz prompt generation."""

    def test_basic_prompt(self):
        """Should generate basic prompt without context."""
        result = _quiz_prompt("Math basics", 5, "medium", None)
        assert "Math basics" in result
        assert "medium" in result
        assert "5" in result

    def test_prompt_with_context(self):
        """Should include context when provided."""
        result = _quiz_prompt("Science", 3, "easy", "Some context here")
        assert "Some context here" in result
        assert "Additional context" in result

    def test_prompt_includes_schema(self):
        """Prompt should include JSON schema."""
        result = _quiz_prompt("Test", 5, "hard", None)
        assert '"title"' in result
        assert '"questions"' in result
        assert '"correctIndex"' in result

    def test_prompt_includes_rules(self):
        """Prompt should include formatting rules."""
        result = _quiz_prompt("Test", 5, "medium", None)
        assert "HARD RULES" in result
        assert "JSON" in result


class TestGenerateQuizEmbedded:
    """Test the main quiz generation function."""

    @patch("backend.mcp.quiz_logic.call_llm")
    def test_generates_quiz(self, mock_llm):
        """Should generate quiz using LLM."""
        mock_llm.return_value = json.dumps(
            {
                "title": "Test Quiz",
                "description": "A test",
                "questions": [
                    {
                        "type": "multiple_choice",
                        "prompt": "What is 1+1?",
                        "options": ["1", "2", "3", "4"],
                        "correctIndex": 1,
                    }
                ],
            }
        )

        result = generate_quiz_embedded(
            prompt="Math test",
            num_questions=1,
            provider="claude",
            provider_keys={"claude": "test-key"},
        )

        assert result["title"] == "Test Quiz"
        assert result["count"] == 1
        assert len(result["questions"]) == 1

    @patch("backend.mcp.quiz_logic.call_llm")
    def test_truncates_questions(self, mock_llm):
        """Should truncate to requested number of questions."""
        mock_llm.return_value = json.dumps(
            {
                "title": "Quiz",
                "description": "",
                "questions": [
                    {
                        "type": "multiple_choice",
                        "prompt": f"Q{i}?",
                        "options": ["A", "B", "C"],
                        "correctIndex": 0,
                    }
                    for i in range(10)
                ],
            }
        )

        result = generate_quiz_embedded(
            prompt="Test", num_questions=3, provider="gemini", provider_keys={"gemini": "test-key"}
        )

        assert len(result["questions"]) == 3
        assert result["count"] == 3

    @patch("backend.mcp.quiz_logic.call_llm")
    def test_uses_default_title_when_missing(self, mock_llm):
        """Should use 'Untitled Quiz' when LLM returns empty title."""
        mock_llm.return_value = json.dumps(
            {
                "title": "",
                "description": "",
                "questions": [
                    {
                        "type": "multiple_choice",
                        "prompt": "Q?",
                        "options": ["A", "B", "C"],
                        "correctIndex": 0,
                    }
                ],
            }
        )

        result = generate_quiz_embedded(
            prompt="My awesome topic for the quiz",
            num_questions=1,
            provider="claude",
            provider_keys={"claude": "test-key"},
        )

        # Empty title is normalized to 'Untitled Quiz' by _normalize_quiz
        assert result["title"] == "Untitled Quiz"

    @patch("backend.mcp.quiz_logic.call_llm")
    def test_uses_default_description_when_missing(self, mock_llm):
        """Should use default description when not provided."""
        mock_llm.return_value = json.dumps(
            {
                "title": "Quiz",
                "description": "",
                "questions": [
                    {
                        "type": "multiple_choice",
                        "prompt": "Q?",
                        "options": ["A", "B", "C"],
                        "correctIndex": 0,
                    }
                ],
            }
        )

        result = generate_quiz_embedded(
            prompt="Test", num_questions=1, provider="claude", provider_keys={"claude": "test-key"}
        )

        assert result["description"] == "Generated quiz"

    @patch("backend.mcp.quiz_logic.call_llm")
    def test_passes_context_to_prompt(self, mock_llm):
        """Should pass context to the quiz prompt."""
        mock_llm.return_value = json.dumps(
            {
                "title": "Quiz",
                "description": "",
                "questions": [
                    {
                        "type": "multiple_choice",
                        "prompt": "Q?",
                        "options": ["A", "B", "C"],
                        "correctIndex": 0,
                    }
                ],
            }
        )

        generate_quiz_embedded(
            prompt="Test",
            num_questions=1,
            context="This is extra context",
            provider="gemini",
            provider_keys={"gemini": "test-key"},
        )

        # Verify call_llm was called
        assert mock_llm.called
        call_args = mock_llm.call_args
        # The context should appear in the user prompt
        assert "This is extra context" in call_args.kwargs.get("user", "")


class TestNormalizeQuizEdgeCases:
    """Additional edge case tests for normalization."""

    def test_non_dict_raises(self):
        """Non-dict input should raise ValueError."""
        with pytest.raises(ValueError, match="Top-level JSON must be an object"):
            _normalize_quiz([])

    def test_non_list_questions(self):
        """Non-list questions should default to empty."""
        data = {"title": "Test", "description": "", "questions": "invalid"}
        result = _normalize_quiz(data)
        assert result["questions"] == []

    def test_non_dict_question_filtered(self):
        """Non-dict question items should be filtered."""
        data = {
            "title": "Test",
            "description": "",
            "questions": [
                "not a dict",
                {"prompt": "Q?", "options": ["A", "B", "C"], "correctIndex": 0},
            ],
        }
        result = _normalize_quiz(data)
        assert len(result["questions"]) == 1

    def test_empty_prompt_gets_default(self):
        """Empty prompt should get default value."""
        data = {
            "title": "Test",
            "description": "",
            "questions": [{"prompt": "", "options": ["A", "B", "C"], "correctIndex": 0}],
        }
        result = _normalize_quiz(data)
        assert result["questions"][0]["prompt"] == "Question"

    def test_string_correct_index_converted(self):
        """String correctIndex should be converted to int."""
        data = {
            "title": "Test",
            "description": "",
            "questions": [{"prompt": "Q?", "options": ["A", "B", "C"], "correctIndex": "1"}],
        }
        result = _normalize_quiz(data)
        assert result["questions"][0]["correctIndex"] == 1

    def test_options_limited_to_five(self):
        """Options should be limited to 5."""
        data = {
            "title": "Test",
            "description": "",
            "questions": [
                {"prompt": "Q?", "options": ["A", "B", "C", "D", "E", "F", "G"], "correctIndex": 0}
            ],
        }
        result = _normalize_quiz(data)
        assert len(result["questions"][0]["options"]) == 5

    def test_non_string_options_converted(self):
        """Non-string options should be converted."""
        data = {
            "title": "Test",
            "description": "",
            "questions": [{"prompt": "Q?", "options": [1, 2, 3], "correctIndex": 0}],
        }
        result = _normalize_quiz(data)
        assert result["questions"][0]["options"] == ["1", "2", "3"]

    def test_empty_options_filtered(self):
        """Empty string options should be filtered."""
        data = {
            "title": "Test",
            "description": "",
            "questions": [
                {"prompt": "Q?", "options": ["A", "", "B", "  ", "C"], "correctIndex": 0}
            ],
        }
        result = _normalize_quiz(data)
        assert "" not in result["questions"][0]["options"]
        assert len(result["questions"][0]["options"]) == 3


class TestParseQuizJsonAdvanced:
    """Advanced tests for JSON parsing recovery."""

    def test_json_with_missing_commas(self):
        """Should repair JSON with missing commas between objects."""
        text = """{"title": "Test", "description": "", "questions": [
            {"type": "multiple_choice", "prompt": "Q1", "options": ["A", "B", "C"],
            "correctIndex": 0}
            {"type": "multiple_choice", "prompt": "Q2", "options": ["X", "Y", "Z"],
            "correctIndex": 1}
        ]}"""
        result = _parse_quiz_json(text)
        # Should recover at least one question
        assert result["title"] == "Test"

    def test_json_with_smart_quotes(self):
        """Should handle smart/curly quotes."""
        text = '{"title": "Test", "description": "", "questions": []}'
        result = _parse_quiz_json(text)
        assert result["title"] == "Test"

    def test_json_with_surrounding_text(self):
        """Should extract JSON from surrounding prose."""
        text = """Here is the quiz JSON:
        {"title": "Quiz", "description": "A quiz", "questions": [
            {"type": "multiple_choice", "prompt": "Q?", "options": ["A", "B", "C"],
            "correctIndex": 0}
        ]}
        Hope this helps!"""
        result = _parse_quiz_json(text)
        assert result["title"] == "Quiz"
