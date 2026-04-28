import json
import os

try:
    import json5 as _json5
except ImportError:  # optional fallback, continue without json5
    _json5 = None
from typing import Any

from backend.agent.llm.clients import call_llm

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")


def _pick_provider_and_key(
    provider: str | None, provider_keys: dict[str, str] | None
) -> tuple[str, str]:
    """Return (provider, api_key). Prefer explicit provider, else infer from keys."""
    keys = provider_keys or {}
    prov = (provider or "").lower()
    if prov in ("claude", "gemini"):
        key = keys.get(prov) or ""
        if not key:
            raise RuntimeError(f"Missing API key for provider '{prov}'.")
        return prov, key
    # infer
    if keys.get("claude"):
        return "claude", keys["claude"]
    if keys.get("gemini"):
        return "gemini", keys["gemini"]
    raise RuntimeError("No provider keys available. Provide 'claude' or 'gemini' key.")


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        # remove leading fence line
        lines = text.splitlines()
        # drop first line and if last line is a fence, drop it
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines)
    return text


def _parse_quiz_json(text: str) -> dict[str, Any]:
    """Parse LLM output into quiz JSON with multi-step repair + validation.

    Strategy:
    1. Direct load (fast path)
    2. Light repair (_repair_json)
    3. Heuristic fixes for missing commas between objects / stray backticks
    4. Last resort: structural extraction of the outer JSON object
    Post-parse: schema normalization/validation to guarantee required fields.
    """
    cleaned = _strip_code_fences(text)

    # Fast path
    try:
        data = json.loads(cleaned)
        return _normalize_quiz(data)
    except Exception:
        pass

    # First repair pass
    try:
        repaired = _repair_json(cleaned)
        data = json.loads(repaired)
        return _normalize_quiz(data)
    except Exception:
        pass

    # Second pass: insert missing commas between adjacent object boundaries inside arrays
    try:
        second = _insert_missing_commas(_repair_json(cleaned))
        data = json.loads(second)
        return _normalize_quiz(data)
    except Exception:
        pass

    # Json5 lenient parse before last resort if available
    if _json5 is not None:
        try:
            data = _json5.loads(cleaned)
            return _normalize_quiz(data)
        except Exception:
            pass

    # Final attempt: brute force extract outermost {...}
    # and retry repairs with enhanced comma insertion
    try:
        outer = _extract_outer_object(cleaned)
        repaired = _repair_json(outer)
        # Apply comma insertion multiple times to catch nested issues
        for _ in range(3):  # Multiple passes for nested structures
            repaired = _insert_missing_commas(repaired)
        data = json.loads(repaired)
        return _normalize_quiz(data)
    except Exception:
        pass

    # Last resort: try to fix common JSON issues more aggressively
    try:
        outer = _extract_outer_object(cleaned)
        # More aggressive repairs
        repaired = _repair_json(outer)
        # Fix missing commas more comprehensively
        repaired = _insert_missing_commas(repaired)
        # Try to fix unclosed strings/arrays/objects
        repaired = _fix_unclosed_structures(repaired)
        data = json.loads(repaired)
        return _normalize_quiz(data)
    except Exception as e:
        # If all else fails, try to extract just the questions array and rebuild
        try:
            return _extract_and_rebuild_quiz(cleaned)
        except Exception:
            raise RuntimeError(f"Unable to parse quiz JSON after multiple repairs: {e}") from e


def _repair_json(s: str) -> str:
    """
    Best-effort JSON repair for minor LLM formatting issues:
    - Trim text before first '{' and after last '}'
    - Replace smart quotes with standard quotes
    - Remove trailing commas before '}' and ']'
    - Convert unquoted booleans/null from Python style to JSON (True/False/None)
    This is intentionally conservative and does not attempt deep restructuring.
    """
    import re

    # Keep only the outermost JSON object if extra prose surrounds it
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        s = s[start : end + 1]

    # Normalize quotes
    s = (
        s.replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2018", "'")
        .replace("\u2019", "'")
    )
    s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")

    # Remove trailing commas before closing braces/brackets
    s = re.sub(r",\s*([}\]])", r"\1", s)

    # Convert Python-style literals to JSON if they appear unquoted
    s = re.sub(r"\bTrue\b", "true", s)
    s = re.sub(r"\bFalse\b", "false", s)
    s = re.sub(r"\bNone\b", "null", s)

    # Remove stray markdown artifacts or language hints
    s = s.replace("```json", "```")
    # If dangling unmatched quotes, attempt naive balance (count only)
    if s.count('"') % 2 == 1:
        s += '"'
    return s


def _insert_missing_commas(s: str) -> str:
    """Heuristically insert commas between JSON objects/elements that are missing them.
    Handles common LLM JSON errors: missing commas between objects, array elements, and properties.
    """
    import re

    # Pattern 1: Missing comma between adjacent objects in arrays: } { (most common case)
    s = re.sub(r"(\})\s*(\{)", r"\1,\2", s)

    # Pattern 2: Missing comma between closing bracket/brace and opening brace/bracket
    s = re.sub(r"([\]\}])\s*([\[{])", r"\1,\2", s)

    # Pattern 3: Missing comma after quoted value before next quoted key (object properties)
    # Match: "value" whitespace "key": but not if comma already exists
    s = re.sub(r'("(?:[^"\\]|\\.)*")\s+("(?:[^"\\]|\\.)*"\s*:)', r"\1,\2", s)

    # Pattern 4: Missing comma after primitive value before quote (for arrays/objects)
    # Match: number/boolean/null followed by whitespace and quote
    s = re.sub(r'(\d+\.?\d*|true|false|null)\s+(")', r"\1,\2", s)

    # Pattern 5: Missing comma between quoted strings in arrays: "value" "value"
    # Only add if whitespace between and no comma nearby (conservative)
    # Match: "string" whitespace "string" where comma should be
    s = re.sub(r'("(?:[^"\\]|\\.)*")\s+("(?:[^"\\]|\\.)*")(?=\s*[,\]])', r"\1,\2", s)

    return s


def _extract_outer_object(s: str) -> str:
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        return s[start : end + 1]
    return s


def _fix_unclosed_structures(s: str) -> str:
    """Fix unclosed strings, arrays, and objects."""

    # Count braces and brackets to ensure they're balanced
    open_braces = s.count("{")
    close_braces = s.count("}")
    open_brackets = s.count("[")
    close_brackets = s.count("]")

    # Add missing closing braces/brackets at the end
    if open_braces > close_braces:
        s += "}" * (open_braces - close_braces)
    if open_brackets > close_brackets:
        s += "]" * (open_brackets - close_brackets)

    # Fix unclosed strings (simple heuristic: if odd number of quotes, add one at end)
    quote_count = s.count('"')
    if quote_count % 2 == 1:
        # Find the last unclosed quote (rough heuristic)
        last_quote = s.rfind('"')
        if last_quote > 0 and s[last_quote - 1] != "\\":
            # Try to close it before the next structural character
            next_brace = s.find("}", last_quote)
            next_bracket = s.find("]", last_quote)
            next_comma = s.find(",", last_quote)
            end_pos = min(
                [x for x in [next_brace, next_bracket, next_comma, len(s)] if x > last_quote]
            )
            s = s[:end_pos] + '"' + s[end_pos:]

    return s


def _extract_and_rebuild_quiz(text: str) -> dict[str, Any]:
    """Last resort: extract quiz data using regex and rebuild JSON structure."""
    import re

    # Extract title
    title_match = re.search(r'"title"\s*:\s*"([^"]+)"', text)
    title = title_match.group(1) if title_match else "Untitled Quiz"

    # Extract description
    desc_match = re.search(r'"description"\s*:\s*"([^"]*)"', text)
    description = desc_match.group(1) if desc_match else ""

    # Extract questions - look for question objects
    questions = []
    # Pattern: { "type": "...", "prompt": "...", "options": [...], "correctIndex": ... }
    question_pattern = (
        r'\{\s*"type"\s*:\s*"[^"]*"\s*,\s*"prompt"\s*:\s*"([^"]+)"\s*,'
        r'\s*"options"\s*:\s*\[(.*?)\]\s*,\s*"correctIndex"\s*:\s*(\d+)'
    )

    for match in re.finditer(question_pattern, text, re.DOTALL):
        prompt = match.group(1)
        options_str = match.group(2)
        correct_idx = int(match.group(3))

        # Extract options
        options = []
        option_pattern = r'"([^"]+)"'
        for opt_match in re.finditer(option_pattern, options_str):
            options.append(opt_match.group(1))

        if len(options) >= 3 and 0 <= correct_idx < len(options):
            questions.append(
                {
                    "type": "multiple_choice",
                    "prompt": prompt,
                    "options": options,
                    "correctIndex": correct_idx,
                }
            )

    if not questions:
        raise ValueError("Could not extract any valid questions")

    return {
        "title": title,
        "description": description,
        "questions": questions,
    }


def _normalize_quiz(data: dict[str, Any]) -> dict[str, Any]:
    """Ensure quiz object matches expected schema; repair minor type issues."""
    if not isinstance(data, dict):
        raise ValueError("Top-level JSON must be an object.")
    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        title = "Untitled Quiz"
    description = data.get("description")
    if not isinstance(description, str):
        description = ""
    questions = data.get("questions")
    if not isinstance(questions, list):
        questions = []
    norm_questions: list[dict[str, Any]] = []
    for q in questions:
        if not isinstance(q, dict):
            continue
        q.get("type") if isinstance(q.get("type"), str) else "multiple_choice"
        prompt = q.get("prompt") if isinstance(q.get("prompt"), str) else ""
        options = q.get("options") if isinstance(q.get("options"), list) else []
        # Coerce all options to strings and drop empties; deduplicate preserving order
        cleaned_opts: list[str] = []
        seen = set()
        for o in options:
            if not isinstance(o, str):
                try:
                    o = str(o)
                except Exception:
                    continue
            o2 = o.strip()
            if not o2 or o2 in seen:
                continue
            seen.add(o2)
            cleaned_opts.append(o2)
            if len(cleaned_opts) >= 5:
                break
        # Enforce min length
        if len(cleaned_opts) < 3:
            continue
        correct = q.get("correctIndex")
        if isinstance(correct, str) and correct.isdigit():
            correct = int(correct)
        if not isinstance(correct, int) or correct < 0 or correct >= len(cleaned_opts):
            correct = 0
        norm_questions.append(
            {
                "type": "multiple_choice",
                "prompt": prompt.strip() or "Question",
                "options": cleaned_opts,
                "correctIndex": correct,
            }
        )
        if len(norm_questions) >= 50:  # safety cap
            break
    return {
        "title": title.strip(),
        "description": description.strip(),
        "questions": norm_questions,
    }


def _quiz_prompt(prompt: str, num_questions: int, difficulty: str, context: str | None) -> str:
    """Build a very strict JSON-only prompt to minimize LLM formatting errors."""
    context_block = (
        f"\nAdditional context (SRT/script, use only for content; "
        f"DO NOT include it in the JSON):\n{context}\n"
        if context
        else ""
    )
    return (
        # Task
        "You are an expert quiz maker. Produce a multiple-choice quiz "
        "as a single JSON object only, strictly following this schema and rules.\n\n"
        # Explicit schema (keys and types)
        "SCHEMA (keys and types):\n"
        "{\n"
        '  "title": string,\n'
        '  "description": string,\n'
        '  "questions": [\n'
        '    { "type": "multiple_choice", "prompt": string, '
        '"options": [string, ...], "correctIndex": integer }\n'
        "  ]\n"
        "}\n\n"
        # Hard rules to avoid syntax issues
        "HARD RULES (must follow all):\n"
        "1) Output MUST be valid RFC 8259 JSON. "
        "No markdown, no code fences, no comments, no explanations.\n"
        "2) Use double quotes for ALL keys and ALL string values.\n"
        "3) NO trailing commas anywhere.\n"
        "4) The array questions MUST contain exactly {NUM_Q} items.\n"
        '5) Each question MUST have: type="multiple_choice" (exact), '
        "non-empty prompt, options array length 3-5 with unique strings.\n"
        "6) correctIndex MUST be a 0-based integer within the bounds of options, "
        "and the option at that index is the ONLY correct answer.\n"
        "7) Do NOT include null/undefined/NaN, "
        "and do NOT include additional fields beyond the schema.\n"
        "8) The JSON MUST start with '{' and end with '}' "
        "with no leading or trailing text.\n\n"
        # Content directives
        "CONTENT REQUIREMENTS:\n"
        f"- Use exactly {{NUM_Q}} questions.\n"
        f'- Topic/context from the user prompt: "{prompt}"\n'
        f"- Difficulty: {difficulty}\n"
        "- Title and description should be short and informative.\n"
        "- Use context only to craft questions; "
        "DO NOT embed the context text into the JSON.\n\n"
        # Final instruction: replace NUM_Q placeholder
        .replace("{NUM_Q}", str(num_questions))
        + context_block
    )


def _generate_quiz_json_with_call_llm(
    prompt: str,
    num_questions: int,
    difficulty: str,
    context: str | None,
    provider: str | None,
    model: str | None,
    provider_keys: dict[str, str] | None,
) -> dict[str, Any]:
    prov, api_key = _pick_provider_and_key(provider, provider_keys)
    # For Gemini, let the unified client choose its preferred default (gemini-3-flash-preview).
    # For Claude, keep a sensible default.
    use_model = model or ("claude-haiku-4-5" if prov == "claude" else None)
    user_prompt = _quiz_prompt(prompt, num_questions, difficulty, context)
    # Add a strict system instruction to force JSON-only output
    strict_system = (
        "You are a JSON generator. Always return a single valid JSON object. "
        "Never include markdown code fences, explanations, or comments."
    )
    text = call_llm(
        provider=prov,
        api_key=api_key,
        model=use_model,
        system=strict_system,
        user=user_prompt,
        temperature=0.4,  # Moderate temperature for question variety while maintaining accuracy
    )
    return _parse_quiz_json(text)


def generate_quiz_embedded(
    *,
    prompt: str,
    num_questions: int = 5,
    difficulty: str = "medium",
    provider: str | None = None,
    model: str | None = None,
    provider_keys: dict[str, str] | None = None,
    context: str | None = None,
) -> dict[str, Any]:
    """Generate a quiz JSON suitable for direct embedding (no Google Form).

    Returns dict: { title, description, questions: [ {prompt, options, correctIndex} ] }
    Questions array is truncated to ``num_questions`` even if the model returned more.
    """
    quiz = _generate_quiz_json_with_call_llm(
        prompt=prompt,
        num_questions=num_questions,
        difficulty=difficulty,
        context=context,
        provider=provider,
        model=model,
        provider_keys=provider_keys,
    )
    # Safety: ensure exactly num_questions questions (LLM may under/over produce)
    questions = (quiz.get("questions") or [])[:num_questions]
    quiz["questions"] = questions
    return {
        "title": quiz.get("title") or f"Quiz: {prompt[:40]}",
        "description": quiz.get("description") or "Generated quiz",
        "questions": questions,
        "count": len(questions),
    }
