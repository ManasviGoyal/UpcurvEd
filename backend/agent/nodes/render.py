# backend/agent/nodes/render.py
from __future__ import annotations

import re

from backend.config import CLEANUP_FAILED_JOBS, MAX_CONTEXT_CHARS
from backend.utils.failure_log import cleanup_job_dir

from ...runner.job_runner import run_job_from_code
from ..state import AgentState

# Regexes to parse traceback/exception lines
_FINAL_EXC_RE = re.compile(r"^\s*([A-Za-z_]\w*(?:Error|Exception)):\s*(.*)$", re.M)
_FILE_LINE_RE = re.compile(r'File "([^"]+)", line (\d+)', re.I)


def _slice_from_last_manim(stderr: str) -> str:
    """
    Return stderr slice starting at the last manim-internal frame,
    else from the last 'File \"...\", line N' frame, else the whole stderr.
    """
    if not stderr:
        return ""
    norm = stderr.replace("\\", "/").lower()
    idx = norm.rfind("site-packages/manim/")
    if idx != -1:
        return stderr[idx:].strip()
    matches = list(_FILE_LINE_RE.finditer(stderr))
    if matches:
        start = matches[-1].start()
        return stderr[start:].strip()
    return stderr.strip()


def _last_exception_in_text(text: str):
    """Return the last regex match object for an exception line inside given text."""
    last = None
    for m in _FINAL_EXC_RE.finditer(text or ""):
        last = m
    return last


def _first_nonempty_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def _build_error_context(stderr: str, max_chars: int = MAX_CONTEXT_CHARS) -> str:
    """
    ERROR CONTEXT focused on the tail of the traceback:
      - Title = last \"XError: message\" if present in the slice, else first non-empty tail line.
      - Body = content immediately BEFORE that exception line (or the slice itself),
               truncated from the START so we keep the tail closest to the error.
    """
    stderr = stderr or ""
    slice_text = _slice_from_last_manim(stderr)

    m_last = _last_exception_in_text(slice_text)
    if m_last:
        exc = m_last.group(1)
        msg = m_last.group(2)
        title = f"{exc}: {msg}".strip(": ").strip()
        body_src = slice_text[: m_last.start()].rstrip()
    else:
        title = _first_nonempty_line(slice_text) or "Manim render failed"
        body_src = slice_text.rstrip()
        if body_src.endswith(title):
            body_src = body_src[: -len(title)].rstrip()

    if not max_chars or max_chars <= 0:
        return f"{title}\n\n{body_src}".strip()

    remaining = max_chars - len(title) - 2  # reserve for title + blank line
    if remaining <= 0:
        return title[:max_chars].rstrip()

    # Tail-first truncation of body
    if len(body_src) > remaining:
        body = "…" + body_src[-remaining:]
    else:
        body = body_src

    return f"{title}\n\n{body}".strip()


def render_manim_node(state: AgentState) -> AgentState:
    code = state.get("manim_code", "") or ""
    new_state: AgentState = dict(state)

    if not code.strip():
        new_state.update(
            {
                "render_ok": False,
                "video_url": None,
                "compile_log": "",
                "error_log": "No manim_code to render.",
                "previous_code": "",
                "error_context": "ValueError: manim_code missing\n\nNo code provided.",
                "error": "no_code",
            }
        )
        return new_state

    # Run the job and collect logs (runner never raises)
    job = run_job_from_code(code)  # returns {ok, video_url, compile_log, error_log, job_dir, ...}
    ok = bool(job.get("ok"))
    video_url = job.get("video_url")
    compile_log = job.get("compile_log") or ""
    error_log = job.get("error_log") or ""
    job_dir = job.get("job_dir")
    job_id = job.get("job_id")
    error_code = job.get("error")  # e.g., 'render_failed', 'render_timeout', etc.

    render_ok = ok and bool(video_url)

    # Always keep the last attempt code (Markovian repair)
    new_state["previous_code"] = code
    new_state["compile_log"] = compile_log
    new_state["error_log"] = "" if render_ok else (error_log or compile_log)
    new_state["render_ok"] = render_ok
    new_state["video_url"] = video_url if render_ok else None
    # Keep identifiers and error code in state for the logger node
    if job_id:
        new_state["job_id"] = job_id

    # Track all render attempts
    ids = list(state.get("attempt_job_ids", []))
    if job_id:
        ids.append(job_id)
    new_state["attempt_job_ids"] = ids
    if render_ok:
        new_state["succeeded_job_id"] = job_id
        # Clear any stale diagnostics so draft node won't include them
        new_state["error_context"] = ""
        new_state.pop("error", None)
        return new_state

    # Failure: build ERROR CONTEXT for the draft prompt
    stderr = error_log or compile_log or ""
    error_context = _build_error_context(stderr, MAX_CONTEXT_CHARS)
    new_state["error_context"] = error_context
    new_state["error"] = error_code or "render_failed"

    # Optionally delete failed job directory
    if CLEANUP_FAILED_JOBS and job_dir:
        try:
            cleanup_job_dir(job_dir)
        except Exception:
            pass

    return new_state
