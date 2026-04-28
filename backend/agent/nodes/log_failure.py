from __future__ import annotations

import json
import logging

from backend.config import MAX_CONTEXT_CHARS
from backend.utils import app_logging  # noqa: F401
from backend.utils.helpers import truncate

from ..state import AgentState

logger = logging.getLogger(f"app.{__name__}")


def log_failure_node(state: AgentState) -> AgentState:
    """
    Log a compact failure entry via logger.info.
    This node never raises; it is safe in failure paths.
    """
    if state.get("render_ok"):
        return state

    entry = {
        "job_id": state.get("job_id"),
        "provider": state.get("provider"),
        "model": state.get("model"),
        "error": state.get("error") or "render_failed",
        "error_context": truncate(state.get("error_context"), MAX_CONTEXT_CHARS),
    }

    try:
        logger.info("agent_manim_failure %s", json.dumps(entry))
    except Exception:
        logger.exception("Failed to log failure entry")

    return state
