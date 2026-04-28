import json
import logging
import mimetypes
import os
import pathlib
import re
import time
from difflib import SequenceMatcher
from typing import Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.agent.code_sanitize import sanitize_minimally
from backend.agent.llm.clients import call_llm
from backend.agent.minigraph import echo_manim_code
from backend.agent.prompts import EDIT_SYSTEM, build_edit_user_prompt
from backend.runner.job_runner import STORAGE, cancel_job, run_job_from_code, to_static_url
from backend.utils import app_logging  # noqa: F401

logger = logging.getLogger(f"app.{__name__}")
APP_MODE = os.environ.get("APP_MODE", "cloud").strip().lower()
DESKTOP_LOCAL_MODE = APP_MODE == "desktop-local"
try:
    from google.cloud import firestore as gcf  # type: ignore
except Exception:  # pragma: no cover
    gcf = None

_DESKTOP_STORE: dict[str, dict] = {}
_DESKTOP_STATE_DIR = pathlib.Path(os.environ.get("UPCURVED_DESKTOP_STATE_DIR", ".desktop-state"))
_DESKTOP_STATE_FILE = _DESKTOP_STATE_DIR / "desktop_store.json"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _desktop_user(uid: str) -> dict:
    return _DESKTOP_STORE.setdefault(uid, {"chats": {}})


def _desktop_chat(uid: str, chat_id: str) -> dict | None:
    return _desktop_user(uid)["chats"].get(chat_id)


def _normalize_desktop_store(raw: dict | None) -> dict[str, dict]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict] = {}
    for uid, user_data in raw.items():
        if not isinstance(uid, str):
            continue
        chats = {}
        if isinstance(user_data, dict):
            chats_in = user_data.get("chats", {})
            if isinstance(chats_in, dict):
                chats = chats_in
        out[uid] = {"chats": chats}
    return out


def _load_desktop_store() -> None:
    global _DESKTOP_STORE
    try:
        _DESKTOP_STATE_DIR.mkdir(parents=True, exist_ok=True)
        if not _DESKTOP_STATE_FILE.exists():
            _DESKTOP_STORE = {}
            return
        data = json.loads(_DESKTOP_STATE_FILE.read_text(encoding="utf-8"))
        _DESKTOP_STORE = _normalize_desktop_store(data)
    except Exception as e:
        logger.warning("Failed to load desktop state from %s: %s", _DESKTOP_STATE_FILE, e)
        _DESKTOP_STORE = {}


def _save_desktop_store() -> None:
    if not DESKTOP_LOCAL_MODE:
        return
    try:
        _DESKTOP_STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _DESKTOP_STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_DESKTOP_STORE, ensure_ascii=True), encoding="utf-8")
        tmp.replace(_DESKTOP_STATE_FILE)
    except Exception as e:
        logger.warning("Failed to persist desktop state to %s: %s", _DESKTOP_STATE_FILE, e)


if DESKTOP_LOCAL_MODE:
    _load_desktop_store()


def _run_to_code(
    prompt: str,
    provider_keys: dict | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> tuple[str, str | None, bool, str | None, str | None]:
    from backend.agent.graph import run_to_code as _run_to_code_canonical

    return _run_to_code_canonical(
        prompt=prompt, provider_keys=provider_keys, provider=provider, model=model
    )


def run_to_code(
    prompt: str,
    provider_keys: dict | None = None,
    provider: str | None = None,
    model: str | None = None,
):
    return _run_to_code(
        prompt=prompt, provider_keys=provider_keys, provider=provider, model=model
    )


def _get_db():
    from backend.firebase_app import get_db as _get_db_impl

    return _get_db_impl()


def _init_firebase():
    from backend.firebase_app import init_firebase as _init_firebase_impl

    return _init_firebase_impl()


def _get_bucket_name() -> str:
    try:
        from backend.gcs_utils import get_bucket_name as _get_bucket_name_impl

        return _get_bucket_name_impl() or ""
    except Exception:
        return ""


def _upload_bytes(bucket: str, path: str, data: bytes, content_type: str) -> str:
    from backend.gcs_utils import upload_bytes as _upload_bytes_impl

    return _upload_bytes_impl(bucket, path, data, content_type)


def _sign_url(bucket: str, path: str, minutes: int = 60) -> str:
    from backend.gcs_utils import sign_url as _sign_url_impl

    return _sign_url_impl(bucket, path, minutes)


def _delete_folder(bucket: str, prefix: str) -> int:
    from backend.gcs_utils import delete_folder as _delete_folder_impl

    return _delete_folder_impl(bucket, prefix)


def _generate_quiz_embedded(*args, **kwargs):
    from backend.mcp.quiz_logic import generate_quiz_embedded as _impl

    return _impl(*args, **kwargs)


def _generate_podcast(*args, **kwargs):
    from backend.mcp.podcast_logic import generate_podcast as _impl

    return _impl(*args, **kwargs)


def _generate_widget(*args, **kwargs):
    from backend.mcp.widget_logic import generate_widget as _impl

    return _impl(*args, **kwargs)


def _generate_story_video(*args, **kwargs):
    from backend.mcp.story_video_logic import generate_story_video as _impl

    return _impl(*args, **kwargs)


def _generate_story_slider(*args, **kwargs):
    from backend.mcp.story_video_logic import generate_story_slider as _impl

    return _impl(*args, **kwargs)


def require_firebase_user(
    authorization: str | None = Header(None),
    x_desktop_user: str | None = Header(None, alias="X-Desktop-User"),
) -> str:
    if DESKTOP_LOCAL_MODE:
        if x_desktop_user and x_desktop_user.strip():
            safe = re.sub(r"[^a-zA-Z0-9._-]", "_", x_desktop_user.strip())[:128]
            return safe or "desktop-local-user"
        return "desktop-local-user"

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        from firebase_admin import auth as fb_auth

        _init_firebase()
        decoded = fb_auth.verify_id_token(token)
        uid = decoded.get("uid")
        if not uid:
            raise ValueError("uid missing")
        return uid
    except Exception as e:
        logger.warning("Auth failed: %s", e)
        raise HTTPException(status_code=401, detail="Invalid token") from e


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
    _DEFAULT_ORIGINS.extend(
        [
            f"https://{_GCP_PROJECT}.firebaseapp.com",
            f"https://{_GCP_PROJECT}.web.app",
        ]
    )

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

if not _get_bucket_name():
    app.mount("/static", StaticFiles(directory=str(STORAGE)), name="static")


class GenerateIn(BaseModel):
    prompt: str
    keys: dict[str, str] = {}
    provider: Literal["claude", "gemini"] | None = None
    model: str | None = None
    mode: Literal["standard", "story"] | None = "standard"
    storyOptions: dict | None = None
    jobId: str | None = None
    chatId: str | None = None
    sessionId: str | None = None


class QuizIn(BaseModel):
    prompt: str
    num_questions: int = 5
    difficulty: Literal["easy", "medium", "hard"] | None = "medium"
    keys: dict[str, str] = {}
    provider: Literal["claude", "gemini"] | None = None
    model: str | None = None
    context: str | None = None
    userEmail: str | None = None


class PodcastIn(BaseModel):
    prompt: str
    keys: dict[str, str] = {}
    provider: Literal["claude", "gemini"] | None = None
    model: str | None = None
    mode: Literal["standard", "debate"] | None = "standard"
    jobId: str | None = None
    chatId: str | None = None
    sessionId: str | None = None


class WidgetIn(BaseModel):
    prompt: str
    keys: dict[str, str] = {}
    provider: Literal["claude", "gemini"] | None = None
    model: str | None = None
    jobId: str | None = None
    chatId: str | None = None
    sessionId: str | None = None


class EditVideoIn(BaseModel):
    original_code: str
    edit_instructions: str
    keys: dict[str, str] = {}
    provider: Literal["claude", "gemini"] | None = None
    model: str | None = None
    jobId: str | None = None
    chatId: str | None = None
    sessionId: str | None = None


class ChatCreateIn(BaseModel):
    title: str | None = Field(default="New Chat")
    model: str | None = None
    sessionId: str | None = None
    shareable: bool = False
    share_token: str | None = None
    content: str | None = None
    timestamp: str | None = None


class ChatItemOut(BaseModel):
    chat_id: str
    title: str
    dts: int | None = None
    sessionId: str | None = None
    shareable: bool = False
    share_token: str | None = None


class MessageMedia(BaseModel):
    type: str | None = None
    url: str | None = None
    subtitleUrl: str | None = None
    artifactId: str | None = None
    title: str | None = None
    gcsPath: str | None = None
    sceneCode: str | None = None
    widgetCode: str | None = None


class MessageCreateIn(BaseModel):
    message_id: str | None = None
    role: Literal["user", "assistant"]
    content: str
    media: MessageMedia | None = None
    quizAnchor: bool | None = None
    quizTitle: str | None = None
    quizData: dict | None = None


class MessageOut(BaseModel):
    message_id: str
    role: Literal["user", "assistant"]
    content: str
    createdAt: int | None = None
    media: MessageMedia | None = None
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
    model: str | None = None


@app.get("/health")
def health():
    return {"ok": True, "mode": APP_MODE}


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
    if DESKTOP_LOCAL_MODE or gcf is None:
        return None
    try:
        db = _get_db()
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
    try:
        import srt as srtlib  # type: ignore

        subs = list(srtlib.parse(srt_text))
        lines = ["WEBVTT", ""]
        for cue in subs:
            start = str(cue.start).replace(",", ".")
            end = str(cue.end).replace(",", ".")
            text = cue.content.replace("\r\n", "\n")
            lines.append(f"{start} --> {end}")
            lines.extend(text.split("\n"))
            lines.append("")
        return "\n".join(lines) + "\n"
    except Exception:
        body = []
        for line in srt_text.splitlines():
            body.append(re.sub(r"(\d\d:\d\d:\d\d),(\d\d\d)", r"\1.\2", line))
        return "WEBVTT\n\n" + "\n".join(body) + "\n"


@app.post("/generate")
def generate(body: GenerateIn, uid: str = Depends(require_firebase_user)):
    try:
        provider = body.provider
        model = body.model
        gen_mode = (body.mode or "standard").strip().lower()
        if not provider:
            if body.keys.get("gemini"):
                provider = "gemini"
            elif body.keys.get("claude"):
                provider = "claude"
        if not model and provider == "gemini":
            model = "gemini-3-flash-preview"
        if not model and provider == "claude":
            model = "claude-haiku-4-5"
        logger.info("/generate called provider=%s model=%s mode=%s", provider, model, gen_mode)

        if gen_mode == "story":
            story_res = _generate_story_slider(
                prompt=body.prompt,
                provider=provider,
                model=model,
                provider_keys=body.keys,
                story_options=body.storyOptions or {},
            )
            widget_html = story_res.get("widget_html")
            if story_res.get("status") == "ok" and widget_html:
                return {
                    "ok": True,
                    "status": "ok",
                    "widget_html": widget_html,
                    "story_plan": story_res.get("story_plan"),
                    "generation_mode": "story",
                    "message": "Story scene slider generated.",
                }
            return {
                "ok": False,
                "status": "error",
                "error": "story_slider_failed",
                "message": "Story generation failed.",
                "video_url": None,
            }
        else:
            code, video_url, render_ok, generated_job_id, failure_detail = run_to_code(
                prompt=body.prompt,
                provider_keys=body.keys,
                provider=provider,
                model=model,
            )

        if render_ok and video_url:
            gcs_bucket = _get_bucket_name()
            signed_video_url = None
            signed_subtitle_url = None
            saved_artifact_id = None
            gcs_path = None

            relative_path = video_url.replace("/static/", "")
            p = pathlib.Path(STORAGE) / relative_path
            job_id = generated_job_id or body.jobId or "unknown"
            if gcs_bucket:
                try:
                    if p.exists():
                        data = p.read_bytes()
                        content_type = mimetypes.guess_type(p.name)[0] or "video/mp4"
                        gcs_path = f"{uid}/chats/{body.chatId or 'uncategorized'}/video_{job_id}.mp4"
                        _upload_bytes(gcs_bucket, gcs_path, data, content_type)
                        signed_video_url = _sign_url(gcs_bucket, gcs_path)
                        saved_artifact_id = _save_artifact(
                            uid, body.chatId, "video", gcs_path, len(data), content_type, derived=False
                        )
                        vtt_local = p.with_suffix(".vtt")
                        if vtt_local.exists():
                            try:
                                vtt_bytes = vtt_local.read_bytes()
                                chat_path = body.chatId or "uncategorized"
                                vtt_path = f"{uid}/chats/{chat_path}/video_{job_id}.vtt"
                                _upload_bytes(gcs_bucket, vtt_path, vtt_bytes, "text/vtt")
                                signed_subtitle_url = _sign_url(gcs_bucket, vtt_path)
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
                        if code:
                            py_bytes = code.encode("utf-8")
                            py_path = f"{uid}/chats/{body.chatId or 'uncategorized'}/scene_{job_id}.py"
                            _upload_bytes(gcs_bucket, py_path, py_bytes, "text/x-python")
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

                if signed_video_url and gcs_bucket:
                    try:
                        if p.exists():
                            p.unlink()
                        if signed_subtitle_url:
                            vtt_local = p.with_suffix(".vtt")
                            if vtt_local.exists():
                                vtt_local.unlink()
                        if code:
                            job_dir = p.parent.parent
                            py_local = job_dir / "scene.py"
                            if py_local.exists():
                                py_local.unlink()
                        try:
                            job_dir = p.parent.parent
                            remaining_files = [f for f in job_dir.iterdir() if f.is_file()]
                            if job_dir.exists() and len(remaining_files) == 0:
                                for subdir in ["logs", "out"]:
                                    subdir_path = job_dir / subdir
                                    if subdir_path.exists():
                                        try:
                                            subdir_path.rmdir()
                                        except Exception:
                                            pass
                                try:
                                    job_dir.rmdir()
                                except Exception:
                                    pass
                        except Exception:
                            pass
                    except Exception as e:
                        logger.warning("Failed to clean up local files: %s", e)

            if gcs_bucket:
                if not signed_video_url:
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
                final_video_url = video_url
                if not signed_subtitle_url and p.exists():
                    vtt_local = p.with_suffix(".vtt")
                    if vtt_local.exists():
                        signed_subtitle_url = to_static_url(vtt_local)

            res = {
                "ok": True,
                "status": "ok",
                "video_url": final_video_url,
                "signed_video_url": signed_video_url,
                "signed_subtitle_url": signed_subtitle_url,
                "artifact_id": saved_artifact_id,
                "gcs_path": gcs_path if gcs_bucket and signed_video_url else None,
                "scene_code": code,
                "generation_mode": gen_mode,
                "message": "Video generated.",
            }
            logger.info("/generate completed: ok (job_id=%s)", generated_job_id)
            return res

        logger.warning("/generate failed (job_id=%s)", generated_job_id)
        debug = (failure_detail or "").strip()
        if debug:
            debug = debug[:500]
        return {
            "ok": False,
            "status": "error",
            "error": "render_failed",
            "message": "Video generation failed.",
            "video_url": None,
            "debug_detail": debug or None,
        }
    except Exception as e:
        logger.exception("/generate failed with exception: %s", e)
        msg = str(e) if str(e) else f"{type(e).__name__}"
        raise HTTPException(status_code=500, detail=msg) from e


def _apply_unified_diff(original: str, diff_text: str, apply_all_matches: bool = False) -> str | None:
    try:
        lines = original.split("\n")
        result_lines = lines.copy()
        hunk_pattern = r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@"
        hunks = re.split(hunk_pattern, diff_text)
        if len(hunks) < 4:
            logger.warning("No valid hunks found in diff")
            return None
        applied_ranges = []
        i = 1
        while i < len(hunks) - 2:
            old_start = int(hunks[i]) - 1
            int(hunks[i + 1]) - 1
            hunk_content = hunks[i + 2]
            i += 3
            hunk_lines = hunk_content.strip().split("\n")
            context_lines = []
            remove_lines = []
            add_lines = []
            for line in hunk_lines:
                if not line:
                    continue
                if line.startswith("-"):
                    remove_lines.append(line[1:])
                elif line.startswith("+"):
                    add_lines.append(line[1:])
                elif line.startswith(" "):
                    context_lines.append(line[1:])
                else:
                    context_lines.append(line)
            if not remove_lines and not add_lines:
                continue
            search_pattern = remove_lines if remove_lines else context_lines[:1]
            if not search_pattern:
                continue
            search_text = "\n".join(search_pattern)
            matches = []
            base_threshold = 0.7 if apply_all_matches else 0.8
            if len(search_pattern) <= 2:
                base_threshold = max(base_threshold, 0.85)
            for idx in range(0, len(result_lines)):
                if idx + len(search_pattern) > len(result_lines):
                    continue
                if any(start <= idx < end for start, end in applied_ranges):
                    continue
                candidate = "\n".join(result_lines[idx : idx + len(search_pattern)])
                score = SequenceMatcher(None, search_text.strip(), candidate.strip()).ratio()
                if score > base_threshold:
                    matches.append((idx, score))
            if not matches:
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
                matches.sort(key=lambda x: x[0], reverse=True)
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
            else:
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
        return "\n".join(result_lines)
    except Exception as e:
        logger.warning("Failed to apply diff: %s", e)
        return None


@app.post("/edit")
def edit_video(body: EditVideoIn, uid: str = Depends(require_firebase_user)):
    logger.info("=" * 50)
    logger.info("/edit endpoint called")
    if not body.original_code or not body.original_code.strip():
        raise HTTPException(status_code=400, detail="original_code is required and cannot be empty")
    if not body.edit_instructions or not body.edit_instructions.strip():
        raise HTTPException(status_code=400, detail="edit_instructions is required and cannot be empty")

    provider = body.provider
    model = body.model
    if not provider:
        if body.keys.get("gemini"):
            provider = "gemini"
        elif body.keys.get("claude"):
            provider = "claude"
    if not model and provider == "gemini":
        model = "gemini-3-flash-preview"
    if not model and provider == "claude":
        model = "claude-haiku-4-5"
    logger.info("/edit using provider=%s model=%s", provider, model)

    key = body.keys.get(provider) if provider else None
    if not key:
        raise HTTPException(status_code=400, detail=f"Missing API key for '{provider}'")

    instructions_lower = body.edit_instructions.lower()
    wants_all = any(
        kw in instructions_lower
        for kw in ["all ", "every ", "throughout", "everywhere", "each ", "whole "]
    )
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

    edit_system = EDIT_SYSTEM
    edit_user = build_edit_user_prompt(
        original_code=body.original_code,
        edit_instructions=body.edit_instructions,
        wants_all=wants_all,
        wants_overlap_fix=wants_overlap_fix,
    )

    try:
        raw = call_llm(
            provider=provider,
            api_key=key,
            model=model,
            system=edit_system,
            user=edit_user,
            temperature=0.1,
        )
        code = None
        diff_applied = False
        diff_match = re.search(r"```diff\s*(.*?)```", raw, re.IGNORECASE | re.DOTALL)
        if diff_match:
            diff_text = diff_match.group(1).strip()
            code = _apply_unified_diff(body.original_code, diff_text, apply_all_matches=wants_all)
            if code and code != body.original_code:
                diff_applied = True
        if not diff_applied:
            code_match = re.search(r"```(?:python)?\s*(.*?)```", raw, re.IGNORECASE | re.DOTALL)
            if code_match:
                potential_code = code_match.group(1).strip()
                if "class " in potential_code and "def construct" in potential_code:
                    code = potential_code
            if not code and "class " in raw and "def construct" in raw:
                code = raw.strip()
        if not code:
            raise HTTPException(status_code=500, detail="Failed to generate code edit")

        code = sanitize_minimally(code)
        render_result = run_job_from_code(code)
        render_ok = render_result.get("ok", False) or render_result.get("render_ok", False)
        video_url = render_result.get("video_url")
        job_id = render_result.get("job_id") or body.jobId or "unknown"

        if render_ok and video_url:
            gcs_bucket = _get_bucket_name()
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
                    _upload_bytes(gcs_bucket, gcs_path, data, content_type)
                    signed_video_url = _sign_url(gcs_bucket, gcs_path)
                    saved_artifact_id = _save_artifact(
                        uid, body.chatId, "video", gcs_path, len(data), content_type, derived=False
                    )
                    vtt_local = p.with_suffix(".vtt")
                    if vtt_local.exists():
                        vtt_bytes = vtt_local.read_bytes()
                        vtt_path = f"{uid}/chats/{body.chatId or 'uncategorized'}/video_{job_id}.vtt"
                        _upload_bytes(gcs_bucket, vtt_path, vtt_bytes, "text/vtt")
                        signed_subtitle_url = _sign_url(gcs_bucket, vtt_path)
                    py_bytes = code.encode("utf-8")
                    py_path = f"{uid}/chats/{body.chatId or 'uncategorized'}/scene_{job_id}.py"
                    _upload_bytes(gcs_bucket, py_path, py_bytes, "text/x-python")
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
            error_detail = render_result.get("error") or render_result.get("stderr") or "Unknown render error"
            return {
                "ok": False,
                "status": "error",
                "error": "render_failed",
                "message": f"Edited video failed to render: {error_detail[:500]}",
                "video_url": None,
                "render_result": render_result,
            }
    except Exception as e:
        logger.exception("/edit failed with exception: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/quiz/embedded")
def quiz_embedded(body: QuizIn):
    try:
        provider = body.provider
        model = body.model
        if not provider:
            if body.keys.get("gemini"):
                provider = "gemini"
            elif body.keys.get("claude"):
                provider = "claude"
        if not model and provider == "gemini":
            model = "gemini-3-flash-preview"
        if not model and provider == "claude":
            model = "claude-haiku-4-5"
        quiz = _generate_quiz_embedded(
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
    try:
        transcript = body.get("transcript", "").strip()
        if not transcript:
            raise ValueError("Transcript from VTT captions is required")
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
            model = "gemini-3-flash-preview"
        if not model and provider == "claude":
            model = "claude-haiku-4-5"
        context = body.get("sceneCode")
        num_questions = body.get("num_questions", 5)
        difficulty = body.get("difficulty", "medium")
        media_prompt = (
            "Generate quiz questions based ONLY on the following content (from captions):\n\n"
            f"{transcript}"
        )
        quiz = _generate_quiz_embedded(
            prompt=media_prompt,
            num_questions=num_questions,
            difficulty=difficulty,
            provider=provider,
            model=model,
            provider_keys=provider_keys,
            context=context,
        )
        return {"status": "ok", "quiz": quiz}
    except Exception as e:
        logger.exception("/quiz/media failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/podcast")
def podcast(body: PodcastIn, uid: str = Depends(require_firebase_user)):
    try:
        provider = body.provider
        model = body.model
        if not provider:
            if body.keys.get("gemini"):
                provider = "gemini"
            elif body.keys.get("claude"):
                provider = "claude"
        if not model and provider == "gemini":
            model = "gemini-3-flash-preview"
        if not model and provider == "claude":
            model = "claude-haiku-4-5"
        result = _generate_podcast(
            prompt=body.prompt,
            provider=provider,
            model=model,
            provider_keys=body.keys,
            mode=body.mode or "standard",
            job_id=body.jobId,
        )

        gcs_bucket = _get_bucket_name()
        if gcs_bucket and result.get("video_url"):
            try:
                job_id = result.get("job_id", "unknown")
                relative_path = result["video_url"].replace("/static/", "")
                p = pathlib.Path(STORAGE) / relative_path
                if p.exists():
                    data = p.read_bytes()
                    content_type = mimetypes.guess_type(p.name)[0] or "audio/mpeg"
                    gcs_path = f"{uid}/chats/{body.chatId or 'uncategorized'}/podcast_{job_id}.mp3"
                    _upload_bytes(gcs_bucket, gcs_path, data, content_type)
                    result["signed_video_url"] = _sign_url(gcs_bucket, gcs_path)
                    result["gcs_path"] = gcs_path
                    saved_artifact_id = _save_artifact(
                        uid, body.chatId, "podcast", gcs_path, len(data), content_type, derived=False
                    )
                    result["artifact_id"] = saved_artifact_id
                    if result.get("script"):
                        script_bytes = result["script"].encode("utf-8")
                        chat_path = body.chatId or "uncategorized"
                        script_gcs_path = f"{uid}/chats/{chat_path}/podcast_{job_id}_script.txt"
                        _upload_bytes(gcs_bucket, script_gcs_path, script_bytes, "text/plain")
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
                    if result.get("vtt_url"):
                        vtt_relative = result["vtt_url"].replace("/static/", "")
                        vtt_path_local = pathlib.Path(STORAGE) / vtt_relative
                        if vtt_path_local.exists():
                            vtt_data = vtt_path_local.read_bytes()
                            chat_path = body.chatId or "uncategorized"
                            vtt_gcs_path = f"{uid}/chats/{chat_path}/podcast_{job_id}.vtt"
                            _upload_bytes(gcs_bucket, vtt_gcs_path, vtt_data, "text/vtt")
                            result["signed_subtitle_url"] = _sign_url(gcs_bucket, vtt_gcs_path)
                            _save_artifact(
                                uid,
                                body.chatId,
                                "subtitle",
                                vtt_gcs_path,
                                len(vtt_data),
                                "text/vtt",
                                derived=True,
                            )
                    if result.get("signed_video_url"):
                        try:
                            if p.exists():
                                p.unlink()
                            if result.get("signed_subtitle_url") and vtt_path_local.exists():
                                vtt_path_local.unlink()
                        except Exception as e:
                            logger.warning("Failed to clean up local podcast files: %s", e)
            except Exception as e:
                logger.warning("GCS podcast upload failed: %s", e)
                if gcs_bucket:
                    raise HTTPException(
                        status_code=500,
                        detail="Podcast generated but GCS upload failed. Please try again.",
                    ) from e
        else:
            if result.get("vtt_url"):
                result["signed_subtitle_url"] = result["vtt_url"]

        if gcs_bucket:
            if not result.get("signed_video_url"):
                raise HTTPException(
                    status_code=500,
                    detail="GCS bucket configured but upload failed. Please try again.",
                )
            result["video_url"] = result["signed_video_url"]

        return result
    except Exception as e:
        logger.exception("/podcast failed: %s", e)
        msg = str(e) if str(e) else f"{type(e).__name__}"
        raise HTTPException(status_code=500, detail=msg) from e


@app.post("/widget")
def widget(body: WidgetIn, uid: str = Depends(require_firebase_user)):
    """Generate a self-contained interactive HTML widget. Returns { ok, status, widget_html }."""
    provider = body.provider
    model = body.model
    if not provider:
        if body.keys.get("gemini"):
            provider = "gemini"
        elif body.keys.get("claude"):
            provider = "claude"
    if not model and provider == "gemini":
        model = "gemini-3-flash-preview"
    if not model and provider == "claude":
        model = "claude-haiku-4-5"

    logger.info("/widget called provider=%s model=%s", provider, model)
    try:
        result = _generate_widget(
            prompt=body.prompt,
            provider=provider,
            model=model,
            provider_keys=body.keys,
        )
        logger.info("/widget completed: ok, html_len=%d", len(result.get("widget_html", "")))
        return {"ok": True, "status": "ok", "widget_html": result["widget_html"]}
    except Exception as e:
        logger.exception("/widget failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


def _chat_doc(uid: str, chat_id: str):
    return _get_db().collection("users").document(uid).collection("chats").document(chat_id)


def _paginate_messages(
    chat_id: str, uid: str, limit: int, before_ms: int | None
) -> tuple[list[MessageOut], bool]:
    if DESKTOP_LOCAL_MODE:
        chat = _desktop_chat(uid, chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")
        messages = list(chat.get("messages", []))
        if before_ms is not None:
            messages = [m for m in messages if int(m.get("createdAt", 0) or 0) < before_ms]
        messages.sort(key=lambda m: int(m.get("createdAt", 0) or 0))
        has_more = len(messages) > limit
        if has_more:
            messages = messages[-limit:]
        out = [
            MessageOut(
                message_id=str(m.get("message_id")),
                role=m.get("role", "assistant"),
                content=m.get("content", ""),
                createdAt=int(m.get("createdAt", 0) or 0),
                media=m.get("media"),
                quizAnchor=m.get("quizAnchor"),
                quizTitle=m.get("quizTitle"),
                quizData=m.get("quizData"),
            )
            for m in messages
        ]
        return out, has_more

    msgs_ref = _chat_doc(uid, chat_id).collection("messages")
    if before_ms:
        q = (
            msgs_ref.order_by("createdAt", direction=gcf.Query.DESCENDING)
            .where("createdAt", "<", gcf.Timestamp(before_ms // 1000, (before_ms % 1000) * 1_000_000))
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


def get_chat(chat_id: str, uid: str, limit: int = 200, before_ms: int | None = None):
    if DESKTOP_LOCAL_MODE:
        chat = _desktop_chat(uid, chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")
        msgs, _ = _paginate_messages(chat_id, uid, limit=limit, before_ms=before_ms)
        return ChatDetailOut(
            chat_id=chat_id,
            title=chat.get("title", "Untitled"),
            dts=int(chat.get("updatedAt", 0) or 0),
            sessionId=chat.get("sessionId"),
            messages=msgs,
            shareable=bool(chat.get("shareable", False)),
            share_token=chat.get("shareToken"),
            model=chat.get("model"),
        )

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
        model=chat_data.get("model"),
    )


def append_message(chat_id: str, body: MessageCreateIn, uid: str):
    if DESKTOP_LOCAL_MODE:
        chat = _desktop_chat(uid, chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")
        now_ms = _now_ms()
        message_id = body.message_id or uuid4().hex[:16]
        media_dict = None
        if body.media is not None:
            try:
                media_dict = body.media.dict(exclude_none=True)
            except Exception:
                media_dict = None
        payload = {
            "message_id": message_id,
            "role": body.role,
            "content": body.content,
            "createdAt": now_ms,
            "media": media_dict,
            "quizAnchor": body.quizAnchor,
            "quizTitle": body.quizTitle,
            "quizData": body.quizData,
        }
        messages = chat.setdefault("messages", [])
        existing_idx = next(
            (i for i, m in enumerate(messages) if m.get("message_id") == message_id), -1
        )
        if existing_idx >= 0:
            messages[existing_idx] = payload
        else:
            messages.append(payload)
        chat["updatedAt"] = now_ms
        _save_desktop_store()
        return MessageOut(
            message_id=message_id,
            role=body.role,
            content=body.content,
            createdAt=now_ms,
            media=media_dict,
            quizAnchor=body.quizAnchor,
            quizTitle=body.quizTitle,
            quizData=body.quizData,
        )

    chat_ref = _chat_doc(uid, chat_id)
    if not chat_ref.get().exists:
        raise HTTPException(status_code=404, detail="Chat not found")
    _get_db()
    msg_ref = (
        chat_ref.collection("messages").document(body.message_id)
        if body.message_id
        else chat_ref.collection("messages").document()
    )
    existing = msg_ref.get()
    now = gcf.SERVER_TIMESTAMP
    data_to_set = {"role": body.role, "content": body.content, "createdAt": now}
    if body.media is not None:
        try:
            media_dict = body.media.dict(exclude_none=True)
        except Exception:
            media_dict = None
        if media_dict:
            data_to_set["media"] = media_dict
    if body.quizAnchor is not None:
        data_to_set["quizAnchor"] = body.quizAnchor
    if body.quizTitle is not None:
        data_to_set["quizTitle"] = body.quizTitle
    if body.quizData is not None:
        data_to_set["quizData"] = body.quizData
    if existing.exists:
        try:
            msg_ref.update({k: v for k, v in data_to_set.items() if k != "createdAt"})
        except Exception:
            pass
    else:
        msg_ref.set(data_to_set)
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
    if DESKTOP_LOCAL_MODE:
        chats = list(_desktop_user(uid)["chats"].items())
        chats.sort(key=lambda it: int(it[1].get("updatedAt", 0) or 0), reverse=True)
        out: list[ChatItemOut] = []
        for chat_id, data in chats[:limit]:
            out.append(
                ChatItemOut(
                    chat_id=chat_id,
                    title=data.get("title", "Untitled"),
                    dts=int(data.get("updatedAt", 0) or 0),
                    sessionId=data.get("sessionId"),
                    shareable=bool(data.get("shareable", False)),
                    share_token=data.get("shareToken"),
                )
            )
        return out

    db = _get_db()
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
    if DESKTOP_LOCAL_MODE:
        chat_id = uuid4().hex[:16]
        now_ms = _now_ms()
        shareable = bool(body.shareable)
        share_token = body.share_token if shareable else None
        _desktop_user(uid)["chats"][chat_id] = {
            "title": body.title or "New Chat",
            "model": body.model or None,
            "sessionId": body.sessionId or None,
            "createdAt": now_ms,
            "updatedAt": now_ms,
            "shareable": shareable,
            "shareToken": share_token,
            "messages": [],
        }
        _save_desktop_store()
        return ChatItemOut(
            chat_id=chat_id,
            title=body.title or "New Chat",
            dts=now_ms,
            sessionId=body.sessionId,
            shareable=shareable,
            share_token=share_token,
        )

    db = _get_db()
    chat_ref = db.collection("users").document(uid).collection("chats").document()
    now = gcf.SERVER_TIMESTAMP
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
    if DESKTOP_LOCAL_MODE:
        return ArtifactRefreshOut(ok=True, artifact_id=artifactId, gcs_path=gcsPath)
    gcs_bucket = _get_bucket_name()
    if not gcs_bucket:
        raise HTTPException(status_code=400, detail="No GCS bucket configured")
    path = gcsPath
    if artifactId and not path:
        try:
            db = _get_db()
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
            raise HTTPException(status_code=500, detail="Artifact lookup failed") from e
    if not path:
        raise HTTPException(status_code=400, detail="Missing artifactId or gcsPath")
    try:
        signed_main = _sign_url(gcs_bucket, path)
        signed_sub = None
        if subtitle:
            base, ext = os.path.splitext(path)
            vtt_path = base + ".vtt"
            signed_sub = _sign_url(gcs_bucket, vtt_path)
        return ArtifactRefreshOut(
            ok=True,
            signed_video_url=signed_main,
            signed_subtitle_url=signed_sub,
            gcs_path=path,
            artifact_id=artifactId,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail="Refresh failed") from e


def list_messages(chat_id: str, uid: str, limit: int = 50, before_ms: int | None = None):
    if DESKTOP_LOCAL_MODE:
        chat = _desktop_chat(uid, chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")
        msgs, has_more = _paginate_messages(chat_id, uid, limit=limit, before_ms=before_ms)
        return MessagesPage(messages=msgs, has_more=has_more)

    chat_snap = _chat_doc(uid, chat_id).get()
    if not chat_snap.exists:
        raise HTTPException(status_code=404, detail="Chat not found")
    msgs, has_more = _paginate_messages(chat_id, uid, limit=limit, before_ms=before_ms)
    return MessagesPage(messages=msgs, has_more=has_more)


@app.get("/api/chats/{chat_id}/export")
def export_chat(chat_id: str, uid: str = Depends(require_firebase_user)):
    if DESKTOP_LOCAL_MODE:
        chat = _desktop_chat(uid, chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")
        messages = sorted(
            list(chat.get("messages", [])),
            key=lambda m: int(m.get("createdAt", 0) or 0),
        )
        msgs = [
            {
                "message_id": str(m.get("message_id")),
                "role": m.get("role"),
                "content": m.get("content"),
                "createdAt": int(m.get("createdAt", 0) or 0),
                "media": m.get("media") or None,
            }
            for m in messages
        ]
        return {
            "chat": {
                "chat_id": chat_id,
                "title": chat.get("title", "Untitled"),
                "createdAt": int(chat.get("createdAt", 0) or 0),
                "updatedAt": int(chat.get("updatedAt", 0) or 0),
            },
            "messages": msgs,
            "version": 1,
        }

    chat_snap = _chat_doc(uid, chat_id).get()
    if not chat_snap.exists:
        raise HTTPException(status_code=404, detail="Chat not found")
    chat_data = chat_snap.to_dict() or {}
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
    return {
        "chat": {
            "chat_id": chat_id,
            "title": chat_data.get("title", "Untitled"),
            "createdAt": _to_ms(chat_data.get("createdAt")),
            "updatedAt": _to_ms(chat_data.get("updatedAt")),
        },
        "messages": msgs,
        "version": 1,
    }


class ChatRenameIn(BaseModel):
    title: str


class ChatShareToggleIn(BaseModel):
    shareable: bool


def rename_chat(chat_id: str, body: ChatRenameIn, uid: str):
    if DESKTOP_LOCAL_MODE:
        chat = _desktop_chat(uid, chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")
        chat["title"] = body.title
        chat["updatedAt"] = _now_ms()
        _save_desktop_store()
        return ChatItemOut(
            chat_id=chat_id,
            title=chat["title"],
            dts=chat["updatedAt"],
            sessionId=chat.get("sessionId"),
            shareable=bool(chat.get("shareable", False)),
            share_token=chat.get("shareToken"),
        )

    chat_ref = _chat_doc(uid, chat_id)
    snap = chat_ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Chat not found")
    now = gcf.SERVER_TIMESTAMP
    chat_ref.update({"title": body.title, "updatedAt": now})
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
def toggle_share(
    chat_id: str,
    body: ChatShareToggleIn,
    uid: str = Depends(require_firebase_user),
):
    if DESKTOP_LOCAL_MODE:
        chat = _desktop_chat(uid, chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")
        shareable = bool(body.shareable)
        share_token = chat.get("shareToken")
        if shareable and not share_token:
            share_token = uuid4().hex[:16]
        chat["shareable"] = shareable
        chat["shareToken"] = share_token
        chat["updatedAt"] = _now_ms()
        _save_desktop_store()
        return ChatItemOut(
            chat_id=chat_id,
            title=chat.get("title", "Untitled"),
            dts=chat.get("updatedAt"),
            sessionId=chat.get("sessionId"),
            shareable=shareable,
            share_token=share_token,
        )

    chat_ref = _chat_doc(uid, chat_id)
    snap = chat_ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Chat not found")
    data = snap.to_dict() or {}
    now = gcf.SERVER_TIMESTAMP
    shareable = bool(body.shareable)
    share_token = data.get("shareToken")
    if shareable and not share_token:
        share_token = uuid4().hex[:16]
    chat_ref.update({"shareable": shareable, "shareToken": share_token, "updatedAt": now})
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
    if DESKTOP_LOCAL_MODE:
        for _uid, user_data in _DESKTOP_STORE.items():
            for chat_id, chat in user_data.get("chats", {}).items():
                if chat.get("shareable") and chat.get("shareToken") == token:
                    msgs = [
                        MessageOut(
                            message_id=str(m.get("message_id")),
                            role=m.get("role", "assistant"),
                            content=m.get("content", ""),
                            createdAt=int(m.get("createdAt", 0) or 0),
                            media=m.get("media"),
                            quizAnchor=m.get("quizAnchor"),
                            quizTitle=m.get("quizTitle"),
                            quizData=m.get("quizData"),
                        )
                        for m in chat.get("messages", [])[:limit]
                    ]
                    return ChatDetailOut(
                        chat_id=chat_id,
                        title=chat.get("title", "Untitled"),
                        dts=int(chat.get("updatedAt", 0) or 0),
                        sessionId=chat.get("sessionId"),
                        messages=msgs,
                        shareable=True,
                        share_token=token,
                        model=chat.get("model"),
                    )
        raise HTTPException(status_code=404, detail="Shared chat not found")

    db = _get_db()
    try:
        q = db.collection_group("chats").where("shareToken", "==", token).limit(1)
        docs = list(q.stream())
    except Exception as e:
        raise HTTPException(status_code=500, detail="Share lookup failed") from e
    if not docs:
        raise HTTPException(status_code=404, detail="Shared chat not found")
    doc = docs[0]
    chat_data = doc.to_dict() or {}
    if not chat_data.get("shareable"):
        raise HTTPException(status_code=404, detail="Shared chat not found")
    chat_id = doc.id
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
        sessionId=chat_data.get("sessionId"),
        messages=msgs,
        shareable=True,
        share_token=token,
        model=chat_data.get("model"),
    )


@app.get("/api/chats", response_model=list[ChatItemOut])
def list_chats_route(
    limit: int = Query(50, ge=1, le=200), uid: str = Depends(require_firebase_user)
):
    return list_chats(uid, limit)


@app.post("/api/chats", response_model=ChatItemOut)
def create_chat_route(
    body: ChatCreateIn,
    uid: str = Depends(require_firebase_user),
    x_session_id: str | None = Header(None, alias="X-Session-ID"),
):
    if x_session_id and not body.sessionId:
        body.sessionId = x_session_id
    if body.content:
        result = create_chat(body, uid)
        try:
            msg_body = MessageCreateIn(role="user", content=body.content)
            append_message(result.chat_id, msg_body, uid)
        except Exception:
            pass
        return result
    return create_chat(body, uid)


@app.get("/api/chats/{chat_id}", response_model=ChatDetailOut)
def get_chat_route(
    chat_id: str,
    uid: str = Depends(require_firebase_user),
    limit: int = Query(200, ge=1, le=500),
    before: int | None = Query(None),
):
    return get_chat(chat_id, uid, limit, before)


@app.post("/api/chats/{chat_id}", response_model=ChatDetailOut)
def continue_chat_route(
    chat_id: str,
    body: MessageCreateIn,
    uid: str = Depends(require_firebase_user),
    x_session_id: str | None = Header(None, alias="X-Session-ID"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    if idempotency_key and not body.message_id:
        body.message_id = idempotency_key
    append_message(chat_id, body, uid)
    return get_chat(chat_id, uid, limit=200, before_ms=None)


@app.get("/api/chats/{chat_id}/messages", response_model=MessagesPage)
def list_messages_route(
    chat_id: str,
    uid: str = Depends(require_firebase_user),
    limit: int = Query(50, ge=1, le=200),
    before: int | None = Query(None),
):
    return list_messages(chat_id, uid, limit, before)


@app.patch("/api/chats/{chat_id}", response_model=ChatItemOut)
def rename_chat_route(chat_id: str, body: ChatRenameIn, uid: str = Depends(require_firebase_user)):
    return rename_chat(chat_id, body, uid)


@app.delete("/api/chats/{chat_id}")
def delete_chat_route(chat_id: str, uid: str = Depends(require_firebase_user)):
    return _delete_chat_impl(chat_id, uid)


@app.delete("/api/account")
def delete_account_route(uid: str = Depends(require_firebase_user)):
    return _delete_account_impl(uid)


def _delete_chat_impl(chat_id: str, uid: str):
    if DESKTOP_LOCAL_MODE:
        user = _desktop_user(uid)
        chat = user["chats"].pop(chat_id, None)
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")
        _save_desktop_store()
        return {
            "ok": True,
            "deleted": chat_id,
            "messages_removed": len(chat.get("messages", [])),
            "gcs_files_removed": 0,
        }

    chat_ref = _chat_doc(uid, chat_id)
    snap = chat_ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Chat not found")
    db = _get_db()
    batch = db.batch()
    msgs = chat_ref.collection("messages").stream()
    count = 0
    for m in msgs:
        batch.delete(m.reference)
        count += 1
    batch.delete(chat_ref)
    batch.commit()
    gcs_bucket = _get_bucket_name()
    gcs_deleted = 0
    if gcs_bucket:
        try:
            gcs_deleted = _delete_folder(gcs_bucket, f"{uid}/chats/{chat_id}/")
        except Exception as e:
            logger.warning("Failed to delete GCS folder for chat %s: %s", chat_id, e)
    return {
        "ok": True,
        "deleted": chat_id,
        "messages_removed": count,
        "gcs_files_removed": gcs_deleted,
    }


def _delete_account_impl(uid: str):
    if DESKTOP_LOCAL_MODE:
        user = _DESKTOP_STORE.pop(uid, {"chats": {}})
        chats = list(user.get("chats", {}).values())
        _save_desktop_store()
        return {
            "ok": True,
            "uid": uid,
            "chats_removed": len(chats),
            "messages_removed": sum(len(c.get("messages", [])) for c in chats),
            "artifacts_removed": 0,
            "gcs_files_removed": 0,
        }

    db = _get_db()

    def delete_collection(coll_ref, batch_size=500):
        deleted = 0
        docs = coll_ref.limit(batch_size).stream()
        deleted_batch = 0
        for doc in docs:
            doc.reference.delete()
            deleted += 1
            deleted_batch += 1
        if deleted_batch >= batch_size:
            return deleted + delete_collection(coll_ref, batch_size)
        return deleted

    total_chats = 0
    total_messages = 0
    total_artifacts = 0
    total_gcs_files = 0
    chats_ref = db.collection("users").document(uid).collection("chats")
    chats = list(chats_ref.stream())
    for chat in chats:
        msg_count = delete_collection(chat.reference.collection("messages"))
        total_messages += msg_count
        chat.reference.delete()
        total_chats += 1
    artifacts_ref = db.collection("users").document(uid).collection("artifacts")
    total_artifacts = delete_collection(artifacts_ref)
    gcs_bucket = _get_bucket_name()
    if gcs_bucket:
        try:
            total_gcs_files = _delete_folder(gcs_bucket, f"{uid}/")
            _delete_folder(gcs_bucket, f"{uid}/chats/")
        except Exception as e:
            logger.warning("Failed to delete GCS folder for user %s: %s", uid, e)
    try:
        user_ref = db.collection("users").document(uid)
        user_doc = user_ref.get()
        if user_doc.exists:
            user_ref.delete()
    except Exception as e:
        logger.error("Failed to delete Firestore user document for %s: %s", uid, e)
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
        if isinstance(ts, (int, float)):
            return int(ts)
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
        res = cancel_job(jobId)
        return res
    except Exception as e:
        logger.exception("/jobs/cancel failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e
