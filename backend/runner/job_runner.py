"""Shared Manim job runner for local/cloud UpcurvEd rendering.

The runner writes complete diagnostics under ``STORAGE/jobs/<job_id>`` and always returns a
uniform dictionary instead of raising. Structured videos may disable per-scene watermarks and
apply one continuous watermark after concatenation.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

STORAGE = Path(os.getenv("UPCURVED_STORAGE_DIR", "storage")).expanduser()
try:
    (STORAGE / "jobs").mkdir(parents=True, exist_ok=True)
except Exception:
    STORAGE = Path(tempfile.mkdtemp(prefix="upcurved_storage_"))
    (STORAGE / "jobs").mkdir(parents=True, exist_ok=True)

ACTIVE_PROCS: dict[str, subprocess.Popen[str]] = {}
_RUNTIME_PREFLIGHT_SUCCESS: dict[str, Any] | None = None
MAX_LOG_BYTES = int(os.getenv("MAX_LOG_BYTES", "200000"))
PREFLIGHT_TIMEOUT_SECONDS = int(os.getenv("UPCURVED_PREFLIGHT_TIMEOUT_SECONDS", "180"))

# Repo root: <root>/backend/runner/job_runner.py
BACKEND_IMPORT_ROOT = Path(__file__).resolve().parents[2]


def _subprocess_env() -> dict[str, str]:
    """Environment for child processes that must be able to ``import backend``.

    Generated scenes import backend.tts.manim_service for narration. The desktop
    build sets PYTHONSAFEPATH=1, which stops Python from putting the working
    directory on sys.path, so the import has to be guaranteed explicitly rather
    than inherited from cwd.
    """
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    root = str(BACKEND_IMPORT_ROOT)
    if root not in existing.split(os.pathsep):
        env["PYTHONPATH"] = f"{root}{os.pathsep}{existing}" if existing else root
    return env


def to_static_url(path: Path) -> str:
    return f"/static/{path.relative_to(STORAGE)}"


def _truncate(value: str | None, limit: int = MAX_LOG_BYTES) -> str:
    if not value:
        return ""
    return value if len(value) <= limit else value[:limit]


def _kill_proc_tree(proc: subprocess.Popen[str]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        pass


def _runner_metadata(job_dir: Path, scene_py: Path | None = None) -> dict[str, str]:
    return {
        "job_dir": str(job_dir.resolve()),
        "storage_dir": str(STORAGE.resolve()),
        "scene_path": str(scene_py.resolve()) if scene_py is not None else "",
        "interpreter": str(Path(sys.executable).resolve()),
    }


def check_manim_runtime(timeout_seconds: int | None = None) -> dict[str, Any]:
    """Verify the exact interpreter used by the runner can load the render stack.

    This is deliberately independent of generated scene code. A missing or broken Manim,
    plugin, voiceover, or TTS installation should be reported before an LLM call is spent.

    The import costs a couple of seconds warm, but a first launch on Windows can be an
    order of magnitude slower while the antivirus scans the freshly unpacked runtime.
    Only success is cached, so a timeout here re-runs on every job and no video can ever
    be produced -- the ceiling has to clear a cold start, not a warm one.
    """
    if timeout_seconds is None:
        timeout_seconds = PREFLIGHT_TIMEOUT_SECONDS
    global _RUNTIME_PREFLIGHT_SUCCESS
    if _RUNTIME_PREFLIGHT_SUCCESS is not None:
        return dict(_RUNTIME_PREFLIGHT_SUCCESS)

    command = [
        sys.executable,
        "-c",
        (
            "import manim; import manim_voiceover; "
            "from backend.tts.manim_service import EdgeTTSService; "
            "print('Manim runtime OK')"
        ),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=_subprocess_env(),
        )
        result = {
            "ok": completed.returncode == 0,
            "command": command,
            "stdout": _truncate(completed.stdout),
            "stderr": _truncate(completed.stderr),
            "returncode": completed.returncode,
            "interpreter": str(Path(sys.executable).resolve()),
            "storage_dir": str(STORAGE.resolve()),
        }
        if result["ok"]:
            _RUNTIME_PREFLIGHT_SUCCESS = dict(result)
        return result
    except Exception as exc:
        return {
            "ok": False,
            "command": command,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
            "returncode": None,
            "interpreter": str(Path(sys.executable).resolve()),
            "storage_dir": str(STORAGE.resolve()),
        }


def _inject_watermark(code: str) -> str:
    watermark_init = """        # Initialize watermark once
        if not hasattr(self, '_watermark_added'):
            from manim import Rectangle, Text, UR

            self._watermark_text = Text("Generated using UpcurvEd", font_size=24, color="white")
            self._watermark_text.set_opacity(0.8)
            self._watermark_text.to_corner(UR, buff=0.1)
            self._watermark_bg = Rectangle(
                width=self._watermark_text.width + 0.3,
                height=self._watermark_text.height + 0.2,
                fill_opacity=0.6,
                fill_color="black",
                stroke_width=0,
            )
            self._watermark_bg.move_to(self._watermark_text.get_center())
            self.add(self._watermark_bg, self._watermark_text)
            self._watermark_added = True

"""
    watermark_readd = """        # Re-add watermark after cleanup
        if hasattr(self, '_watermark_added') and self._watermark_added:
            if self._watermark_bg not in self.mobjects:
                self.add(self._watermark_bg)
            if self._watermark_text not in self.mobjects:
                self.add(self._watermark_text)

"""
    cleanup_modify = """        # Modify cleanup to exclude watermark
        snapshot = [m for m in self.mobjects if not (
            hasattr(self, '_watermark_bg') and m in [self._watermark_bg, self._watermark_text]
        )]
"""

    pattern_start = r"(def\s+construct\s*\([^)]*\)\s*:\s*\n)"
    modified = re.sub(
        pattern_start,
        lambda match: match.group(1) + watermark_init,
        code,
        count=1,
        flags=re.MULTILINE,
    )
    if modified == code:
        modified = re.sub(
            r"(def\s+construct\s*\([^)]*\)\s*:)",
            r"\1\n" + watermark_init,
            code,
            count=1,
            flags=re.MULTILINE,
        )
    modified = re.sub(
        r"snapshot\s*=\s*list\(self\.mobjects\)",
        cleanup_modify.strip(),
        modified,
        flags=re.MULTILINE,
    )
    modified = re.sub(
        r"(self\.wait\(0\.1\))",
        r"\1\n" + watermark_readd,
        modified,
        flags=re.MULTILINE,
    )
    return modified


def _base_result(
    *,
    ok: bool,
    status: str,
    error: str | None,
    job_id: str,
    job_dir: Path,
    scene_py: Path,
    video_url: str | None,
    compile_log: str = "",
    error_log: str = "",
    logs: dict[str, str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": ok,
        "status": status,
        "error": error,
        "job_id": job_id,
        "video_url": video_url,
        "compile_log": _truncate(compile_log),
        "error_log": _truncate(error_log),
        "logs": logs or {"stdout_url": "", "stderr_url": "", "cmd_url": ""},
        **_runner_metadata(job_dir, scene_py),
    }
    result.update(extra)
    return result


def run_job_from_code(
    code: str,
    scene_name: str = "GeneratedScene",
    timeout_seconds: int = 600,
    job_id: str | None = None,
    inject_watermark: bool = True,
    retain_logs: bool = True,
) -> dict[str, Any]:
    """Compile, lint, and render one complete Manim script. Never raises."""
    job_id = job_id or str(uuid.uuid4())[:8]
    job_dir = STORAGE / "jobs" / job_id
    out_dir = job_dir / "out"
    logs_dir = job_dir / "logs"
    job_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    if inject_watermark:
        code = _inject_watermark(code)

    scene_py = job_dir / "scene.py"
    scene_py.write_text(code, encoding="utf-8")

    # Distinguish Python syntax/compile failures from Manim runtime failures.
    try:
        compile(code, str(scene_py), "exec")
        if retain_logs:
            (logs_dir / "compile_ok.txt").write_text("ok\n", encoding="utf-8")
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        (logs_dir / "compile_error.txt").write_text(detail + "\n", encoding="utf-8")
        return _base_result(
            ok=False,
            status="error",
            error="compile_failed",
            job_id=job_id,
            job_dir=job_dir,
            scene_py=scene_py,
            video_url=None,
            error_log=detail,
            logs={
                "stdout_url": "",
                "stderr_url": to_static_url(logs_dir / "compile_error.txt"),
                "cmd_url": "",
            },
            compile_error_url=to_static_url(logs_dir / "compile_error.txt"),
        )

    runner_env = _subprocess_env()
    ffmpeg_path = runner_env.get("UPCURVED_FFMPEG_PATH", "").strip()
    if ffmpeg_path:
        ffmpeg_dir = str(Path(ffmpeg_path).parent)
        runner_env["PATH"] = f"{ffmpeg_dir}{os.pathsep}{runner_env.get('PATH', '')}"
        runner_env["FFMPEG_BINARY"] = ffmpeg_path
        runner_env["IMAGEIO_FFMPEG_EXE"] = ffmpeg_path

    lint_text = ""
    try:
        lint_proc = subprocess.run(
            [sys.executable, "-m", "pyflakes", str(scene_py)],
            capture_output=True,
            text=True,
            timeout=20,
            env=runner_env,
        )
        lint_text = (lint_proc.stdout or "") + (lint_proc.stderr or "")
        if retain_logs or lint_text.strip() or lint_proc.returncode != 0:
            (logs_dir / "lint.txt").write_text(lint_text, encoding="utf-8")
        if lint_proc.returncode != 0 and os.getenv("LINT_STRICT", "0") == "1":
            return _base_result(
                ok=False,
                status="error",
                error="lint_failed",
                job_id=job_id,
                job_dir=job_dir,
                scene_py=scene_py,
                video_url=None,
                compile_log=lint_text,
                logs={
                    "stdout_url": to_static_url(logs_dir / "lint.txt"),
                    "stderr_url": "",
                    "cmd_url": "",
                },
                lint_url=to_static_url(logs_dir / "lint.txt"),
            )
    except FileNotFoundError:
        pass
    except subprocess.TimeoutExpired as exc:
        (logs_dir / "lint_timeout.txt").write_text(str(exc), encoding="utf-8")
        if os.getenv("LINT_STRICT", "0") == "1":
            return _base_result(
                ok=False,
                status="error",
                error="lint_timeout",
                job_id=job_id,
                job_dir=job_dir,
                scene_py=scene_py,
                video_url=None,
                error_log=str(exc),
                logs={
                    "stdout_url": "",
                    "stderr_url": to_static_url(logs_dir / "lint_timeout.txt"),
                    "cmd_url": "",
                },
                lint_timeout_url=to_static_url(logs_dir / "lint_timeout.txt"),
            )

    stdout = ""
    stderr = ""
    proc: subprocess.Popen[str] | None = None
    cmd = [
        sys.executable,
        "-m",
        "manim",
        "-v",
        "WARNING",
        "-ql",
        str(scene_py),
        scene_name,
        "-o",
        "video.mp4",
        "--media_dir",
        str(out_dir),
    ]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
            env=runner_env,
        )
        ACTIVE_PROCS[job_id] = proc
        try:
            stdout, stderr = proc.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            _kill_proc_tree(proc)
            try:
                stdout, stderr = proc.communicate(timeout=2)
            except Exception:
                pass
            (logs_dir / "timeout.txt").write_text(str(exc), encoding="utf-8")
            (logs_dir / "manim_cmd.txt").write_text(" ".join(cmd), encoding="utf-8")
            (logs_dir / "manim_stdout.txt").write_text(stdout or "", encoding="utf-8")
            (logs_dir / "manim_stderr.txt").write_text(stderr or "", encoding="utf-8")
            (logs_dir / "returncode.txt").write_text("timeout", encoding="utf-8")
            return _base_result(
                ok=False,
                status="error",
                error="render_timeout",
                job_id=job_id,
                job_dir=job_dir,
                scene_py=scene_py,
                video_url=None,
                compile_log=stdout,
                error_log=stderr or str(exc),
                logs={
                    "stdout_url": to_static_url(logs_dir / "manim_stdout.txt"),
                    "stderr_url": to_static_url(logs_dir / "manim_stderr.txt"),
                    "cmd_url": to_static_url(logs_dir / "manim_cmd.txt"),
                },
                timeout_url=to_static_url(logs_dir / "timeout.txt"),
                render_command=cmd,
            )

        mp4s = sorted(out_dir.rglob("*.mp4"))
        failed_render = proc.returncode != 0 or not mp4s
        if retain_logs or failed_render:
            (logs_dir / "manim_cmd.txt").write_text(" ".join(cmd), encoding="utf-8")
            (logs_dir / "manim_stdout.txt").write_text(stdout or "", encoding="utf-8")
            (logs_dir / "manim_stderr.txt").write_text(stderr or "", encoding="utf-8")
            (logs_dir / "returncode.txt").write_text(str(proc.returncode), encoding="utf-8")

        if failed_render:
            (logs_dir / "out_dir_listing.txt").write_text(
                "\n".join(str(path) for path in out_dir.rglob("*")),
                encoding="utf-8",
            )
            return _base_result(
                ok=False,
                status="error",
                error="render_failed",
                job_id=job_id,
                job_dir=job_dir,
                scene_py=scene_py,
                video_url=None,
                compile_log=stdout,
                error_log=stderr,
                logs={
                    "stdout_url": to_static_url(logs_dir / "manim_stdout.txt"),
                    "stderr_url": to_static_url(logs_dir / "manim_stderr.txt"),
                    "cmd_url": to_static_url(logs_dir / "manim_cmd.txt"),
                },
                listing_url=to_static_url(logs_dir / "out_dir_listing.txt"),
                returncode_url=to_static_url(logs_dir / "returncode.txt"),
                render_command=cmd,
            )

        newest = max(mp4s, key=lambda path: path.stat().st_mtime)
        final_video = job_dir / "video.mp4"
        shutil.copyfile(newest, final_video)

        srt_file = newest.with_suffix(".srt")
        if srt_file.exists():
            try:
                srt_text = srt_file.read_text(encoding="utf-8", errors="ignore")
                vtt_body = re.sub(
                    r"^(\d{2}:\d{2}:\d{2}),(\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}),(\d{3})",
                    r"\1.\2 --> \3.\4",
                    srt_text,
                    flags=re.MULTILINE,
                )
                vtt_lines = [
                    line for line in vtt_body.splitlines() if not re.match(r"^\s*\d+\s*$", line)
                ]
                (job_dir / "video.vtt").write_text(
                    "WEBVTT\n\n" + "\n".join(vtt_lines).strip() + "\n",
                    encoding="utf-8",
                )
            except Exception:
                pass

        return _base_result(
            ok=True,
            status="ok",
            error=None,
            job_id=job_id,
            job_dir=job_dir,
            scene_py=scene_py,
            video_url=to_static_url(final_video),
            compile_log=stdout,
            logs=(
                {
                    "stdout_url": to_static_url(logs_dir / "manim_stdout.txt"),
                    "stderr_url": to_static_url(logs_dir / "manim_stderr.txt"),
                    "cmd_url": to_static_url(logs_dir / "manim_cmd.txt"),
                }
                if retain_logs
                else {"stdout_url": "", "stderr_url": "", "cmd_url": ""}
            ),
            render_command=cmd,
        )
    except FileNotFoundError as exc:
        return _base_result(
            ok=False,
            status="error",
            error="manim_not_found",
            job_id=job_id,
            job_dir=job_dir,
            scene_py=scene_py,
            video_url=None,
            error_log=f"{type(exc).__name__}: {exc}",
            render_command=cmd,
        )
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        (logs_dir / "runner_exception.txt").write_text(detail + "\n", encoding="utf-8")
        return _base_result(
            ok=False,
            status="error",
            error="runner_exception",
            job_id=job_id,
            job_dir=job_dir,
            scene_py=scene_py,
            video_url=None,
            error_log=detail,
            logs={
                "stdout_url": "",
                "stderr_url": to_static_url(logs_dir / "runner_exception.txt"),
                "cmd_url": "",
            },
            render_command=cmd,
        )
    finally:
        active = ACTIVE_PROCS.get(job_id)
        if active is not None and active.poll() is not None:
            ACTIVE_PROCS.pop(job_id, None)



def cleanup_structured_job_artifacts(
    parent_job_id: str,
    *,
    keep_diagnostics: bool,
) -> dict[str, int]:
    """Remove structured-video render intermediates without deleting final user artifacts.

    Child scene jobs are always transient after concatenation or a terminal failure. Parent logs
    and metadata are retained only for abnormal runs selected by the orchestrator.
    """
    jobs_root = (STORAGE / "jobs").resolve()
    parent_name = str(parent_job_id or "").strip()
    if not parent_name:
        return {"child_jobs_removed": 0, "parent_items_removed": 0}

    child_jobs_removed = 0
    try:
        for candidate in list(jobs_root.iterdir()):
            if not candidate.is_dir():
                continue
            if candidate.name.startswith(f"{parent_name}-scene-"):
                shutil.rmtree(candidate, ignore_errors=True)
                child_jobs_removed += 1
    except Exception:
        pass

    parent_dir = (jobs_root / parent_name).resolve()
    if jobs_root not in parent_dir.parents:
        return {
            "child_jobs_removed": child_jobs_removed,
            "parent_items_removed": 0,
        }
    parent_items_removed = 0
    if not parent_dir.exists():
        return {
            "child_jobs_removed": child_jobs_removed,
            "parent_items_removed": parent_items_removed,
        }

    # These directories contain Manim/ffmpeg intermediates and should never be retained.
    transient_dirs = (
        "out",
        "media",
        "partial_movie_files",
        "Tex",
        "texts",
        "images",
        "sounds",
    )
    for name in transient_dirs:
        target = parent_dir / name
        try:
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
                parent_items_removed += 1
        except Exception:
            pass

    # Watermarking uses this temporary sibling when interrupted before replacement.
    for pattern in ("video_watermarked.mp4", "*.tmp", "*.temp"):
        for target in parent_dir.glob(pattern):
            try:
                if target.is_file():
                    target.unlink()
                    parent_items_removed += 1
            except Exception:
                pass

    if not keep_diagnostics:
        for name in (
            "logs",
            "structured_plan.json",
            "structured_scene_results.json",
            "generation_diagnostics.json",
            ".diagnostic_retention.json",
        ):
            target = parent_dir / name
            try:
                if target.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
                    parent_items_removed += 1
                elif target.exists():
                    target.unlink()
                    parent_items_removed += 1
            except Exception:
                pass

    return {
        "child_jobs_removed": child_jobs_removed,
        "parent_items_removed": parent_items_removed,
    }

def cancel_job(job_id: str) -> dict[str, str]:
    """Cancel an exact render or any structured-video child render."""
    actual_job_id = job_id
    proc = ACTIVE_PROCS.get(job_id)
    if proc is None:
        prefixes = (f"{job_id}_", f"{job_id}-")
        for active_id, active_proc in list(ACTIVE_PROCS.items()):
            if active_id.startswith(prefixes):
                actual_job_id = active_id
                proc = active_proc
                break

    job_dir = STORAGE / "jobs" / job_id
    logs_dir = job_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    if proc is None:
        (logs_dir / "cancel.txt").write_text("no active process", encoding="utf-8")
        return {"status": "not_found", "job_id": job_id}
    if proc.poll() is not None:
        ACTIVE_PROCS.pop(actual_job_id, None)
        (logs_dir / "cancel.txt").write_text(
            f"already exited: {actual_job_id}", encoding="utf-8"
        )
        return {"status": "already_finished", "job_id": job_id, "actual_job_id": actual_job_id}

    try:
        _kill_proc_tree(proc)
    finally:
        ACTIVE_PROCS.pop(actual_job_id, None)
        (logs_dir / "cancel.txt").write_text(f"canceled: {actual_job_id}", encoding="utf-8")
    return {"status": "canceled", "job_id": job_id, "actual_job_id": actual_job_id}
