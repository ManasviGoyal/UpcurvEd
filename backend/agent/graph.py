# backend/agent/graph.py
import json
import logging
import time

from langgraph.graph import END, StateGraph

from backend.config import MAX_CONTEXT_CHARS
from backend.utils.helpers import truncate

# Import to trigger app-level logging configuration (handlers, format, level).
from ..utils import app_logging  # noqa: F401
from .nodes.draft_code import draft_code_node
from .nodes.log_failure import log_failure_node
from .nodes.render import render_manim_node
from .state import AgentState

# Per-module logger; name will look like: "app.backend.agent.graph"
logger = logging.getLogger(f"app.{__name__}")


def _timed_node(name: str, fn):
    """
    Wrap a node function that takes AgentState and returns AgentState,
    and record its execution time in the returned state under 'timings'.
    """

    def wrapper(state: AgentState) -> AgentState:
        start = time.perf_counter()
        new_state = fn(state)  # your node returns a fresh AgentState (dict-like)
        duration = time.perf_counter() - start

        # Ensure we don't crash if a node ever returns None / non-dict
        if not isinstance(new_state, dict):
            return new_state

        timings = list(new_state.get("timings") or [])
        timings.append(
            {
                "step": name,
                "duration_s": duration,
                "tries": int(new_state.get("tries", state.get("tries", 0))),
                "timestamp": time.time(),
            }
        )
        new_state["timings"] = timings
        return new_state

    return wrapper


def _route_after_render(state: AgentState) -> str:
    return "ok" if state.get("render_ok") else "need_fix"


def _route_after_log_failure(state: AgentState) -> str:
    tries = int(state.get("tries", 0))
    max_tries = int(state.get("max_tries", 2))
    return "retry" if tries < max_tries else "give_up"


def build_graph():
    g = StateGraph(AgentState)

    g.add_node("draft_code", _timed_node("draft_code", draft_code_node))
    g.add_node("render", _timed_node("render", render_manim_node))
    g.add_node("log_failure", _timed_node("log_failure", log_failure_node))

    # Entry
    g.set_entry_point("draft_code")

    # Linear edges
    g.add_edge("draft_code", "render")

    # Conditional: render -> END or retrieve
    g.add_conditional_edges(
        "render",
        _route_after_render,
        {"ok": END, "need_fix": "log_failure"},
    )


    # Conditional: log_failure -> draft_code (retry) or END (give up)
    g.add_conditional_edges(
        "log_failure",
        _route_after_log_failure,
        {"retry": "draft_code", "give_up": END},
    )

    return g.compile()


def run_to_code(
    prompt: str,
    provider_keys: dict | None = None,
    provider: str | None = None,
    model: str | None = None,
    max_tries: int = 2,
) -> tuple[str, str | None, bool, int, list[str], str | None]:
    """
    Returns 6 values:
    (manim_code, video_url, render_ok, tries, attempt_job_ids, succeeded_job_id)
    """
    app = build_graph()
    overall_start = time.perf_counter()

    initial: AgentState = {
        "user_prompt": prompt,
        "tries": 0,
        "max_tries": max_tries,
    }
    if provider_keys:
        initial["provider_keys"] = provider_keys
    if provider:
        # e.g. "claude" or "gemini"
        initial["provider"] = provider
    if model:
        initial["model"] = model

    final: AgentState = app.invoke(initial)
    total_duration = time.perf_counter() - overall_start

    code = final.get("manim_code")
    if not code:
        raise RuntimeError(
            f"Graph produced no 'manim_code'. compile_log={final.get('compile_log')!r}"
        )

    # --- metrics collection ---
    timings = final.get("timings", [])
    compile_log = final.get("compile_log") or ""

    record = {
        "total_duration_s": total_duration,
        "timings": timings,
        "render_ok": bool(final.get("render_ok")),
        "tries": final.get("tries"),
        "attempt_job_ids": final.get("attempt_job_ids", []),
        "succeeded_job_id": final.get("succeeded_job_id"),
        # Safe-ish metadata (avoid logging full prompt/code for now)
        "prompt_length": len(prompt),
        "code_length": len(code),
        "compile_log_length": len(compile_log),
        "provider": final.get("provider"),
        "model": final.get("model"),
        "retrieved_docs": truncate(final.get("retrieved_docs"), MAX_CONTEXT_CHARS),
        "timestamp": time.time(),
        "status": "success" if final.get("render_ok") else "failed",
    }

    try:
        # One structured line per generation: easy to grep or ingest
        logger.info("agent_manim_generation %s", json.dumps(record))
    except Exception:
        # Metrics should never break the main code path
        logger.exception("Failed to log agent metrics")

    return (
        code,
        final.get("video_url"),
        bool(final.get("render_ok")),
        final.get("tries"),
        final.get("attempt_job_ids", []),
        final.get("succeeded_job_id"),
    )
