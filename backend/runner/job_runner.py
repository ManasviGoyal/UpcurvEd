# backend/runner/job_runner.py
"""
Shared job runner for Manim (fixed low quality):
- writes scene.py
- lints with pyflakes (best-effort)
- renders with: manim -ql
- stores logs/mp4 under storage/jobs/<job_id>/
- ALWAYS returns a uniform dict (never raises)
"""

import os
import re
import shutil
import signal
import subprocess
import sys
import uuid
from pathlib import Path

# Root for artifacts; FastAPI should mount this at /static
STORAGE = Path("storage")
# Ensure storage/jobs exists early; prefer os.makedirs for robustness.
try:
    os.makedirs(str(STORAGE / "jobs"), exist_ok=True)
except Exception:
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="ac215_storage_"))
    STORAGE = tmp
    os.makedirs(str(STORAGE / "jobs"), exist_ok=True)

# Track active processes by job_id for cancellation
ACTIVE_PROCS: dict[str, subprocess.Popen] = {}

# Log size cap to avoid huge payloads in memory/prompts
MAX_LOG_BYTES = int(os.getenv("MAX_LOG_BYTES", "200000"))  # ~200 KB default


def to_static_url(p: Path) -> str:
    """Map a filesystem path under storage/ to a /static/... URL."""
    return f"/static/{p.relative_to(STORAGE)}"


def _truncate(s: str | None, limit: int = MAX_LOG_BYTES) -> str:
    if not s:
        return ""
    return s if len(s) <= limit else s[:limit]


def _kill_proc_tree(proc: subprocess.Popen) -> None:
    """Best-effort kill of a started Popen (entire group)."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        pass


def _inject_watermark(code: str) -> str:
    """
    Inject watermark code into Manim scene code.
    Adds a Text watermark at the top-right corner that persists throughout the scene.
    The watermark is added after each cleanup section to ensure it persists.
    """
    # Watermark initialization code (only run once, stored as instance vars)
    watermark_init = """        # Initialize watermark (only once) - stored as instance variables
        if not hasattr(self, '_watermark_added'):
            self._watermark_text = Text("Generated using UpcurvEd", font_size=24, color="white")
            self._watermark_text.set_opacity(0.8)  # Make text translucent
            self._watermark_text.to_corner(UR, buff=0.1)
            # Add semi-transparent background box
            self._watermark_bg = Rectangle(
                width=self._watermark_text.width + 0.3,
                height=self._watermark_text.height + 0.2,
                fill_opacity=0.6,  # More translucent background
                fill_color="black",
                stroke_width=0
            )
            self._watermark_bg.move_to(self._watermark_text.get_center())
            self.add(self._watermark_bg, self._watermark_text)
            self._watermark_added = True

"""

    # Watermark re-add code (after cleanup) - re-adds stored watermark objects
    watermark_readd = """        # Re-add watermark after cleanup (excluded from snapshot)
        if hasattr(self, '_watermark_added') and self._watermark_added:
            if self._watermark_bg not in self.mobjects:
                self.add(self._watermark_bg)
            if self._watermark_text not in self.mobjects:
                self.add(self._watermark_text)

"""

    # Modify cleanup code to exclude watermark from snapshot
    cleanup_modify = """        # Modify cleanup to exclude watermark
        snapshot = [m for m in self.mobjects if not (
            hasattr(self, '_watermark_bg') and m in [self._watermark_bg, self._watermark_text]
        )]
"""

    # First, add watermark initialization at the start of construct()
    pattern_start = r"(def\s+construct\s*\([^)]*\)\s*:\s*\n)"
    modified_code = re.sub(
        pattern_start, lambda m: m.group(1) + watermark_init, code, count=1, flags=re.MULTILINE
    )

    # If that didn't work, try fallback
    if modified_code == code:
        pattern_fallback = r"(def\s+construct\s*\([^)]*\)\s*:)"
        modified_code = re.sub(
            pattern_fallback, r"\1\n" + watermark_init, code, count=1, flags=re.MULTILINE
        )

    # Modify cleanup code to exclude watermark from being faded out
    # Replace: snapshot = list(self.mobjects) with modified version
    snapshot_pattern = r"(snapshot\s*=\s*list\(self\.mobjects\))"
    modified_code = re.sub(
        snapshot_pattern, cleanup_modify.strip(), modified_code, flags=re.MULTILINE
    )

    # Also re-add watermark after cleanup waits as a safeguard
    cleanup_wait_pattern = r"(self\.wait\(0\.1\))"
    modified_code = re.sub(
        cleanup_wait_pattern, r"\1\n" + watermark_readd, modified_code, flags=re.MULTILINE
    )

    # Also add at the very end of construct() as a final safeguard
    # Find the end of construct() - look for the last indented line before next def/class
    # This is tricky, so let's add it before any final return or at the end
    # Actually, let's just ensure it's added after the last self.wait() or similar

    return modified_code


def run_job_from_code(
    code: str,
    scene_name: str = "GeneratedScene",
    timeout_seconds: int = 600,
    job_id: str | None = None,
):
    """
    Execute a full render job from provided Manim code.
    Always uses low quality (-ql).

    Returns (uniform shape; NEVER raises):
    {
      "ok": bool,
      "status": "ok" | "error",
      "error": str | None,           # short error code on failure
      "job_id": str,
      "job_dir": str,                # filesystem path to the job directory
      "video_url": str | None,
      "compile_log": str,            # stdout text (possibly truncated)
      "error_log": str,              # stderr text (possibly truncated)
      "logs": {                      # URLs for deeper inspection
        "stdout_url": str,
        "stderr_url": str,
        "cmd_url": str
      },
      # on failure, may also include:
      # "listing_url": str,
      # "returncode_url": str,
      # "lint_url": str,
      # "lint_timeout_url": str,
      # "timeout_url": str,
    }
    """
    job_id = job_id or str(uuid.uuid4())[:8]
    job_dir = STORAGE / "jobs" / job_id
    out_dir = job_dir / "out"
    logs_dir = job_dir / "logs"
    job_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    # --- Inject watermark into code ---
    code = _inject_watermark(code)

    # --- Write scene.py ---
    scene_py = job_dir / "scene.py"
    scene_py.write_text(code)

    runner_env = os.environ.copy()
    ffmpeg_path = runner_env.get("UPCURVED_FFMPEG_PATH", "").strip()
    if ffmpeg_path:
        ffmpeg_dir = str(Path(ffmpeg_path).parent)
        runner_env["PATH"] = f"{ffmpeg_dir}{os.pathsep}{runner_env.get('PATH', '')}"
        runner_env["FFMPEG_BINARY"] = ffmpeg_path
        runner_env["IMAGEIO_FFMPEG_EXE"] = ffmpeg_path

    # --- Lint (advisory only) ---
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
        (logs_dir / "lint.txt").write_text(lint_text)

        LINT_STRICT = os.getenv("LINT_STRICT", "0") == "1"
        if lint_proc.returncode != 0 and LINT_STRICT:
            return {
                "ok": False,
                "status": "error",
                "error": "lint_failed",
                "job_id": job_id,
                "job_dir": str(job_dir),
                "video_url": None,
                "compile_log": _truncate(lint_text),
                "error_log": "",
                "logs": {
                    "stdout_url": to_static_url(logs_dir / "lint.txt"),
                    "stderr_url": "",
                    "cmd_url": "",
                },
                "lint_url": to_static_url(logs_dir / "lint.txt"),
            }
    except FileNotFoundError:
        # pyflakes not installed → skip linting
        pass
    except subprocess.TimeoutExpired as e:
        (logs_dir / "lint_timeout.txt").write_text(str(e))
        if os.getenv("LINT_STRICT", "0") == "1":
            return {
                "ok": False,
                "status": "error",
                "error": "lint_timeout",
                "job_id": job_id,
                "job_dir": str(job_dir),
                "video_url": None,
                "compile_log": "",
                "error_log": _truncate(str(e)),
                "logs": {
                    "stdout_url": "",
                    "stderr_url": to_static_url(logs_dir / "lint_timeout.txt"),
                    "cmd_url": "",
                },
                "lint_timeout_url": to_static_url(logs_dir / "lint_timeout.txt"),
            }

    # --- Render with Manim (fixed low quality) ---
    stdout = ""
    stderr = ""
    proc: subprocess.Popen | None = None
    try:
        cmd = [
            sys.executable,
            "-m",
            "manim",
            "-v",
            "WARNING",
            "-ql",  # fixed low quality
            str(scene_py),
            scene_name,
            "-o",
            "video.mp4",
            "--media_dir",
            str(out_dir),
        ]
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
        except subprocess.TimeoutExpired as e:
            # Kill and capture what we can
            _kill_proc_tree(proc)
            try:
                stdout, stderr = proc.communicate(timeout=2)
            except Exception:
                pass
            (logs_dir / "timeout.txt").write_text(str(e))
            # Persist artifacts
            (logs_dir / "manim_cmd.txt").write_text(" ".join(cmd))
            (logs_dir / "manim_stdout.txt").write_text(stdout or "")
            (logs_dir / "manim_stderr.txt").write_text(stderr or "")
            (logs_dir / "returncode.txt").write_text("timeout")

            return {
                "ok": False,
                "status": "error",
                "error": "render_timeout",
                "job_id": job_id,
                "job_dir": str(job_dir),
                "video_url": None,
                "compile_log": _truncate(stdout),
                "error_log": _truncate(stderr or str(e)),
                "logs": {
                    "stdout_url": to_static_url(logs_dir / "manim_stdout.txt"),
                    "stderr_url": to_static_url(logs_dir / "manim_stderr.txt"),
                    "cmd_url": to_static_url(logs_dir / "manim_cmd.txt"),
                },
                "timeout_url": to_static_url(logs_dir / "timeout.txt"),
            }

        # Always write command and any available outputs
        (logs_dir / "manim_cmd.txt").write_text(" ".join(cmd))
        (logs_dir / "manim_stdout.txt").write_text(stdout or "")
        (logs_dir / "manim_stderr.txt").write_text(stderr or "")
        (logs_dir / "returncode.txt").write_text(str(proc.returncode))

        # Manim nests outputs under out_dir
        mp4s = sorted(out_dir.rglob("*.mp4"))
        if proc.returncode != 0 or not mp4s:
            (logs_dir / "out_dir_listing.txt").write_text(
                "\n".join(str(p) for p in out_dir.rglob("*"))
            )
            return {
                "ok": False,
                "status": "error",
                "error": "render_failed",
                "job_id": job_id,
                "job_dir": str(job_dir),
                "video_url": None,
                "compile_log": _truncate(stdout),
                "error_log": _truncate(stderr),
                "logs": {
                    "stdout_url": to_static_url(logs_dir / "manim_stdout.txt"),
                    "stderr_url": to_static_url(logs_dir / "manim_stderr.txt"),
                    "cmd_url": to_static_url(logs_dir / "manim_cmd.txt"),
                },
                "listing_url": to_static_url(logs_dir / "out_dir_listing.txt"),
                "returncode_url": to_static_url(logs_dir / "returncode.txt"),
            }

        # Success: copy newest MP4 to stable path and return
        newest = max(mp4s, key=lambda p: p.stat().st_mtime)
        final_video = job_dir / "video.mp4"
        shutil.copyfile(newest, final_video)

        # Convert SRT to VTT if available (do it during generation, not after)
        # Use same converter as podcast code for consistency
        srt_file = newest.with_suffix(".srt")
        if srt_file.exists():
            try:
                import re

                srt_text = srt_file.read_text(encoding="utf-8", errors="ignore")

                # Convert SRT to WebVTT (same as podcast_logic._srt_to_vtt)
                # Replace comma milliseconds with dot: 00:00:01,000 --> 00:00:01.000
                vtt_body = re.sub(
                    r"^(\d{2}:\d{2}:\d{2}),(\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}),(\d{3})",
                    r"\1.\2 --> \3.\4",
                    srt_text,
                    flags=re.MULTILINE,
                )
                # Remove SRT cue indices (standalone lines with only digits)
                vtt_lines = []
                for line in vtt_body.splitlines():
                    if re.match(r"^\s*\d+\s*$", line):
                        continue
                    vtt_lines.append(line)
                vtt_text = "WEBVTT\n\n" + "\n".join(vtt_lines).strip() + "\n"

                final_vtt = job_dir / "video.vtt"
                final_vtt.write_text(vtt_text, encoding="utf-8")
            except Exception as e:
                # Log but don't fail the whole job if VTT conversion fails
                print(f"Warning: VTT conversion failed: {e}", file=sys.stderr)

        return {
            "ok": True,
            "status": "ok",
            "error": None,
            "job_id": job_id,
            "job_dir": str(job_dir),
            "video_url": to_static_url(final_video),
            "compile_log": _truncate(stdout),
            "error_log": "",
            "logs": {
                "stdout_url": to_static_url(logs_dir / "manim_stdout.txt"),
                "stderr_url": to_static_url(logs_dir / "manim_stderr.txt"),
                "cmd_url": to_static_url(logs_dir / "manim_cmd.txt"),
            },
        }

    except FileNotFoundError:
        # python/manim runtime not available
        return {
            "ok": False,
            "status": "error",
            "error": "manim_not_found",
            "job_id": job_id,
            "job_dir": str(job_dir),
            "video_url": None,
            "compile_log": "",
            "error_log": "manim runtime not found (FileNotFoundError)",
            "logs": {"stdout_url": "", "stderr_url": "", "cmd_url": ""},
        }
    finally:
        # Cleanup registry if process finished
        proc_ref = ACTIVE_PROCS.get(job_id)
        if proc_ref is not None and proc_ref.poll() is not None:
            ACTIVE_PROCS.pop(job_id, None)


def cancel_job(job_id: str):
    """Attempt to terminate a running job by job_id. Never raises; returns a dict."""
    proc = ACTIVE_PROCS.get(job_id)
    job_dir = STORAGE / "jobs" / job_id
    logs_dir = job_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    if proc is None:
        (logs_dir / "cancel.txt").write_text("no active process")
        return {"status": "not_found", "job_id": job_id}

    if proc.poll() is not None:
        ACTIVE_PROCS.pop(job_id, None)
        (logs_dir / "cancel.txt").write_text("already exited")
        return {"status": "already_finished", "job_id": job_id}

    try:
        _kill_proc_tree(proc)
    finally:
        ACTIVE_PROCS.pop(job_id, None)
        (logs_dir / "cancel.txt").write_text("canceled")
    return {"status": "canceled", "job_id": job_id}
