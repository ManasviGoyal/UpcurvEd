# backend/agent/nodes/log_failure.py
from __future__ import annotations

import json
import logging

from backend.config import MAX_CONTEXT_CHARS
from backend.utils import app_logging  # noqa: F401
from backend.utils.helpers import truncate

from ..state import AgentState

# Per-module logger ("app.backend.agent.nodes.log_failure")
logger = logging.getLogger(f"app.{__name__}")


def log_failure_node(state: AgentState) -> AgentState:
    """
    Log a compact failure entry via logger.info.
    Must be called after retrieve_node so that `retrieved_docs` (if any) is present.
    This node never raises; it's safe in failure paths.
    """
    # Only log if it's truly a failed render attempt
    if state.get("render_ok"):
        return state

    try:
        tries_so_far = int(state.get("tries", 0))
    except Exception:
        tries_so_far = 0

    entry = {
        "job_id": state.get("job_id"),
        "provider": state.get("provider"),
        "model": state.get("model"),
        "error": state.get("error") or "render_failed",
        "error_context": truncate(state.get("error_context"), MAX_CONTEXT_CHARS),
        "retrieved_docs": truncate(state.get("retrieved_docs"), MAX_CONTEXT_CHARS),
        "tries": tries_so_far,
        "attempt_job_ids": state.get("attempt_job_ids", []),
    }

    try:
        logger.info("agent_manim_failure %s", json.dumps(entry))
    except Exception:
        # Never fail the graph due to logging problems
        logger.exception("Failed to log failure entry")

    return state
