# backend/api/main.py
import logging
import mimetypes
import os
import pathlib
import re
from difflib import SequenceMatcher
from typing import Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from firebase_admin import auth as fb_auth
from google.cloud import firestore as gcf
from pydantic import BaseModel, Field

from backend.agent.code_sanitize import sanitize_minimally
from backend.agent.graph import run_to_code
from backend.agent.llm.clients import call_llm
from backend.agent.minigraph import echo_manim_code
from backend.agent.prompts import EDIT_SYSTEM, build_edit_user_prompt
from backend.firebase_app import get_db, init_firebase
from backend.gcs_utils import delete_folder, get_bucket_name, sign_url, upload_bytes
from backend.mcp.podcast_logic import generate_podcast
from backend.mcp.quiz_logic import generate_quiz_embedded
from backend.runner.job_runner import STORAGE, cancel_job, run_job_from_code, to_static_url

# Import to trigger app-level logging configuration (handlers, format, level).
from backend.utils import app_logging  # noqa: F401

logger = logging.getLogger(f"app.{__name__}")
APP_MODE = os.environ.get("APP_MODE", "cloud").strip().lower()
DESKTOP_LOCAL_MODE = APP_MODE == "desktop-local"


# ===== Firebase auth dependency =====
def require_firebase_user(
    authorization: str | None = Header(None),
    x_desktop_user: str | None = Header(None, alias="X-Desktop-User"),
) -> str:
    """Verify Firebase ID token from Authorization: Bearer <token> header.

    Returns uid if valid. Raises 401 on failure.
    """
    if DESKTOP_LOCAL_MODE:
        if x_desktop_user and x_desktop_user.strip():
            safe = re.sub(r"[^a-zA-Z0-9._-]", "_", x_desktop_user.strip())[:128]
            return safe or "desktop-local-user"
        return "desktop-local-user"

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        # Ensure Firebase Admin app is initialized before verifying tokens
        init_firebase()
        decoded = fb_auth.verify_id_token(token)
        uid = decoded.get("uid")
        if not uid:
            raise ValueError("uid missing")
        return uid
    except Exception as e:
        logger.warning("Auth failed: %s", e)
        raise HTTPException(status_code=401, detail="Invalid token") from e


# ===== CORS Configuration =====
# Default origins for local development
_GCP_PROJECT = os.environ.get("GCP_PROJECT", "").strip()
_DEFAULT_ORIGINS = [
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "http://[::1]:8080",
    "http://localhost:8085",
    "http://127.0.0.1:8085",
    "http://[::1]:8085",
]
if _GCP_PROJECT:
    # Firebase hosting domains (dynamic)
    _DEFAULT_ORIGINS.extend(
        [
            f"https://{_GCP_PROJECT}.firebaseapp.com",
            f"https://{_GCP_PROJECT}.web.app",
        ]
    )

# Additional origins from environment (comma-separated)
# Example: CORS_ORIGINS=https://my-app.com,https://staging.my-app.com
_extra_origins = os.environ.get("CORS_ORIGINS", "")
_all_origins = _DEFAULT_ORIGINS + [o.strip() for o in _extra_origins.split(",") if o.strip()]

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_all_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Only mount /static/ in dev mode (when GCS bucket is not configured)
# In production, use GCS signed URLs only
if not get_bucket_name():
    app.mount("/static", StaticFiles(directory=str(STORAGE)), name="static")


class GenerateIn(BaseModel):
    prompt: str
    keys: dict[str, str] = {}  # {"claude": "...", "gemini": "..."}
    provider: Literal["claude", "gemini"] | None = None
    model: str | None = None
    jobId: str | None = None
    chatId: str | None = None
    sessionId: str | None = None


class QuizIn(BaseModel):
    prompt: str
    num_questions: int = 5
    difficulty: Literal["easy", "medium", "hard"] | None = "medium"
    # optional provider/model and keys similar to /generate
    keys: dict[str, str] = {}
    provider: Literal["claude", "gemini"] | None = None
    model: str | None = None
    # optional extra context (e.g., script/SRT)
    context: str | None = None
    userEmail: str | None = None


class PodcastIn(BaseModel):
    prompt: str
    # optional provider/model and keys similar to /generate
    keys: dict[str, str] = {}
    provider: Literal["claude", "gemini"] | None = None
    model: str | None = None
    jobId: str | None = None
    chatId: str | None = None
    sessionId: str | None = None


class EditVideoIn(BaseModel):
    """Request model for video editing - modifies existing scene code based on instructions."""

    original_code: str  # The original scene.py code
    edit_instructions: str  # What changes the user wants
    keys: dict[str, str] = {}
    provider: Literal["claude", "gemini"] | None = None
    model: str | None = None
    jobId: str | None = None
    chatId: str | None = None
    sessionId: str | None = None


# ===== Chat API models =====
class ChatCreateIn(BaseModel):
    title: str | None = Field(default="New Chat")
    model: str | None = None
    sessionId: str | None = None
    # sharing flags at creation (normally defaults to False)
    shareable: bool = False
    share_token: str | None = None  # ignored unless shareable True
    # Optional first message content and timestamp
    content: str | None = None
    timestamp: str | None = None


class ChatItemOut(BaseModel):
    chat_id: str
    title: str
    dts: int | None = None  # milliseconds since epoch (updatedAt)
    sessionId: str | None = None
    shareable: bool = False
    share_token: str | None = None


class MessageMedia(BaseModel):
    type: str | None = None  # e.g. "video" | "audio" | "podcast"
    url: str | None = None
    subtitleUrl: str | None = None
    artifactId: str | None = None
    title: str | None = None
    gcsPath: str | None = None  # persist path to allow refresh of signed URL
    sceneCode: str | None = None  # scene.py code for video editing


class MessageCreateIn(BaseModel):
    # client-generated id for idempotent writes; if omitted, server will create
    message_id: str | None = None
    role: Literal["user", "assistant"]
    content: str
    media: MessageMedia | None = None
    # Quiz data for embedded quizzes
    quizAnchor: bool | None = None
    quizTitle: str | None = None
    quizData: dict | None = None


class MessageOut(BaseModel):
    message_id: str
    role: Literal["user", "assistant"]
    content: str
    createdAt: int | None = None  # ms epoch
    media: MessageMedia | None = None
    # Quiz data for embedded quizzes
    quizAnchor: bool | None = None
    quizTitle: str | None = None
    quizData: dict | None = None


class MessagesPage(BaseModel):
    messages: list[MessageOut]
    has_more: bool


class ChatDetailOut(BaseModel):
    chat_id: str
    title: str
    dts: int | None = None
    sessionId: str | None = None
    messages: list[MessageOut] = []
    shareable: bool = False
    share_token: str | None = None
    model: str | None = None  # model used for this chat


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/echo")
def echo(body: GenerateIn):
    logger.info("/echo called")
    code = echo_manim_code(body.prompt)
    res = run_job_from_code(code)
    logger.info("/echo completed: %s", res.get("status"))
    return res


def _save_artifact(
    uid: str,
    chat_id: str | None,
    type_: str,
    gcs_path: str,
    size_bytes: int,
    fmt: str,
    derived: bool = False,
):
    try:
        db = get_db()
        doc = db.collection("users").document(uid).collection("artifacts").document()
        doc.set(
            {
                "chatId": chat_id or None,
                "type": type_,
                "gcsPath": gcs_path,
                "sizeBytes": size_bytes,
                "format": fmt,
                "derived": derived,
                "createdAt": gcf.SERVER_TIMESTAMP,
            }
        )
        return doc.id
    except Exception as e:
        logger.warning("save artifact failed: %s", e)
        return None


def _srt_to_vtt_text(srt_text: str) -> str:
    """Convert SRT text to WebVTT text (simple formatting)."""
    # Basic approach: ensure WEBVTT header and replace comma decimal separator
    # More robust conversion could use the 'srt' Python package to parse and reformat.
    try:
        import srt as srtlib  # type: ignore

        subs = list(srtlib.parse(srt_text))
        lines = ["WEBVTT", ""]
        for cue in subs:
            start = str(cue.start).replace(",", ".")
            end = str(cue.end).replace(",", ".")
            # srtlib renders like '0:00:12.345000'; WebVTT accepts it
            text = cue.content.replace("\r\n", "\n")
            lines.append(f"{start} --> {end}")
            lines.extend(text.split("\n"))
            lines.append("")
        return "\n".join(lines) + "\n"
    except Exception:
        # Fallback naive conversion: add header and replace comma with dot in timestamps

        body = []
        for line in srt_text.splitlines():
            body.append(re.sub(r"(\d\d:\d\d:\d\d),(\d\d\d)", r"\1.\2", line))
        return "WEBVTT\n\n" + "\n".join(body) + "\n"


@app.post("/generate")
def generate(body: GenerateIn, uid: str = Depends(require_firebase_user)):
    # Defaults for provider/model to avoid None crashes
    provider = body.provider
    model = body.model
    if not provider:
        if body.keys.get("gemini"):
            provider = "gemini"
        elif body.keys.get("claude"):
            provider = "claude"
    if not model and provider == "gemini":
        model = "gemini-2.5-pro"
    if not model and provider == "claude":
        model = "claude-sonnet-4-6"
    logger.info("/generate called provider=%s model=%s", provider, model)

    # returns: code, video_url, render_ok, tries, attempt_job_ids, succeeded_job_id
    code, video_url, render_ok, tries, attempt_job_ids, succeeded_job_id = run_to_code(
        prompt=body.prompt,
        provider_keys=body.keys,
        provider=provider,
        model=model,
    )

    if render_ok and video_url:
        # Attempt GCS copy if bucket configured
        gcs_bucket = get_bucket_name()
        signed_video_url = None
        signed_subtitle_url = None
        saved_artifact_id = None
        gcs_path = None
        # Calculate local file path (needed for both GCS and local subtitle handling)

        relative_path = video_url.replace("/static/", "")
        p = pathlib.Path(STORAGE) / relative_path
        # Use job_id for unique filenames to prevent overwrites
        job_id = succeeded_job_id or body.jobId or "unknown"
        if gcs_bucket:
            try:
                # Read file bytes from storage path (video_url is already served from /static)
                # video_url format: /static/jobs/abc123/out/video.mp4
                # We need the full relative path: jobs/abc123/out/video.mp4
                if p.exists():
                    data = p.read_bytes()
                    content_type = mimetypes.guess_type(p.name)[0] or "video/mp4"
                    gcs_path = f"{uid}/chats/{body.chatId or 'uncategorized'}/video_{job_id}.mp4"
                    upload_bytes(gcs_bucket, gcs_path, data, content_type)
                    signed_video_url = sign_url(gcs_bucket, gcs_path)
                    saved_artifact_id = _save_artifact(
                        uid, body.chatId, "video", gcs_path, len(data), content_type, derived=False
                    )
                    # Try subtitle next to video (VTT already converted by job_runner)
                    vtt_local = p.with_suffix(".vtt")
                    if vtt_local.exists():
                        try:
                            vtt_bytes = vtt_local.read_bytes()
                            chat_path = body.chatId or "uncategorized"
                            vtt_path = f"{uid}/chats/{chat_path}/video_{job_id}.vtt"
                            upload_bytes(gcs_bucket, vtt_path, vtt_bytes, "text/vtt")
                            signed_subtitle_url = sign_url(gcs_bucket, vtt_path)
                            _save_artifact(
                                uid,
                                body.chatId,
                                "subtitle",
                                vtt_path,
                                len(vtt_bytes),
                                "text/vtt",
                                derived=True,
                            )
                        except Exception as e:
                            logger.warning("VTT upload failed: %s", e)
                    # Save scene code if available
                    if code:
                        py_bytes = code.encode("utf-8")
                        py_path = f"{uid}/chats/{body.chatId or 'uncategorized'}/scene_{job_id}.py"
                        upload_bytes(gcs_bucket, py_path, py_bytes, "text/x-python")
                        _save_artifact(
                            uid,
                            body.chatId,
                            "script",
                            py_path,
                            len(py_bytes),
                            "text/x-python",
                            derived=True,
                        )
            except Exception as e:
                logger.warning("GCS upload failed: %s", e)

            # Clean up local files after successful GCS upload
            if signed_video_url and gcs_bucket:
                try:
                    # Clean up video file
                    if p.exists():
                        p.unlink()
                        logger.info("Cleaned up local video file: %s", p)
                    # Clean up VTT file if uploaded
                    if signed_subtitle_url:
                        vtt_local = p.with_suffix(".vtt")
                        if vtt_local.exists():
                            vtt_local.unlink()
                            logger.info("Cleaned up local VTT file: %s", vtt_local)
                    # Clean up scene.py if uploaded (it's in the job directory)
                    if code:
                        job_dir = p.parent.parent
                        py_local = job_dir / "scene.py"
                        if py_local.exists():
                            py_local.unlink()
                            logger.info("Cleaned up local scene.py file: %s", py_local)
                    # Clean up job directory if empty (after all files removed)
                    try:
                        job_dir = p.parent.parent
                        # Check if directory is empty (only check for files, not subdirs)
                        remaining_files = [f for f in job_dir.iterdir() if f.is_file()]
                        if job_dir.exists() and len(remaining_files) == 0:
                            # Try to remove logs and out subdirectories if empty
                            for subdir in ["logs", "out"]:
                                subdir_path = job_dir / subdir
                                if subdir_path.exists():
                                    try:
                                        subdir_path.rmdir()
                                    except Exception:
                                        pass  # Not empty, ignore
                            # Try to remove job directory
                            try:
                                job_dir.rmdir()
                                logger.info("Cleaned up empty job directory: %s", job_dir)
                            except Exception:
                                pass  # Directory not empty or other error, ignore
                    except Exception:
                        pass  # Directory not empty or other error, ignore
                except Exception as e:
                    logger.warning("Failed to clean up local files: %s", e)

        # If GCS configured, ONLY return GCS URLs (no fallback)
        # If GCS not configured, return local URLs
        if gcs_bucket:
            if not signed_video_url:
                # GCS configured but upload failed - return error
                logger.error("GCS bucket configured but upload failed")
                return {
                    "ok": False,
                    "status": "error",
                    "error": "gcs_upload_failed",
                    "message": "Video generated but GCS upload failed.",
                    "video_url": None,
                }
            final_video_url = signed_video_url
        else:
            # No GCS configured, use local URLs
            final_video_url = video_url
            # Provide local VTT if exists and GCS not configured
            if not signed_subtitle_url and p.exists():
                vtt_local = p.with_suffix(".vtt")
                if vtt_local.exists():
                    signed_subtitle_url = to_static_url(vtt_local)
                    logger.info("Providing local subtitle URL: %s", signed_subtitle_url)

        res = {
            "ok": True,
            "status": "ok",
            "video_url": final_video_url,
            "signed_video_url": signed_video_url,
            "signed_subtitle_url": signed_subtitle_url,
            "artifact_id": saved_artifact_id,
            "gcs_path": gcs_path if gcs_bucket and signed_video_url else None,
            "scene_code": code,  # Return scene code for video editing feature
            "message": "Video generated.",  # optional but consistent
        }
        logger.info("/generate completed: ok (job_id=%s, tries=%s)", succeeded_job_id, tries)
        return res

    # ===== failure path =====
    logger.warning("/generate failed: tries=%s attempts=%s", tries, attempt_job_ids)

    res = {
        "ok": False,
        "status": "error",
        "error": "render_failed",
        "message": "Video generation failed.",
        "video_url": None,
    }
    logger.info("/generate completed: error")
    return res


def _apply_unified_diff(
    original: str, diff_text: str, apply_all_matches: bool = False
) -> str | None:
    """Apply a unified diff to original code. Returns modified code or None if failed.

    This uses fuzzy matching to find the correct location even if line numbers are off.
    If apply_all_matches is True, each hunk is applied to ALL matching locations in the file.
    """

    try:
        lines = original.split("\n")
        result_lines = lines.copy()

        # Parse diff hunks
        hunk_pattern = r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@"
        hunks = re.split(hunk_pattern, diff_text)

        if len(hunks) < 4:
            logger.warning("No valid hunks found in diff")
            return None

        # Track applied changes to avoid duplicate applications
        applied_ranges = []

        # Process hunks (skip first element which is before first @@)
        i = 1
        while i < len(hunks) - 2:
            old_start = int(hunks[i]) - 1  # Convert to 0-indexed
            int(hunks[i + 1]) - 1
            hunk_content = hunks[i + 2]
            i += 3

            # Parse the hunk content
            hunk_lines = hunk_content.strip().split("\n")

            # Collect removed (-) and added (+) lines with context
            context_lines = []
            remove_lines = []
            add_lines = []

            for line in hunk_lines:
                if not line:
                    continue
                if line.startswith("-"):
                    remove_lines.append(line[1:])  # Remove the '-' prefix
                elif line.startswith("+"):
                    add_lines.append(line[1:])  # Remove the '+' prefix
                elif line.startswith(" "):
                    context_lines.append(line[1:])  # Context line
                else:
                    context_lines.append(line)  # Treat as context

            if not remove_lines and not add_lines:
                continue

            # Find matching locations using context
            search_pattern = remove_lines if remove_lines else context_lines[:1]
            if not search_pattern:
                continue

            search_text = "\n".join(search_pattern)

            # Find ALL matches above threshold (for apply_all_matches mode)
            # Use adaptive threshold based on search pattern length
            matches = []
            # Shorter patterns need higher threshold to avoid false positives
            base_threshold = 0.7 if apply_all_matches else 0.8
            if len(search_pattern) <= 2:
                base_threshold = max(base_threshold, 0.85)

            for idx in range(0, len(result_lines)):
                if idx + len(search_pattern) > len(result_lines):
                    continue

                # Skip if this range was already modified
                if any(start <= idx < end for start, end in applied_ranges):
                    continue

                candidate = "\n".join(result_lines[idx : idx + len(search_pattern)])
                score = SequenceMatcher(None, search_text.strip(), candidate.strip()).ratio()
                if score > base_threshold:
                    matches.append((idx, score))

            if not matches:
                # Try with lower threshold as fallback
                for idx in range(0, len(result_lines)):
                    if idx + len(search_pattern) > len(result_lines):
                        continue
                    if any(start <= idx < end for start, end in applied_ranges):
                        continue
                    candidate = "\n".join(result_lines[idx : idx + len(search_pattern)])
                    score = SequenceMatcher(None, search_text.strip(), candidate.strip()).ratio()
                    if score > 0.6:
                        matches.append((idx, score))

            if not matches:
                logger.warning("Could not find match for hunk starting at line %d", old_start)
                continue

            if apply_all_matches and len(matches) > 1:
                # Apply to ALL matching locations (in reverse order to preserve indices)
                logger.info("Applying hunk to %d matching locations", len(matches))
                matches.sort(key=lambda x: x[0], reverse=True)  # Process from bottom to top
                for match_idx, match_score in matches:
                    if remove_lines:
                        result_lines = (
                            result_lines[:match_idx]
                            + add_lines
                            + result_lines[match_idx + len(remove_lines) :]
                        )
                        applied_ranges.append((match_idx, match_idx + len(add_lines)))
                    else:
                        result_lines = (
                            result_lines[: match_idx + 1]
                            + add_lines
                            + result_lines[match_idx + 1 :]
                        )
                        applied_ranges.append((match_idx, match_idx + 1 + len(add_lines)))
                    logger.info("Applied hunk at line %d (score=%.2f)", match_idx, match_score)
            else:
                # Apply to best match only
                best_match_idx, best_match_score = max(matches, key=lambda x: x[1])
                if remove_lines:
                    result_lines = (
                        result_lines[:best_match_idx]
                        + add_lines
                        + result_lines[best_match_idx + len(remove_lines) :]
                    )
                    applied_ranges.append((best_match_idx, best_match_idx + len(add_lines)))
                else:
                    result_lines = (
                        result_lines[: best_match_idx + 1]
                        + add_lines
                        + result_lines[best_match_idx + 1 :]
                    )
                    applied_ranges.append((best_match_idx, best_match_idx + 1 + len(add_lines)))
                logger.info(
                    "Applied hunk at line %d (score=%.2f)", best_match_idx, best_match_score
                )

        return "\n".join(result_lines)

    except Exception as e:
        logger.warning("Failed to apply diff: %s", e)
        return None


@app.post("/edit")
def edit_video(body: EditVideoIn, uid: str = Depends(require_firebase_user)):
    """Edit an existing video by modifying its scene code based on user instructions.

    This endpoint takes the original scene.py code and edit instructions,
    uses the LLM to make targeted modifications, and re-renders the video.
    """

    logger.info("=" * 50)
    logger.info("/edit endpoint called")

    # Validate inputs
    if not body.original_code or not body.original_code.strip():
        logger.error("/edit failed: original_code is empty or missing")
        raise HTTPException(status_code=400, detail="original_code is required and cannot be empty")

    if not body.edit_instructions or not body.edit_instructions.strip():
        logger.error("/edit failed: edit_instructions is empty or missing")
        raise HTTPException(
            status_code=400, detail="edit_instructions is required and cannot be empty"
        )

    # Defaults for provider/model to avoid None crashes
    provider = body.provider
    model = body.model
    if not provider:
        if body.keys.get("gemini"):
            provider = "gemini"
        elif body.keys.get("claude"):
            provider = "claude"
    if not model and provider == "gemini":
        model = "gemini-2.5-pro"
    if not model and provider == "claude":
        model = "claude-sonnet-4-6"
    logger.info("/edit using provider=%s model=%s", provider, model)

    key = body.keys.get(provider) if provider else None
    if not key:
        logger.error("/edit failed: Missing API key for provider=%s", provider)
        raise HTTPException(status_code=400, detail=f"Missing API key for '{provider}'")

    # Detect if user wants to change ALL occurrences
    # (keywords like "all", "every", "throughout", etc.)
    instructions_lower = body.edit_instructions.lower()
    wants_all = any(
        kw in instructions_lower
        for kw in ["all ", "every ", "throughout", "everywhere", "each ", "whole "]
    )
    # Detect overlap-related instructions
    wants_overlap_fix = any(
        kw in instructions_lower
        for kw in [
            "overlap",
            "overlapping",
            "collision",
            "collide",
            "stack",
            "stacking",
            "on top",
            "cover",
            "obscure",
            "hidden",
            "behind",
            "cleanup",
            "clear",
            "fadeout",
            "fade out",
            "remove previous",
        ]
    )
    logger.info(
        "/edit: instructions=%r, wants_all=%s, wants_overlap_fix=%s",
        body.edit_instructions,
        wants_all,
        wants_overlap_fix,
    )

    # Build edit prompt - ask LLM for a unified diff
    edit_system = EDIT_SYSTEM
    edit_user = build_edit_user_prompt(
        original_code=body.original_code,
        edit_instructions=body.edit_instructions,
        wants_all=wants_all,
        wants_overlap_fix=wants_overlap_fix,
    )

    try:
        logger.info("/edit: Calling LLM for diff-based edit...")
        raw = call_llm(
            provider=provider,
            api_key=key,
            model=model,
            system=edit_system,
            user=edit_user,
            temperature=0.1,  # Very low temperature for precise, deterministic edits
        )
        logger.info("/edit: LLM response received, length=%d chars", len(raw) if raw else 0)
        logger.info("/edit: LLM diff response:\n%s", raw[:500] if raw else "EMPTY")

        # Try to extract and apply diff
        code = None
        diff_applied = False

        # Extract diff block if present
        diff_match = re.search(r"```diff\s*(.*?)```", raw, re.IGNORECASE | re.DOTALL)
        if diff_match:
            diff_text = diff_match.group(1).strip()
            hunk_count = diff_text.count("@@ ")
            logger.info(
                "/edit: Found diff block with %d hunks, wants_all=%s, attempting to apply...",
                hunk_count,
                wants_all,
            )
            logger.info("/edit: Full diff:\n%s", diff_text)
            code = _apply_unified_diff(body.original_code, diff_text, apply_all_matches=wants_all)
            if code and code != body.original_code:
                diff_applied = True
                logger.info("/edit: Diff applied successfully")

        # Fallback: check if LLM returned full code instead of diff
        if not diff_applied:
            logger.info("/edit: Diff not found or failed, checking for full code...")
            # Check for python code block
            code_match = re.search(r"```(?:python)?\s*(.*?)```", raw, re.IGNORECASE | re.DOTALL)
            if code_match:
                potential_code = code_match.group(1).strip()
                # Verify it looks like valid Python with our class
                if "class " in potential_code and "def construct" in potential_code:
                    code = potential_code
                    logger.info("/edit: Using full code from LLM response")

            # Last resort: use raw response if it looks like code
            if not code and "class " in raw and "def construct" in raw:
                code = raw.strip()
                logger.info("/edit: Using raw response as code")

        if not code:
            logger.error("/edit: Could not extract valid code from LLM response")
            raise HTTPException(status_code=500, detail="Failed to generate code edit")

        code = sanitize_minimally(code)

        similarity = SequenceMatcher(None, body.original_code, code).ratio()
        logger.info("/edit: Code similarity to original: %.1f%%", similarity * 100)

        if similarity < 0.5:
            logger.warning(
                "/edit: Code changed significantly (%.1f%% similar) "
                "- LLM may have rewritten instead of edited",
                similarity * 100,
            )

        logger.info("/edit: Starting Manim render...")
        render_result = run_job_from_code(code)
        # Note: run_job_from_code returns 'ok' not 'render_ok'
        render_ok = render_result.get("ok", False) or render_result.get("render_ok", False)
        video_url = render_result.get("video_url")
        job_id = render_result.get("job_id") or body.jobId or "unknown"
        logger.info(
            "/edit: Render result - ok=%s, video_url=%s, job_id=%s", render_ok, video_url, job_id
        )

        if not render_ok:
            error_detail = (
                render_result.get("error")
                or render_result.get("stderr")
                or render_result.get("error_log")
                or "Unknown render error"
            )
            logger.error("/edit: Render FAILED - %s", error_detail)
            logger.error("/edit: Full render_result: %s", render_result)

        if render_ok and video_url:
            # Upload to GCS if bucket configured
            gcs_bucket = get_bucket_name()
            signed_video_url = None
            signed_subtitle_url = None
            saved_artifact_id = None
            gcs_path = None

            relative_path = video_url.replace("/static/", "")
            p = pathlib.Path(STORAGE) / relative_path

            if gcs_bucket and p.exists():
                try:
                    data = p.read_bytes()
                    content_type = mimetypes.guess_type(p.name)[0] or "video/mp4"
                    gcs_path = f"{uid}/chats/{body.chatId or 'uncategorized'}/video_{job_id}.mp4"
                    upload_bytes(gcs_bucket, gcs_path, data, content_type)
                    signed_video_url = sign_url(gcs_bucket, gcs_path)
                    saved_artifact_id = _save_artifact(
                        uid, body.chatId, "video", gcs_path, len(data), content_type, derived=False
                    )
                    # Try subtitle
                    vtt_local = p.with_suffix(".vtt")
                    if vtt_local.exists():
                        vtt_bytes = vtt_local.read_bytes()
                        vtt_path = (
                            f"{uid}/chats/{body.chatId or 'uncategorized'}/video_{job_id}.vtt"
                        )
                        upload_bytes(gcs_bucket, vtt_path, vtt_bytes, "text/vtt")
                        signed_subtitle_url = sign_url(gcs_bucket, vtt_path)
                    # Save scene code
                    py_bytes = code.encode("utf-8")
                    py_path = f"{uid}/chats/{body.chatId or 'uncategorized'}/scene_{job_id}.py"
                    upload_bytes(gcs_bucket, py_path, py_bytes, "text/x-python")
                    # Clean up local files
                    try:
                        if p.exists():
                            p.unlink()
                        if vtt_local.exists():
                            vtt_local.unlink()
                    except Exception:
                        pass
                except Exception as e:
                    logger.warning("GCS upload failed for edit: %s", e)

            if gcs_bucket:
                if not signed_video_url:
                    return {
                        "ok": False,
                        "status": "error",
                        "error": "gcs_upload_failed",
                        "message": "Edited video generated but GCS upload failed.",
                    }
                final_video_url = signed_video_url
            else:
                final_video_url = video_url
                if p.exists():
                    vtt_local = p.with_suffix(".vtt")
                    if vtt_local.exists():
                        signed_subtitle_url = to_static_url(vtt_local)

            logger.info("/edit: Successfully edited video")
            return {
                "ok": True,
                "status": "ok",
                "video_url": final_video_url,
                "signed_video_url": signed_video_url,
                "signed_subtitle_url": signed_subtitle_url,
                "artifact_id": saved_artifact_id,
                "gcs_path": gcs_path,
                "scene_code": code,
                "message": "Video edited successfully.",
            }
        else:
            # Return detailed error for debugging
            error_detail = (
                render_result.get("error") or render_result.get("stderr") or "Unknown render error"
            )
            logger.error("/edit: Returning render_failed - %s", error_detail)
            return {
                "ok": False,
                "status": "error",
                "error": "render_failed",
                "message": f"Edited video failed to render: {error_detail[:500]}",
                "video_url": None,
                "render_result": render_result,  # Include full result for debugging
            }

    except Exception as e:
        logger.exception("/edit failed with exception: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/quiz/embedded")
def quiz_embedded(body: QuizIn):
    """Return raw quiz JSON for embedding directly in the chat UI (no Google Form)."""
    try:
        provider = body.provider
        model = body.model
        if not provider:
            if body.keys.get("gemini"):
                provider = "gemini"
            elif body.keys.get("claude"):
                provider = "claude"
        if not model and provider == "gemini":
            model = "gemini-2.5-pro"
        if not model and provider == "claude":
            model = "claude-sonnet-4-6"
        logger.info("/quiz/embedded called provider=%s model=%s", provider, model)
        quiz = generate_quiz_embedded(
            prompt=body.prompt,
            num_questions=body.num_questions,
            difficulty=body.difficulty or "medium",
            provider=provider,
            model=model,
            provider_keys=body.keys,
            context=body.context,
        )
        return {"status": "ok", "quiz": quiz}
    except Exception as e:
        logger.exception("/quiz/embedded failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/quiz/media")
def quiz_media(body: dict, uid: str = Depends(require_firebase_user)):
    """Generate quiz from media captions (VTT) for both video and podcast."""
    logger.info("/quiz/media endpoint called by user=%s", uid)
    try:
        transcript = body.get("transcript", "").strip()
        logger.info("/quiz/media transcript length=%d", len(transcript) if transcript else 0)
        if not transcript:
            logger.error("/quiz/media failed: transcript is empty or missing")
            raise ValueError("Transcript from VTT captions is required")

        # Reuse provider/model defaults from /quiz/embedded logic
        provider = body.get("provider")
        model = body.get("model")
        provider_keys = body.get("provider_keys", {})

        if not provider:
            if provider_keys.get("gemini"):
                provider = "gemini"
            elif provider_keys.get("claude"):
                provider = "claude"
            else:
                provider = "gemini"

        if not model and provider == "gemini":
            model = "gemini-2.5-pro"
        if not model and provider == "claude":
            model = "claude-sonnet-4-6"

        # Optional scene code as context
        context = body.get("sceneCode")
        num_questions = body.get("num_questions", 5)
        difficulty = body.get("difficulty", "medium")

        logger.info(
            "/quiz/media with provider=%s model=%s num_questions=%d difficulty=%s",
            provider,
            model,
            num_questions,
            difficulty,
        )

        # Add prefix to ensure quiz is generated only from media content
        media_prompt = (
            f"Generate quiz questions based ONLY on the following content "
            f"(from captions):\n\n{transcript}"
        )
        logger.debug("/quiz/media prompt length=%d", len(media_prompt))

        # Pass prefixed prompt to reuse all quiz_embedded logic
        quiz = generate_quiz_embedded(
            prompt=media_prompt,
            num_questions=num_questions,
            difficulty=difficulty,
            provider=provider,
            model=model,
            provider_keys=provider_keys,
            context=context,
        )

        logger.info(
            "/quiz/media completed successfully, questions=%d", len(quiz.get("questions", []))
        )
        return {"status": "ok", "quiz": quiz}
    except Exception as e:
        logger.exception("/quiz/media failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/podcast")
def podcast(body: PodcastIn, uid: str = Depends(require_firebase_user)):
    try:
        # Apply provider/model defaults similar to /generate
        provider = body.provider
        model = body.model
        if not provider:
            if body.keys.get("gemini"):
                provider = "gemini"
            elif body.keys.get("claude"):
                provider = "claude"
        if not model and provider == "gemini":
            model = "gemini-2.5-pro"
        if not model and provider == "claude":
            model = "claude-sonnet-4-6"
        logger.info("/podcast called provider=%s model=%s", provider, model)
        result = generate_podcast(
            prompt=body.prompt,
            provider=provider,
            model=model,
            provider_keys=body.keys,
            job_id=body.jobId,
        )
        logger.info("/podcast completed: %s", result.get("status"))

        # Upload podcast audio and VTT to GCS if bucket configured
        gcs_bucket = get_bucket_name()
        if gcs_bucket and result.get("video_url"):
            try:
                # Upload MP3 audio - use job_id for unique filename
                job_id = result.get("job_id", "unknown")
                relative_path = result["video_url"].replace("/static/", "")
                p = pathlib.Path(STORAGE) / relative_path
                if p.exists():
                    data = p.read_bytes()
                    content_type = mimetypes.guess_type(p.name)[0] or "audio/mpeg"
                    # Use job_id in filename to prevent overwrites
                    gcs_path = f"{uid}/chats/{body.chatId or 'uncategorized'}/podcast_{job_id}.mp3"
                    upload_bytes(gcs_bucket, gcs_path, data, content_type)
                    result["signed_video_url"] = sign_url(gcs_bucket, gcs_path)
                    result["gcs_path"] = gcs_path
                    saved_artifact_id = _save_artifact(
                        uid,
                        body.chatId,
                        "podcast",
                        gcs_path,
                        len(data),
                        content_type,
                        derived=False,
                    )
                    result["artifact_id"] = saved_artifact_id
                    logger.info("Podcast audio uploaded to GCS: %s", gcs_path)

                    # Upload podcast script for quiz fallback
                    if result.get("script"):
                        script_bytes = result["script"].encode("utf-8")
                        chat_path = body.chatId or "uncategorized"
                        script_gcs_path = f"{uid}/chats/{chat_path}/podcast_{job_id}_script.txt"
                        upload_bytes(gcs_bucket, script_gcs_path, script_bytes, "text/plain")
                        result["script_gcs_path"] = script_gcs_path
                        _save_artifact(
                            uid,
                            body.chatId,
                            "script",
                            script_gcs_path,
                            len(script_bytes),
                            "text/plain",
                            derived=True,
                        )
                        logger.info("Podcast script uploaded to GCS: %s", script_gcs_path)

                    # Upload VTT subtitle if exists - use same job_id for matching
                    if result.get("vtt_url"):
                        vtt_relative = result["vtt_url"].replace("/static/", "")
                        vtt_path_local = pathlib.Path(STORAGE) / vtt_relative
                        if vtt_path_local.exists():
                            vtt_data = vtt_path_local.read_bytes()
                            chat_path = body.chatId or "uncategorized"
                            vtt_gcs_path = f"{uid}/chats/{chat_path}/podcast_{job_id}.vtt"
                            upload_bytes(gcs_bucket, vtt_gcs_path, vtt_data, "text/vtt")
                            result["signed_subtitle_url"] = sign_url(gcs_bucket, vtt_gcs_path)
                            _save_artifact(
                                uid,
                                body.chatId,
                                "subtitle",
                                vtt_gcs_path,
                                len(vtt_data),
                                "text/vtt",
                                derived=True,
                            )
                            logger.info("Podcast VTT uploaded to GCS: %s", vtt_gcs_path)

                    # Clean up local files after successful GCS upload
                    if result.get("signed_video_url"):
                        try:
                            # Clean up MP3 file
                            if p.exists():
                                p.unlink()
                                logger.info("Cleaned up local podcast file: %s", p)
                            # Clean up VTT file if uploaded
                            if result.get("signed_subtitle_url") and vtt_path_local.exists():
                                vtt_path_local.unlink()
                                logger.info("Cleaned up local podcast VTT file: %s", vtt_path_local)
                        except Exception as e:
                            logger.warning("Failed to clean up local podcast files: %s", e)
            except Exception as e:
                logger.warning("GCS podcast upload failed: %s", e)
                # If GCS configured but upload failed, return error
                if gcs_bucket:
                    raise HTTPException(
                        status_code=500,
                        detail="Podcast generated but GCS upload failed. Please try again.",
                    ) from e
        else:
            # No GCS bucket configured, use local URLs
            if result.get("vtt_url"):
                result["signed_subtitle_url"] = result["vtt_url"]
                logger.info("Using local podcast VTT (no GCS bucket): %s", result["vtt_url"])

        # If GCS configured, ONLY return GCS URLs (no fallback)
        # If GCS not configured, return local URLs
        if gcs_bucket:
            if not result.get("signed_video_url"):
                raise HTTPException(
                    status_code=500,
                    detail="GCS bucket configured but upload failed. Please try again.",
                )
            result["video_url"] = result["signed_video_url"]
        # else: result["video_url"] already set from generate_podcast (local URL)

        return result
    except Exception as e:
        logger.exception("/podcast failed: %s", e)
        # Ensure detail is never empty so the frontend shows something useful
        msg = str(e)
        if not msg:
            msg = f"{type(e).__name__}"
        raise HTTPException(status_code=500, detail=msg) from e


# ================= Chat persistence routes =================


def _chat_doc(uid: str, chat_id: str):
    return get_db().collection("users").document(uid).collection("chats").document(chat_id)


# Legacy routes removed - use /api/{model}/chats instead


def _paginate_messages(
    chat_id: str, uid: str, limit: int, before_ms: int | None
) -> tuple[list[MessageOut], bool]:
    msgs_ref = _chat_doc(uid, chat_id).collection("messages")
    # order ASC for stable render; apply cursor as upper bound if provided
    if before_ms:
        # Firestore requires filtering by a field value; we stored createdAt as timestamp
        # For simplicity, fetch in DESC and then reverse for ASC output
        q = (
            msgs_ref.order_by("createdAt", direction=gcf.Query.DESCENDING)
            .where(
                "createdAt", "<", gcf.Timestamp(before_ms // 1000, (before_ms % 1000) * 1_000_000)
            )
            .limit(limit + 1)
        )
        snaps = list(q.stream())
        has_more = len(snaps) > limit
        if has_more:
            snaps = snaps[:limit]
        snaps.reverse()
    else:
        q = msgs_ref.order_by("createdAt", direction=gcf.Query.ASCENDING).limit(limit + 1)
        snaps = list(q.stream())
        has_more = len(snaps) > limit
        if has_more:
            snaps = snaps[:limit]
    out: list[MessageOut] = []
    for m in snaps:
        md = m.to_dict() or {}
        out.append(
            MessageOut(
                message_id=m.id,
                role=md.get("role", "assistant"),
                content=md.get("content", ""),
                createdAt=_to_ms(md.get("createdAt")),
                media=md.get("media") or None,
                quizAnchor=md.get("quizAnchor") or None,
                quizTitle=md.get("quizTitle") or None,
                quizData=md.get("quizData") or None,
            )
        )
    return out, has_more


# Legacy routes removed - use /api/{model}/chats/{chat_id} instead


def get_chat(chat_id: str, uid: str, limit: int = 200, before_ms: int | None = None):
    """Helper function to get chat."""
    chat_snap = _chat_doc(uid, chat_id).get()
    if not chat_snap.exists:
        raise HTTPException(status_code=404, detail="Chat not found")
    chat_data = chat_snap.to_dict() or {}
    msgs, _ = _paginate_messages(chat_id, uid, limit=limit, before_ms=before_ms)
    return ChatDetailOut(
        chat_id=chat_id,
        title=chat_data.get("title", "Untitled"),
        dts=_to_ms(chat_data.get("updatedAt")),
        sessionId=chat_data.get("sessionId"),
        messages=msgs,
        shareable=bool(chat_data.get("shareable", False)),
        share_token=chat_data.get("shareToken"),
        model=chat_data.get("model"),  # return stored model
    )


def append_message(chat_id: str, body: MessageCreateIn, uid: str):
    """Helper function to append message - used by model-based routes."""
    # ensure chat exists
    chat_ref = _chat_doc(uid, chat_id)
    if not chat_ref.get().exists:
        raise HTTPException(status_code=404, detail="Chat not found")
    get_db()
    # Idempotent: use client-provided message_id if present
    msg_ref = (
        chat_ref.collection("messages").document(body.message_id)
        if body.message_id
        else chat_ref.collection("messages").document()
    )
    existing = msg_ref.get()
    now = gcf.SERVER_TIMESTAMP
    data_to_set = {
        "role": body.role,
        "content": body.content,
        "createdAt": now,
    }
    # include media only if provided
    if body.media is not None:
        try:
            media_dict = body.media.dict(exclude_none=True)
        except Exception:
            media_dict = None
        if media_dict:
            data_to_set["media"] = media_dict
    # include quiz data if provided
    if body.quizAnchor is not None:
        data_to_set["quizAnchor"] = body.quizAnchor
    if body.quizTitle is not None:
        data_to_set["quizTitle"] = body.quizTitle
    if body.quizData is not None:
        data_to_set["quizData"] = body.quizData
    if existing.exists:
        # Return existing without overwriting createdAt; update content/media only if changed
        try:
            msg_ref.update({k: v for k, v in data_to_set.items() if k != "createdAt"})
        except Exception:
            pass
    else:
        msg_ref.set(data_to_set)
    # bump chat updatedAt
    chat_ref.update({"updatedAt": now})
    snap = msg_ref.get()
    data = snap.to_dict() or {}
    return MessageOut(
        message_id=msg_ref.id,
        role=data.get("role", body.role),
        content=data.get("content", body.content),
        createdAt=_to_ms(data.get("createdAt")),
        media=data.get("media") or None,
        quizAnchor=data.get("quizAnchor") or None,
        quizTitle=data.get("quizTitle") or None,
        quizData=data.get("quizData") or None,
    )


def list_chats(uid: str, limit: int = 50):
    """Helper function to list chats - used by model-based routes."""
    db = get_db()
    chats_ref = db.collection("users").document(uid).collection("chats")
    q = chats_ref.order_by("updatedAt", direction=gcf.Query.DESCENDING).limit(limit)
    docs = q.stream()
    out: list[ChatItemOut] = []
    for d in docs:
        data = d.to_dict() or {}
        out.append(
            ChatItemOut(
                chat_id=d.id,
                title=data.get("title", "Untitled"),
                dts=_to_ms(data.get("updatedAt")),
                sessionId=data.get("sessionId"),
                shareable=bool(data.get("shareable", False)),
                share_token=data.get("shareToken"),
            )
        )
    return out


def create_chat(body: ChatCreateIn, uid: str):
    """Helper function to create chat."""
    db = get_db()
    chat_ref = db.collection("users").document(uid).collection("chats").document()
    now = gcf.SERVER_TIMESTAMP
    # Respect sharing flags if provided at creation (rare)
    shareable = bool(body.shareable)
    share_token = body.share_token if shareable else None
    chat_ref.set(
        {
            "title": body.title or "New Chat",
            "model": body.model or None,
            "sessionId": body.sessionId or None,
            "createdAt": now,
            "updatedAt": now,
            "shareable": shareable,
            "shareToken": share_token,
        }
    )
    snap = chat_ref.get()
    data = snap.to_dict() or {}
    return ChatItemOut(
        chat_id=chat_ref.id,
        title=data.get("title", "New Chat"),
        dts=_to_ms(data.get("updatedAt")),
        sessionId=data.get("sessionId"),
        shareable=bool(data.get("shareable", False)),
        share_token=data.get("shareToken"),
    )


class ArtifactRefreshOut(BaseModel):
    ok: bool
    signed_video_url: str | None = None
    signed_subtitle_url: str | None = None
    gcs_path: str | None = None
    artifact_id: str | None = None


@app.get("/api/artifacts/refresh", response_model=ArtifactRefreshOut)
def refresh_artifact(
    artifactId: str | None = Query(None),
    gcsPath: str | None = Query(None),
    subtitle: bool = Query(False),
    uid: str = Depends(require_firebase_user),
):
    """Return fresh signed URL(s) for a previously stored artifact.

    Caller can pass either artifactId (preferred) or gcsPath. If subtitle=True, return a
    signed_subtitle_url for the .vtt alongside the object (preferred). Older artifacts may
    still have only .srt; client will fallback if needed.
    """
    gcs_bucket = get_bucket_name()
    if not gcs_bucket:
        raise HTTPException(status_code=400, detail="No GCS bucket configured")
    path = gcsPath
    # If artifactId given, lookup its gcsPath
    if artifactId and not path:
        try:
            db = get_db()
            snap = (
                db.collection("users")
                .document(uid)
                .collection("artifacts")
                .document(artifactId)
                .get()
            )
            if not snap.exists:
                raise HTTPException(status_code=404, detail="Artifact not found")
            doc = snap.to_dict() or {}
            path = doc.get("gcsPath")
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("artifact lookup failed: %s", e)
            raise HTTPException(status_code=500, detail="Artifact lookup failed") from e
    if not path:
        raise HTTPException(status_code=400, detail="Missing artifactId or gcsPath")
    try:
        signed_main = sign_url(gcs_bucket, path)
        signed_sub = None
        if subtitle:
            base, ext = os.path.splitext(path)
            vtt_path = base + ".vtt"
            # Sign .vtt preferred; client can fallback if object is missing
            signed_sub = sign_url(gcs_bucket, vtt_path)
        return ArtifactRefreshOut(
            ok=True,
            signed_video_url=signed_main,
            signed_subtitle_url=signed_sub,
            gcs_path=path,
            artifact_id=artifactId,
        )
    except Exception as e:
        logger.warning("artifact refresh failed: %s", e)
        raise HTTPException(status_code=500, detail="Refresh failed") from e


def list_messages(chat_id: str, uid: str, limit: int = 50, before_ms: int | None = None):
    """Helper function to list messages."""
    chat_snap = _chat_doc(uid, chat_id).get()
    if not chat_snap.exists:
        raise HTTPException(status_code=404, detail="Chat not found")
    msgs, has_more = _paginate_messages(chat_id, uid, limit=limit, before_ms=before_ms)
    return MessagesPage(messages=msgs, has_more=has_more)


@app.get("/api/chats/{chat_id}/export")
def export_chat(chat_id: str, uid: str = Depends(require_firebase_user)):
    # Simple JSON export of conversation and messages
    chat_snap = _chat_doc(uid, chat_id).get()
    if not chat_snap.exists:
        raise HTTPException(status_code=404, detail="Chat not found")
    chat_data = chat_snap.to_dict() or {}
    # export all messages in ASC order
    snaps = (
        _chat_doc(uid, chat_id)
        .collection("messages")
        .order_by("createdAt", direction=gcf.Query.ASCENDING)
        .stream()
    )
    msgs = []
    for m in snaps:
        d = m.to_dict() or {}
        msgs.append(
            {
                "message_id": m.id,
                "role": d.get("role"),
                "content": d.get("content"),
                "createdAt": _to_ms(d.get("createdAt")),
                "media": d.get("media") or None,
            }
        )
    out = {
        "chat": {
            "chat_id": chat_id,
            "title": chat_data.get("title", "Untitled"),
            "createdAt": _to_ms(chat_data.get("createdAt")),
            "updatedAt": _to_ms(chat_data.get("updatedAt")),
        },
        "messages": msgs,
        "version": 1,
    }
    return out


class ChatRenameIn(BaseModel):
    title: str


class ChatShareToggleIn(BaseModel):
    shareable: bool


def rename_chat(chat_id: str, body: ChatRenameIn, uid: str):
    """Helper function to rename chat."""
    chat_ref = _chat_doc(uid, chat_id)
    snap = chat_ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Chat not found")
    now = gcf.SERVER_TIMESTAMP
    chat_ref.update({"title": body.title, "updatedAt": now})
    # re-read
    snap = chat_ref.get()
    data = snap.to_dict() or {}
    return ChatItemOut(
        chat_id=chat_id,
        title=data.get("title", body.title),
        dts=_to_ms(data.get("updatedAt")),
        shareable=bool(data.get("shareable", False)),
        share_token=data.get("shareToken"),
    )


@app.patch("/api/chats/{chat_id}/share", response_model=ChatItemOut)
def toggle_share(chat_id: str, body: ChatShareToggleIn, uid: str = Depends(require_firebase_user)):
    """Enable or disable sharing for a chat. When enabling, generate a token if absent.

    Returns updated ChatItemOut including share flags.
    """

    chat_ref = _chat_doc(uid, chat_id)
    snap = chat_ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Chat not found")
    data = snap.to_dict() or {}
    now = gcf.SERVER_TIMESTAMP
    shareable = bool(body.shareable)
    # Preserve existing token if already set; generate new on first enable
    share_token = data.get("shareToken")
    if shareable and not share_token:
        # Short token (8 chars) derived from uuid4 for URL friendliness
        share_token = uuid4().hex[:16]
    chat_ref.update(
        {
            "shareable": shareable,
            # Keep token stable even if disabling so re-enable doesn't break old links (optional)
            "shareToken": share_token,
            "updatedAt": now,
        }
    )
    snap = chat_ref.get()
    updated = snap.to_dict() or {}
    return ChatItemOut(
        chat_id=chat_id,
        title=updated.get("title", data.get("title", "Untitled")),
        dts=_to_ms(updated.get("updatedAt")),
        sessionId=updated.get("sessionId"),
        shareable=bool(updated.get("shareable", False)),
        share_token=updated.get("shareToken"),
    )


@app.get("/api/share/{token}", response_model=ChatDetailOut)
def get_shared_chat(token: str, limit: int = Query(500, ge=1, le=1000)):
    """Public retrieval of a shared chat by token.

    Does not require auth. Returns 404 if token not found or chat not shareable.
    """
    db = get_db()
    try:
        # collection group query over all users' chats subcollections
        q = db.collection_group("chats").where("shareToken", "==", token).limit(1)
        docs = list(q.stream())
    except Exception as e:
        logger.warning("share lookup failed: %s", e)
        raise HTTPException(status_code=500, detail="Share lookup failed") from e
    if not docs:
        raise HTTPException(status_code=404, detail="Shared chat not found")
    doc = docs[0]
    chat_data = doc.to_dict() or {}
    if not chat_data.get("shareable"):
        # treat as not found to avoid leaking existence
        raise HTTPException(status_code=404, detail="Shared chat not found")
    # Get chat_id from the document
    chat_id = doc.id
    # Load messages (ASC order) limited by 'limit'
    msgs_snap = (
        doc.reference.collection("messages")
        .order_by("createdAt", direction=gcf.Query.ASCENDING)
        .limit(limit)
        .stream()
    )
    msgs: list[MessageOut] = []
    for m in msgs_snap:
        md = m.to_dict() or {}
        msgs.append(
            MessageOut(
                message_id=m.id,
                role=md.get("role", "assistant"),
                content=md.get("content", ""),
                createdAt=_to_ms(md.get("createdAt")),
                media=md.get("media") or None,
                quizAnchor=md.get("quizAnchor") or None,
                quizTitle=md.get("quizTitle") or None,
                quizData=md.get("quizData") or None,
            )
        )
    return ChatDetailOut(
        chat_id=chat_id,
        title=chat_data.get("title", "Untitled"),
        dts=_to_ms(chat_data.get("updatedAt")),
        sessionId=chat_data.get("sessionId"),  # not secret; optional for client heuristics
        messages=msgs,
        shareable=True,
        share_token=token,
        model=chat_data.get("model"),  # return stored model
    )


# ================= Chat routes (non-model-specific) =================


@app.get("/api/chats", response_model=list[ChatItemOut])
def list_chats_route(
    limit: int = Query(50, ge=1, le=200), uid: str = Depends(require_firebase_user)
):
    """List all chats for the authenticated user."""
    return list_chats(uid, limit)


@app.post("/api/chats", response_model=ChatItemOut)
def create_chat_route(
    body: ChatCreateIn,
    uid: str = Depends(require_firebase_user),
    x_session_id: str | None = Header(None, alias="X-Session-ID"),
):
    """Create a new chat. Model is stored in the chat document. Supports X-Session-ID header."""
    # Use session ID from header if provided
    if x_session_id and not body.sessionId:
        body.sessionId = x_session_id
    # If content provided in body (first message), create chat and immediately append message
    if body.content:
        result = create_chat(body, uid)
        # Append the first message
        try:
            msg_body = MessageCreateIn(
                role="user",
                content=body.content,
                timestamp=body.timestamp if hasattr(body, "timestamp") else None,
            )
            append_message(result.chat_id, msg_body, uid)
        except Exception:
            pass  # Continue even if message append fails
        return result
    return create_chat(body, uid)


@app.get("/api/chats/{chat_id}", response_model=ChatDetailOut)
def get_chat_route(
    chat_id: str,
    uid: str = Depends(require_firebase_user),
    limit: int = Query(200, ge=1, le=500),
    before: int | None = Query(None),
):
    """Get a chat by ID."""
    return get_chat(chat_id, uid, limit, before)


@app.post("/api/chats/{chat_id}", response_model=ChatDetailOut)
def continue_chat_route(
    chat_id: str,
    body: MessageCreateIn,
    uid: str = Depends(require_firebase_user),
    x_session_id: str | None = Header(None, alias="X-Session-ID"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    """Continue an existing chat (append message).

    Supports X-Session-ID and Idempotency-Key headers.
    """
    # Use idempotency key if provided for message_id
    if idempotency_key and not body.message_id:
        body.message_id = idempotency_key
    # Append message
    append_message(chat_id, body, uid)
    # Return full chat detail
    chat_snap = _chat_doc(uid, chat_id).get()
    if not chat_snap.exists:
        raise HTTPException(status_code=404, detail="Chat not found")
    chat_data = chat_snap.to_dict() or {}
    msgs, _ = _paginate_messages(chat_id, uid, limit=200, before_ms=None)
    return ChatDetailOut(
        chat_id=chat_id,
        title=chat_data.get("title", "Untitled"),
        dts=_to_ms(chat_data.get("updatedAt")),
        sessionId=chat_data.get("sessionId"),
        messages=msgs,
        shareable=bool(chat_data.get("shareable", False)),
        share_token=chat_data.get("shareToken"),
        model=chat_data.get("model"),  # return stored model
    )


@app.get("/api/chats/{chat_id}/messages", response_model=MessagesPage)
def list_messages_route(
    chat_id: str,
    uid: str = Depends(require_firebase_user),
    limit: int = Query(50, ge=1, le=200),
    before: int | None = Query(None),
):
    """List messages for a chat."""
    return list_messages(chat_id, uid, limit, before)


@app.patch("/api/chats/{chat_id}", response_model=ChatItemOut)
def rename_chat_route(chat_id: str, body: ChatRenameIn, uid: str = Depends(require_firebase_user)):
    """Rename a chat."""
    return rename_chat(chat_id, body, uid)


@app.delete("/api/chats/{chat_id}")
def delete_chat_route(chat_id: str, uid: str = Depends(require_firebase_user)):
    """Delete a chat."""
    return _delete_chat_impl(chat_id, uid)


@app.delete("/api/account")
def delete_account_route(uid: str = Depends(require_firebase_user)):
    """Delete user account and all associated data."""
    if DESKTOP_LOCAL_MODE:
        return {
            "ok": True,
            "uid": uid,
            "chats_removed": 0,
            "messages_removed": 0,
            "artifacts_removed": 0,
            "gcs_files_removed": 0,
        }
    return _delete_account_impl(uid)


def _delete_chat_impl(chat_id: str, uid: str):
    chat_ref = _chat_doc(uid, chat_id)
    snap = chat_ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Chat not found")
    # delete messages subcollection (batch)
    db = get_db()
    batch = db.batch()
    msgs = chat_ref.collection("messages").stream()
    count = 0
    for m in msgs:
        batch.delete(m.reference)
        count += 1
    batch.delete(chat_ref)
    batch.commit()

    # Delete GCS folder for this chat (all media files)
    gcs_bucket = get_bucket_name()
    gcs_deleted = 0
    if gcs_bucket:
        try:
            folder_prefix = f"{uid}/chats/{chat_id}/"
            gcs_deleted = delete_folder(gcs_bucket, folder_prefix)
        except Exception as e:
            logger.warning("Failed to delete GCS folder for chat %s: %s", chat_id, e)

    return {
        "ok": True,
        "deleted": chat_id,
        "messages_removed": count,
        "gcs_files_removed": gcs_deleted,
    }


def _delete_account_impl(uid: str):
    """Delete all user data including chats, artifacts, and Firebase Auth account."""
    db = get_db()

    logger.info("Starting account deletion for user %s", uid)

    # Helper function to recursively delete a collection
    def delete_collection(coll_ref, batch_size=500):
        deleted = 0
        docs = coll_ref.limit(batch_size).stream()
        deleted_batch = 0

        for doc in docs:
            doc.reference.delete()
            deleted += 1
            deleted_batch += 1

        if deleted_batch >= batch_size:
            # There might be more documents, recursively delete
            return deleted + delete_collection(coll_ref, batch_size)

        return deleted

    total_chats = 0
    total_messages = 0
    total_artifacts = 0
    total_gcs_files = 0

    # Delete all chats and their messages
    # Use direct path to chats collection
    chats_ref = db.collection("users").document(uid).collection("chats")
    chats = list(chats_ref.stream())
    logger.info("Found %d chats for user %s", len(chats), uid)

    # Delete each chat and its messages
    for chat in chats:
        chat_id = chat.id
        logger.debug("Deleting chat %s", chat_id)

        # Delete messages subcollection recursively
        msgs_ref = chat.reference.collection("messages")
        msg_count = delete_collection(msgs_ref)
        logger.debug("Deleted %d messages in chat %s", msg_count, chat_id)

        total_messages += msg_count

        # Delete chat document
        chat.reference.delete()
        total_chats += 1
        logger.info("Deleted chat %s with %d messages", chat_id, msg_count)

    # Delete all artifacts
    artifacts_ref = db.collection("users").document(uid).collection("artifacts")
    total_artifacts = delete_collection(artifacts_ref)
    logger.info("Deleted %d artifacts for user %s", total_artifacts, uid)

    # Delete all GCS media for this user
    gcs_bucket = get_bucket_name()
    if gcs_bucket:
        try:
            # Delete all files under user's folder
            folder_prefix = f"{uid}/"
            logger.info(
                "Attempting to delete GCS objects with prefix: gs://%s/%s",
                gcs_bucket,
                folder_prefix,
            )
            total_gcs_files = delete_folder(gcs_bucket, folder_prefix)

            # Also delete chats folder placeholder if it exists
            chats_folder = f"{uid}/chats/"
            delete_folder(gcs_bucket, chats_folder)

            logger.info("Deleted %d GCS files for user %s", total_gcs_files, uid)
        except Exception as e:
            logger.warning("Failed to delete GCS folder for user %s: %s", uid, e)
    else:
        logger.warning("No GCS bucket configured, skipping GCS deletion")

    # Delete user document from Firestore (this removes the entire user entry)
    # Note: This must be done AFTER deleting all subcollections
    try:
        user_ref = db.collection("users").document(uid)
        user_doc = user_ref.get()
        if user_doc.exists:
            user_ref.delete()
            logger.info("Deleted Firestore user document for %s", uid)
        else:
            logger.info(
                "No Firestore user document found for %s (already deleted or never created)", uid
            )
    except Exception as e:
        logger.error("Failed to delete Firestore user document for %s: %s", uid, e)

    # Note: Firebase Auth account deletion is handled client-side
    # Users can delete their own accounts without admin permissions

    logger.info(
        "Completed account deletion for user %s: %d chats, %d messages, %d artifacts, %d GCS files",
        uid,
        total_chats,
        total_messages,
        total_artifacts,
        total_gcs_files,
    )

    return {
        "ok": True,
        "uid": uid,
        "chats_removed": total_chats,
        "messages_removed": total_messages,
        "artifacts_removed": total_artifacts,
        "gcs_files_removed": total_gcs_files,
    }


def _to_ms(ts) -> int | None:
    try:
        if ts is None:
            return None
        # Firestore timestamp has seconds + nanoseconds
        seconds = getattr(ts, "seconds", None)
        nanos = getattr(ts, "nanoseconds", 0)
        if seconds is None:
            return None
        return int(seconds * 1000 + nanos / 1_000_000)
    except Exception:
        return None


@app.post("/jobs/cancel")
def jobs_cancel(jobId: str = Query(...)):
    try:
        logger.info("/jobs/cancel called jobId=%s", jobId)
        res = cancel_job(jobId)
        return res
    except Exception as e:
        logger.exception("/jobs/cancel failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e
