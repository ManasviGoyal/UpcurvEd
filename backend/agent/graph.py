# backend/agent/graph.py
import json
import logging
import os
import time

from langgraph.graph import END, StateGraph

# Import to trigger app-level logging configuration (handlers, format, level).
from ..utils import app_logging  # noqa: F401
from .nodes.draft_code import draft_code_node
from .nodes.log_failure import log_failure_node
from .nodes.render import render_manim_node
from .state import AgentState
from .structured_video import generate_structured_manim_video

logger = logging.getLogger(f"app.{__name__}")


def _timed_node(name: str, fn):
    """
    Wrap a node function that takes AgentState and returns AgentState,
    and record its execution time in the returned state under 'timings'.
    """

    def wrapper(state: AgentState) -> AgentState:
        start = time.perf_counter()
        new_state = fn(state)
        duration = time.perf_counter() - start

        if not isinstance(new_state, dict):
            return new_state

        timings = list(new_state.get("timings") or [])
        timings.append(
            {
                "step": name,
                "duration_s": duration,
                "timestamp": time.time(),
            }
        )
        new_state["timings"] = timings
        return new_state

    return wrapper


def _route_after_render(state: AgentState) -> str:
    return "ok" if state.get("render_ok") else "failed"


def build_graph():
    g = StateGraph(AgentState)

    g.add_node("draft_code", _timed_node("draft_code", draft_code_node))
    g.add_node("render", _timed_node("render", render_manim_node))
    g.add_node("log_failure", _timed_node("log_failure", log_failure_node))

    g.set_entry_point("draft_code")
    g.add_edge("draft_code", "render")

    g.add_conditional_edges(
        "render",
        _route_after_render,
        {"ok": END, "failed": "log_failure"},
    )

    g.add_edge("log_failure", END)

    return g.compile()


def run_to_code(
    prompt: str,
    provider_keys: dict | None = None,
    provider: str | None = None,
    model: str | None = None,
    max_tries: int = 2,
    job_id: str | None = None,
) -> tuple[str, str | None, bool, str | None, str | None]:
    """
    Returns 5 values:
    (manim_code, video_url, render_ok, job_id, failure_detail)

    max_tries is kept only for temporary call-site compatibility and is unused.
    """
    overall_start = time.perf_counter()

    # Default standard video generation now uses the structured scene-bundle
    # pipeline. Set UPCURVED_LEGACY_VIDEO_PIPELINE=1 to temporarily use the old
    # monolithic Manim graph while debugging.
    if os.getenv("UPCURVED_LEGACY_VIDEO_PIPELINE", "0") != "1":
        try:
            structured = generate_structured_manim_video(
                prompt=prompt,
                provider_keys=provider_keys,
                provider=provider,
                model=model,
                job_id=job_id,
            )
            total_duration = time.perf_counter() - overall_start
            code = structured.get("scene_code") or ""
            render_ok = bool(structured.get("ok") and structured.get("video_url"))

            record = {
                "total_duration_s": total_duration,
                "timings": structured.get("scene_results", []),
                "render_ok": render_ok,
                "job_id": structured.get("job_id"),
                "prompt_length": len(prompt),
                "code_length": len(code),
                "compile_log_length": 0,
                "provider": provider,
                "model": model,
                "generation_mode": "structured_scene_bundle",
                "used_fallback": structured.get("used_fallback"),
                "failure_detail": None,
                "timestamp": time.time(),
                "status": "success" if render_ok else "failed",
            }
            try:
                logger.info("agent_manim_generation %s", json.dumps(record))
            except Exception:
                logger.exception("Failed to log agent metrics")

            return (
                code,
                structured.get("video_url"),
                render_ok,
                structured.get("job_id"),
                None if render_ok else "Structured video generation failed.",
            )
        except Exception as structured_error:
            logger.exception(
                "structured_manim_generation failed; falling back to legacy graph: %s",
                structured_error,
            )

    app = build_graph()

    initial: AgentState = {
        "user_prompt": prompt,
    }
    if provider_keys:
        initial["provider_keys"] = provider_keys
    if provider:
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

    timings = final.get("timings", [])
    compile_log = final.get("compile_log") or ""
    render_ok = bool(final.get("render_ok"))
    failure_detail = final.get("error_context") if not render_ok else None

    record = {
        "total_duration_s": total_duration,
        "timings": timings,
        "render_ok": render_ok,
        "job_id": final.get("job_id"),
        "prompt_length": len(prompt),
        "code_length": len(code),
        "compile_log_length": len(compile_log),
        "provider": final.get("provider"),
        "model": final.get("model"),
        "failure_detail": failure_detail,
        "timestamp": time.time(),
        "status": "success" if render_ok else "failed",
    }

    try:
        logger.info("agent_manim_generation %s", json.dumps(record))
    except Exception:
        logger.exception("Failed to log agent metrics")

    return (
        code,
        final.get("video_url"),
        render_ok,
        final.get("job_id"),
        failure_detail,
    )
