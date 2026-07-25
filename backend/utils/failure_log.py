"""Privacy-safe generation audit, export, and diagnostic-retention helpers."""

from __future__ import annotations

import json
import os
import re
import shutil
import uuid
import zipfile
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from backend.runner.job_runner import STORAGE

JOBS_ROOT = STORAGE / "jobs"
GENERATION_AUDIT_PATH = STORAGE / "generation_audit.jsonl"
_INSTALLATION_ID_PATH = STORAGE / ".generation_installation_id"
_EXPORTS_ROOT = STORAGE / "exports"
_RETENTION_MARKER = ".diagnostic_retention.json"
_SCHEMA_VERSION = 2

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


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _installation_id() -> str:
    """Return a random installation identifier that contains no user information."""
    try:
        if _INSTALLATION_ID_PATH.exists():
            existing = _INSTALLATION_ID_PATH.read_text(encoding="utf-8").strip()
            if re.fullmatch(r"[a-f0-9-]{16,64}", existing, flags=re.IGNORECASE):
                return existing
        value = str(uuid.uuid4())
        _INSTALLATION_ID_PATH.parent.mkdir(parents=True, exist_ok=True)
        _INSTALLATION_ID_PATH.write_text(value + "\n", encoding="utf-8")
        return value
    except Exception:
        # The audit should never break generation merely because the identifier cannot persist.
        return "unavailable"


def _clean_text(value: Any, limit: int = 300) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _clean_error_summary(value: Any, limit: int = 500) -> str:
    text = _clean_text(value, limit * 2)
    text = re.sub(r"/(?:Users|home)/[^\s:]+(?:/[^\s:]+)*", "[local path]", text)
    text = re.sub(r"[A-Za-z]:\\[^\s:]+(?:\\[^\s:]+)*", "[local path]", text)
    text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[email]", text)
    text = re.sub(r"sk-[A-Za-z0-9_-]+", "[key]", text)
    return text[:limit]


def _clean_int_list(values: Iterable[Any] | None) -> list[int]:
    output: set[int] = set()
    for value in values or []:
        try:
            number = int(value)
        except Exception:
            continue
        if number > 0:
            output.add(number)
    return sorted(output)


def _clean_string_list(values: Iterable[Any] | None, *, limit: int = 20) -> list[str]:
    output: list[str] = []
    for value in values or []:
        text = _clean_text(value, 240)
        if text and text not in output:
            output.append(text)
        if len(output) >= limit:
            break
    return output


def _clean_script_adjustments(values: Iterable[Any] | None) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for value in values or []:
        if not isinstance(value, dict):
            continue
        try:
            scene = int(value.get("scene"))
        except Exception:
            continue
        if scene <= 0:
            continue
        changes = _clean_string_list(value.get("changes") or [], limit=20)
        if not changes:
            continue
        output.append(
            {
                "scene": scene,
                "stage": _clean_text(value.get("stage"), 80),
                "changes": changes,
            }
        )
        if len(output) >= 20:
            break
    return output


def append_generation_audit(entry: dict[str, Any]) -> dict[str, Any]:
    """Append one privacy-safe generation record to ``generation_audit.jsonl``.

    The caller supplies only structured generation metrics. This function intentionally drops
    prompts, narration, scripts, API keys, chat identifiers, user names, and local paths.
    """
    payload: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "timestamp": _now_iso(),
        "installation_id": _installation_id(),
        "app_version": _clean_text(
            os.getenv("UPCURVED_APP_VERSION") or os.getenv("APP_VERSION") or "unknown",
            80,
        ),
        "job_id": _clean_text(entry.get("job_id"), 100),
        "operation": _clean_text(entry.get("operation") or "generate", 40),
        "outcome": _clean_text(entry.get("outcome") or "unknown", 80),
        "provider": _clean_text(entry.get("provider"), 80),
        "model": _clean_text(entry.get("model"), 180),
        "llm_calls": max(0, int(entry.get("llm_calls") or 0)),
        "total_scenes": max(0, int(entry.get("total_scenes") or 0)),
        "creative_scenes": max(0, int(entry.get("creative_scenes") or 0)),
        "rendered_initially": max(0, int(entry.get("rendered_initially") or 0)),
        "plan_repaired_by_model": bool(entry.get("plan_repaired_by_model")),
        "sanitizer_repaired_scenes": _clean_int_list(
            entry.get("sanitizer_repaired_scenes")
        ),
        "render_repaired_scenes": _clean_int_list(entry.get("render_repaired_scenes")),
        "simplified_scene_ids": _clean_int_list(entry.get("simplified_scene_ids")),
        "component_fallback_scene_ids": _clean_int_list(
            entry.get("component_fallback_scene_ids")
        ),
        "recovery_stages": _clean_string_list(entry.get("recovery_stages") or []),
        "voice_retry_count": max(0, int(entry.get("voice_retry_count") or 0)),
        "transport_salvages": max(0, int(entry.get("transport_salvages") or 0)),
        "local_adjustments": {
            "json_plan_punctuation_repaired": bool(
                entry.get("local_json_plan_repair")
            ),
            "plan": _clean_string_list(entry.get("local_plan_adjustments") or []),
            "scripts": _clean_script_adjustments(
                entry.get("local_script_adjustments") or []
            ),
        },
        "duration_seconds": round(max(0.0, float(entry.get("duration_seconds") or 0.0)), 3),
    }

    failure_stage = _clean_text(entry.get("failure_stage"), 100)
    if failure_stage:
        payload["failure_stage"] = failure_stage
    during_stage = _clean_text(entry.get("during_stage"), 100)
    if during_stage:
        payload["during_stage"] = during_stage
    error_category = _clean_text(entry.get("error_category"), 100)
    if error_category:
        payload["error_category"] = error_category
    if entry.get("retryable") is not None:
        payload["retryable"] = bool(entry.get("retryable"))
    affected = _clean_int_list(entry.get("affected_scenes"))
    if affected:
        payload["affected_scenes"] = affected
    error_summary = _clean_error_summary(entry.get("error_summary"), 500)
    if error_summary:
        payload["error_summary"] = error_summary

    GENERATION_AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with GENERATION_AUDIT_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    return payload


def _parse_timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except Exception:
        return None


def mark_diagnostic_retention(
    *,
    job_id: str,
    status: str,
    has_final_artifact: bool,
) -> None:
    """Mark an abnormal job so its detailed diagnostics can be pruned later."""
    job_dir = (JOBS_ROOT / str(job_id)).resolve()
    try:
        root = JOBS_ROOT.resolve()
        if root not in job_dir.parents:
            return
        job_dir.mkdir(parents=True, exist_ok=True)
        marker = {
            "created_at": _now_iso(),
            "status": _clean_text(status, 80),
            "has_final_artifact": bool(has_final_artifact),
        }
        (job_dir / _RETENTION_MARKER).write_text(
            json.dumps(marker, ensure_ascii=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass


def _strip_job_diagnostics(job_dir: Path) -> None:
    """Remove detailed diagnostic material while preserving user-facing artifacts."""
    for name in (
        "logs",
        "structured_plan.json",
        "structured_scene_results.json",
        "generation_diagnostics.json",
        _RETENTION_MARKER,
    ):
        target = job_dir / name
        try:
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            elif target.exists():
                target.unlink()
        except Exception:
            pass


def prune_diagnostic_bundles(
    *,
    max_abnormal_runs: int | None = None,
    max_age_days: int | None = None,
) -> dict[str, int]:
    """Prune old detailed diagnostics without deleting successful final artifacts."""
    max_runs = max(1, int(max_abnormal_runs or os.getenv("UPCURVED_DIAGNOSTIC_MAX_RUNS", "20")))
    age_days = max(1, int(max_age_days or os.getenv("UPCURVED_DIAGNOSTIC_MAX_AGE_DAYS", "30")))
    cutoff = datetime.now(UTC) - timedelta(days=age_days)
    records: list[tuple[datetime, Path, dict[str, Any]]] = []

    try:
        JOBS_ROOT.mkdir(parents=True, exist_ok=True)
        for marker_path in JOBS_ROOT.glob(f"*/{_RETENTION_MARKER}"):
            try:
                data = json.loads(marker_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            created = _parse_timestamp(data.get("created_at"))
            if created is None:
                try:
                    created = datetime.fromtimestamp(marker_path.stat().st_mtime, tz=UTC)
                except Exception:
                    created = datetime.now(UTC)
            records.append((created, marker_path.parent, data))
    except Exception:
        return {"pruned": 0, "remaining": 0}

    records.sort(key=lambda item: item[0], reverse=True)
    keep_paths = {path for _created, path, _data in records[:max_runs]}
    pruned = 0
    for created, job_dir, data in records:
        should_prune = created < cutoff or job_dir not in keep_paths
        if not should_prune:
            continue
        try:
            if bool(data.get("has_final_artifact")):
                _strip_job_diagnostics(job_dir)
            else:
                shutil.rmtree(job_dir, ignore_errors=True)
            pruned += 1
        except Exception:
            pass

    remaining = max(0, len(records) - pruned)
    return {"pruned": pruned, "remaining": remaining}


def _read_audit_entries() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not GENERATION_AUDIT_PATH.exists():
        return entries
    try:
        with GENERATION_AUDIT_PATH.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    value = json.loads(text)
                except Exception:
                    continue
                if isinstance(value, dict):
                    entries.append(value)
    except Exception:
        return []
    return entries


def build_generation_summary(entries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Build a deterministic aggregate summary from audit records."""
    values = entries if entries is not None else _read_audit_entries()
    outcomes = Counter(str(item.get("outcome") or "unknown") for item in values)
    operations = Counter(str(item.get("operation") or "generate") for item in values)
    providers = Counter(str(item.get("provider") or "unknown") for item in values)
    failure_stages = Counter(
        str(item.get("failure_stage"))
        for item in values
        if str(item.get("failure_stage") or "").strip()
    )
    recovery_stages: Counter[str] = Counter()
    error_categories: Counter[str] = Counter()
    during_stages: Counter[str] = Counter()
    local_plan_adjustments: Counter[str] = Counter()
    local_script_adjustments: Counter[str] = Counter()
    total_duration = 0.0
    total_voice_retries = 0
    total_transport_salvages = 0
    model_rows: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "runs": 0,
            "llm_calls": 0,
            "duration_seconds": 0.0,
            "outcomes": Counter(),
            "creative_scenes": 0,
            "fallback_scenes": 0,
            "simplified_scenes": 0,
        }
    )

    for item in values:
        duration = max(0.0, float(item.get("duration_seconds") or 0.0))
        total_duration += duration
        recovery_stages.update(str(value) for value in item.get("recovery_stages") or [])
        if str(item.get("error_category") or "").strip():
            error_categories[str(item.get("error_category"))] += 1
        if str(item.get("during_stage") or "").strip():
            during_stages[str(item.get("during_stage"))] += 1
        total_voice_retries += int(item.get("voice_retry_count") or 0)
        total_transport_salvages += int(item.get("transport_salvages") or 0)
        local = item.get("local_adjustments")
        if isinstance(local, dict):
            local_plan_adjustments.update(
                str(value) for value in local.get("plan") or [] if str(value).strip()
            )
            for script_entry in local.get("scripts") or []:
                if not isinstance(script_entry, dict):
                    continue
                local_script_adjustments.update(
                    str(value)
                    for value in script_entry.get("changes") or []
                    if str(value).strip()
                )

        provider = str(item.get("provider") or "unknown")
        model = str(item.get("model") or "unknown")
        key = f"{provider}::{model}"
        row = model_rows[key]
        row["runs"] += 1
        row["llm_calls"] += int(item.get("llm_calls") or 0)
        row["duration_seconds"] += duration
        row["creative_scenes"] += int(item.get("creative_scenes") or 0)
        row["fallback_scenes"] += len(item.get("component_fallback_scene_ids") or [])
        row["simplified_scenes"] += len(item.get("simplified_scene_ids") or [])
        row["outcomes"][str(item.get("outcome") or "unknown")] += 1

    by_model: list[dict[str, Any]] = []
    for key, row in sorted(model_rows.items()):
        provider, model = key.split("::", 1)
        runs = int(row["runs"])
        by_model.append(
            {
                "provider": provider,
                "model": model,
                "runs": runs,
                "average_llm_calls": round(row["llm_calls"] / runs, 3) if runs else 0.0,
                "average_duration_seconds": (
                    round(row["duration_seconds"] / runs, 3) if runs else 0.0
                ),
                "creative_scenes": int(row["creative_scenes"]),
                "fallback_scenes": int(row["fallback_scenes"]),
                "simplified_scenes": int(row["simplified_scenes"]),
                "outcomes": dict(sorted(row["outcomes"].items())),
            }
        )

    return {
        "schema_version": _SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "total_runs": len(values),
        "average_duration_seconds": round(total_duration / len(values), 3) if values else 0.0,
        "operations": dict(sorted(operations.items())),
        "outcomes": dict(sorted(outcomes.items())),
        "providers": dict(sorted(providers.items())),
        "failure_stages": dict(sorted(failure_stages.items())),
        "during_stages": dict(sorted(during_stages.items())),
        "error_categories": dict(sorted(error_categories.items())),
        "recovery_stages": dict(sorted(recovery_stages.items())),
        "voice_retries": total_voice_retries,
        "transport_salvages": total_transport_salvages,
        "local_plan_adjustments": dict(sorted(local_plan_adjustments.items())),
        "local_script_adjustments": dict(sorted(local_script_adjustments.items())),
        "by_model": by_model,
    }


def build_generation_export() -> Path:
    """Create a small privacy-safe zip containing the audit, summary, and README."""
    _EXPORTS_ROOT.mkdir(parents=True, exist_ok=True)
    for old in _EXPORTS_ROOT.glob("upcurved_generation_diagnostics_*.zip"):
        try:
            old.unlink()
        except Exception:
            pass

    entries = _read_audit_entries()
    summary = build_generation_summary(entries)
    date_stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    export_path = _EXPORTS_ROOT / f"upcurved_generation_diagnostics_{date_stamp}.zip"
    readme = """UpcurvEd generation diagnostics

This archive contains privacy-safe, local generation-performance data.
It does not include prompts, chat messages, narration, generated scripts, API keys,
user names, email addresses, local filesystem paths, or full tracebacks.

Files:
- generation_audit.jsonl: one compact JSON record per structured-video generation or edit.
- generation_summary.json: deterministic aggregate counts by outcome, provider, model,
  failure stage, root error category, service retries, and recovery path.
"""

    with zipfile.ZipFile(export_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if GENERATION_AUDIT_PATH.exists():
            archive.write(GENERATION_AUDIT_PATH, arcname="generation_audit.jsonl")
        else:
            archive.writestr("generation_audit.jsonl", "")
        archive.writestr(
            "generation_summary.json",
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        )
        archive.writestr("README.txt", readme)
    return export_path


# Backward-compatible aliases for any older call sites outside structured_video.py.
def append_failure_log(path: str | Path, entry: dict, *, max_context_chars: int | None = None) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(entry)
    payload.setdefault("ts", _now_iso())
    if max_context_chars and max_context_chars > 0:
        context = payload.get("error_context")
        if isinstance(context, str) and len(context) > max_context_chars:
            payload["error_context"] = context[:max_context_chars] + "…"
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def cleanup_job_dir(job_dir: str | Path) -> bool:
    try:
        candidate = Path(job_dir).resolve()
        root = JOBS_ROOT.resolve()
        if root not in candidate.parents and candidate != root:
            return False
        shutil.rmtree(candidate, ignore_errors=True)
        return True
    except Exception:
        return False
