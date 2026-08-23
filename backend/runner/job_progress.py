"""Live progress for in-flight generation jobs.

The client already mints the ``jobId`` it sends with a generation request and uses
it for ``/jobs/cancel``, so the same id keys this registry. The pipeline reports
which stage it is in; the UI polls ``/jobs/progress`` and shows that instead of a
timer creeping toward an arbitrary cap.

In-process and deliberately lossy: the desktop build runs one backend serving one
user, and a lost progress tick only means the bar updates a moment later. Nothing
here is authoritative -- the generation response is.
"""
from __future__ import annotations

import threading
import time
from typing import Any

# Stages in the order a video generation passes through them. The UI maps these to
# a share of the bar, so adding one here means adding it there too.
STAGES = (
    "planning",      # LLM is writing the scene plan
    "preparing",     # plan parsed, scene code being prepared
    "rendering",     # Manim renders, per scene (has done/total)
    "assembling",    # concat, watermark, subtitles
)

# Entries older than this are dropped on the next access. Long renders refresh
# their entry constantly, so this only reaps jobs that died without cleanup.
_TTL_SECONDS = 30 * 60

_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}


def _prune_locked(now: float) -> None:
    stale = [key for key, value in _JOBS.items() if now - value["updated"] > _TTL_SECONDS]
    for key in stale:
        _JOBS.pop(key, None)


def set_stage(job_id: str | None, stage: str, *, done: int = 0, total: int = 0) -> None:
    """Record the stage a job has entered. Safe to call with a missing job id."""
    if not job_id:
        return
    now = time.time()
    with _LOCK:
        _prune_locked(now)
        _JOBS[str(job_id)] = {
            "stage": str(stage),
            "done": max(0, int(done)),
            "total": max(0, int(total)),
            "updated": now,
        }


def advance(job_id: str | None, *, done: int | None = None) -> None:
    """Move a counted stage forward, keeping the current stage and total."""
    if not job_id:
        return
    key = str(job_id)
    now = time.time()
    with _LOCK:
        entry = _JOBS.get(key)
        if entry is None:
            return
        entry["done"] = int(done) if done is not None else entry["done"] + 1
        if entry["total"]:
            entry["done"] = min(entry["done"], entry["total"])
        entry["updated"] = now


def snapshot(job_id: str | None) -> dict[str, Any] | None:
    """Current progress for a job, or None if nothing has been reported."""
    if not job_id:
        return None
    now = time.time()
    with _LOCK:
        _prune_locked(now)
        entry = _JOBS.get(str(job_id))
        if entry is None:
            return None
        return {
            "job_id": str(job_id),
            "stage": entry["stage"],
            "done": entry["done"],
            "total": entry["total"],
            "age_seconds": round(now - entry["updated"], 2),
        }


def clear(job_id: str | None) -> None:
    """Drop a job's entry once it has finished, failed, or been cancelled."""
    if not job_id:
        return
    with _LOCK:
        _JOBS.pop(str(job_id), None)
