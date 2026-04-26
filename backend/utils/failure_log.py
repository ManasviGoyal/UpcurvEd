# backend/utils/failure_log.py
from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

# For safety checks when deleting job dirs
JOBS_ROOT = Path("storage") / "jobs"


def append_failure_log(path: str, entry: dict, *, max_context_chars: int | None = None) -> None:
    """
    Append one JSON line to a compact failure log.
    Ensures the parent directory exists. Optionally truncates entry['error_context'].
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    # Ensure timestamp exists (UTC ISO8601)
    entry = dict(entry)
    entry.setdefault("ts", datetime.now(UTC).isoformat())

    # Optionally truncate the error_context
    if max_context_chars and max_context_chars > 0:
        ctx = entry.get("error_context")
        if isinstance(ctx, str) and len(ctx) > max_context_chars:
            entry["error_context"] = ctx[:max_context_chars] + "…"

    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def cleanup_job_dir(job_dir: str | Path) -> bool:
    """
    Safely delete a job directory under storage/jobs.
    Returns True if removed or didn't exist; False if refused.
    """
    try:
        p = Path(job_dir).resolve()
        root = JOBS_ROOT.resolve()
        # Safety: only allow deletion within storage/jobs
        if root not in p.parents and p != root:
            return False
        shutil.rmtree(p, ignore_errors=True)
        return True
    except Exception:
        return False
