"""Cooperative cancellation for generations that are not a subprocess.

Video already cancels properly: its Manim render is a child process, so
``cancel_job`` can kill it. Everything else -- podcasts, quizzes, worksheets,
diagrams, widgets -- is a sequence of blocking HTTP calls to a model provider
and, for podcasts, a text-to-speech pass. Aborting the browser's request there
only closed the connection; the server kept working on a response nobody would
ever read, still spending the user's tokens.

This module lets those pipelines notice they have been cancelled and stop at the
next safe point. It cannot interrupt an in-flight provider call -- that request
is already paid for -- but it stops every step after it.

The job id travels in a ContextVar rather than through every function signature.
FastAPI runs sync endpoints in a worker thread and copies the context into it, so
each request sees its own value and nothing leaks between concurrent requests.
"""
from __future__ import annotations

import contextvars
import logging
import threading
import time

logger = logging.getLogger(f"app.{__name__}")

# Cancelled ids are kept briefly: long enough for a pipeline mid-step to notice,
# short enough that an id reused later is not born cancelled.
_TTL_SECONDS = 15 * 60

_LOCK = threading.Lock()
_CANCELLED: dict[str, float] = {}

_current_job_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "upcurved_current_job_id", default=None
)


class JobCanceled(RuntimeError):
    """Raised at a checkpoint when the client has cancelled this job."""

    def __init__(self, job_id: str) -> None:
        super().__init__(f"Generation cancelled by the client (job {job_id}).")
        self.job_id = job_id


def _prune_locked(now: float) -> None:
    stale = [key for key, marked in _CANCELLED.items() if now - marked > _TTL_SECONDS]
    for key in stale:
        _CANCELLED.pop(key, None)


def request_cancel(job_id: str | None) -> None:
    """Mark a job cancelled. Safe to call for an id that never existed."""
    if not job_id:
        return
    now = time.time()
    with _LOCK:
        _prune_locked(now)
        _CANCELLED[str(job_id)] = now
    logger.info("job_cancel: cancellation requested for %s", job_id)


def is_canceled(job_id: str | None) -> bool:
    if not job_id:
        return False
    now = time.time()
    with _LOCK:
        _prune_locked(now)
        return str(job_id) in _CANCELLED


def clear(job_id: str | None) -> None:
    """Forget a job. Called when a fresh run starts with the same id."""
    if not job_id:
        return
    with _LOCK:
        _CANCELLED.pop(str(job_id), None)


def bind_current_job(job_id: str | None) -> None:
    """Attach a job id to this request, so checkpoints know what to look up."""
    _current_job_id.set(str(job_id) if job_id else None)


def current_job_id() -> str | None:
    return _current_job_id.get()


def raise_if_canceled() -> None:
    """Stop here if this request's job has been cancelled.

    Called at the start of each model call and between text-to-speech segments --
    points where the next step is expensive and skipping it saves real work.
    """
    job_id = _current_job_id.get()
    if job_id and is_canceled(job_id):
        raise JobCanceled(job_id)
