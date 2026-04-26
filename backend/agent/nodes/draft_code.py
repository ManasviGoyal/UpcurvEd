# backend/agent/nodes/draft_code.py
import re

from ..code_sanitize import sanitize_minimally  # minimal, non-restrictive sanitizer
from ..llm.clients import call_llm
from ..prompts import CODE_SYSTEM, build_code_user_prompt
from ..state import AgentState


def _pick_provider(state: AgentState) -> str:
    """Choose an LLM provider based on explicit state or available keys."""
    if "provider" in state and state["provider"]:
        return state["provider"]  # type: ignore
    keys = state.get("provider_keys", {}) or {}
    if keys.get("claude"):
        return "claude"
    if keys.get("gemini"):
        return "gemini"
    raise RuntimeError("No provider keys found in state.")


def _extract_python(text: str) -> str:
    """Remove explanations/backticks if the model adds prose before/around code."""
    if not isinstance(text, str):
        return ""
    m = re.search(r"```(?:python)?\s*(.*?)```", text, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()
    lines = text.splitlines()
    for i, line in enumerate(lines):
        s = line.lstrip()
        if s.startswith(("from ", "import ", "class ", "def ")):
            return "\n".join(lines[i:]).strip()
    return text.strip()


def draft_code_node(state: AgentState) -> AgentState:
    goal = (state.get("user_prompt") or "").strip()
    if not goal:
        raise RuntimeError("draft_code_node: missing user_prompt")

    # Markovian repair inputs
    previous_code = (state.get("previous_code") or "").strip()
    error_context = (state.get("error_context") or "").strip()
    retrieved_docs = (state.get("retrieved_docs") or "").strip()

    # Provider & key
    provider = _pick_provider(state)
    key = (state.get("provider_keys") or {}).get(provider)
    if not key:
        raise RuntimeError(f"draft_code_node: missing API key for '{provider}'")

    # Build the single user prompt with our three-block structure
    user = build_code_user_prompt(
        goal=goal,
        retrieved_docs=retrieved_docs or None,
        previous_code=previous_code or None,
        error_context=error_context or None,
    )

    # Call LLM
    raw = call_llm(
        provider=provider,
        api_key=key,
        model=state.get("model"),
        system=CODE_SYSTEM,
        user=user,
    )

    # Extract python & sanitize (minimal)
    code = _extract_python(raw)
    code = sanitize_minimally(code)

    new_state = dict(state)
    new_state["manim_code"] = code
    return new_state
