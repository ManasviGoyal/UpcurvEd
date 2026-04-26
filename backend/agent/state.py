# backend/agent/state.py
from typing import Any, Literal, TypedDict

Provider = Literal["claude", "gemini"]


class AgentState(TypedDict, total=False):
    # ---- Inputs / routing ----
    user_prompt: str
    provider_keys: dict[str, str]  # {"claude": "...", "gemini": "..."}
    provider: Provider  # optional; if absent we auto-pick by available key
    model: str  # optional model name

    # ---- Retrieval (RAG) ----
    retrieved_docs: str  # formatted docs retrieved from RAG (optional)

    # ---- Draft/Render/Repair loop ----
    manim_code: str  # current draft from draft_code_node
    previous_code: str  # last attempt that was rendered (for repair)

    # Raw logs from runner (truncated there)
    compile_log: str  # manim stdout
    error_log: str  # manim stderr

    # Single-block error context used for prompting (title + tail snippet, capped)
    error_context: str

    # Render outputs / flags
    render_ok: bool
    video_url: str | None  # /static/... when render_ok

    # Retry counters / limits
    tries: int  # incremented in retrieve_node
    max_tries: int

    # Attempt tracking (per-render job ids from runner)
    attempt_job_ids: list[str]  # every render attempt's job_id
    succeeded_job_id: str | None  # job_id that produced final video, if any

    # Runner job metadata (latest render attempt)
    job_id: str | None  # <--- NEW: so log_failure_node can see it

    # Instrumentation / metrics
    timings: list[dict[str, Any]]  # <--- NEW: per-node timing info

    # ---- Misc artifacts for UI/debug ----
    artifacts: dict[str, Any]
