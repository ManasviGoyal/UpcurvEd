"""Compact deterministic failure/recovery index for generated artifacts."""

from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.runner.job_runner import STORAGE

JOBS_ROOT = STORAGE / "jobs"
FAILURE_INDEX_PATH = STORAGE / "failure_index.jsonl"

_EXCEPTION_LINE = re.compile(
    r"^(?:[A-Za-z_][\w.]*Error|Exception|RuntimeError|TypeError|ValueError|NameError|"
    r"AttributeError|ImportError|ModuleNotFoundError|SyntaxError|KeyError|IndexError):"
)


def summarize_error(error_text: Any, fallback: str = "Generation failed.", limit: int = 500) -> str:
    """Extract one useful local summary from a traceback without an LLM call."""
    lines = [line.strip() for line in str(error_text or "").splitlines() if line.strip()]
    for line in reversed(lines):
        if _EXCEPTION_LINE.match(line):
            return line[:limit]
    if lines:
        return lines[-1][:limit]
    return str(fallback or "Generation failed.")[:limit]


def append_failure_log(path: str | Path, entry: dict, *, max_context_chars: int | None = None) -> None:
    """Append one JSON object as a line, creating the parent directory when needed."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(entry)
    payload.setdefault("ts", datetime.now(UTC).isoformat())
    if max_context_chars and max_context_chars > 0:
        context = payload.get("error_context")
        if isinstance(context, str) and len(context) > max_context_chars:
            payload["error_context"] = context[:max_context_chars] + "…"
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def append_generation_index(
    *,
    job_id: str,
    status: str,
    stage: str,
    provider: str | None,
    model: str | None,
    affected_scenes: list[int] | None = None,
    error_detail: Any = None,
    summary: str | None = None,
    llm_calls: int | None = None,
    recovery_stages: list[str] | None = None,
    job_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Append a compact index entry for a failure or degraded successful result."""
    scene_values = sorted({int(value) for value in (affected_scenes or []) if int(value) > 0})
    concise = summary or summarize_error(error_detail, fallback=stage.replace("_", " ").title())
    entry: dict[str, Any] = {
        "job_id": str(job_id),
        "status": str(status),
        "stage": str(stage),
        "provider": str(provider or ""),
        "model": str(model or ""),
        "affected_scenes": scene_values,
        "summary": concise,
        "job_dir": str(Path(job_dir).resolve()) if job_dir else str((JOBS_ROOT / job_id).resolve()),
    }
    if llm_calls is not None:
        entry["llm_calls"] = int(llm_calls)
    if recovery_stages:
        entry["recovery_stages"] = list(dict.fromkeys(str(value) for value in recovery_stages))
    append_failure_log(FAILURE_INDEX_PATH, entry)
    return entry


def cleanup_job_dir(job_dir: str | Path) -> bool:
    """Safely delete a directory only when it is inside the resolved active jobs root."""
    try:
        candidate = Path(job_dir).resolve()
        root = JOBS_ROOT.resolve()
        if root not in candidate.parents and candidate != root:
            return False
        shutil.rmtree(candidate, ignore_errors=True)
        return True
    except Exception:
        return False
