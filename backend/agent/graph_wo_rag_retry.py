# backend/agent/graph_wo_rag_retry.py
from langgraph.graph import END, StateGraph

from .nodes.draft_code import draft_code_node
from .state import AgentState


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("draft_code", draft_code_node)
    g.set_entry_point("draft_code")
    g.add_edge("draft_code", END)
    return g.compile()


def run_to_code(
    prompt: str,
    provider_keys: dict | None = None,
    provider: str | None = None,
    model: str | None = None,
    max_tries: int = 2,  # kept for forward-compat; unused in this test mode
) -> str:
    app = build_graph()
    initial: AgentState = {
        "user_prompt": prompt,
        "tries": 0,
        "max_tries": max_tries,
    }
    if provider_keys:
        initial["provider_keys"] = provider_keys
    if provider:
        initial["provider"] = provider  # "claude" or "gemini"
    if model:
        initial["model"] = model

    final: AgentState = app.invoke(initial)
    code = final.get("manim_code")
    if not code:
        raise RuntimeError(
            f"Graph produced no 'manim_code'. compile_log={final.get('compile_log')!r}"
        )
    return code
