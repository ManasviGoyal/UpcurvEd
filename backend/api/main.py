# backend/api/main.py
import json
import logging
import mimetypes
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from typing import Literal
from urllib.parse import urlparse
from uuid import uuid4

import requests
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.agent.llm.clients import call_llm, track_llm_calls
from backend.agent.llm.multimodal import (
    MAX_GENERATION_IMAGES,
    resolve_effective_learner_prompt,
)
from backend.agent.llm.provider_config import (
    ProviderName,
    get_provider_key as _get_provider_key,
    merge_provider_keys as _provider_keys_with_env,
    resolve_provider_model as _resolve_provider_model,
)
from backend.agent.minigraph import echo_manim_code
from backend.agent.prompts import (
    STORY_EDIT_FULL_HTML_SYSTEM,
    STORY_EDIT_PATCH_SYSTEM,
    build_story_edit_full_html_user_prompt,
    build_story_edit_patch_user_prompt,
)
from backend.runner.job_runner import STORAGE, cancel_job, run_job_from_code, to_static_url
from backend.utils import app_logging  # noqa: F401
from backend.utils.diagnostics import diagnostic_error_response, diagnostic_payload
from backend.utils.failure_log import append_generation_audit, summarize_error
from backend.utils.html_exports import (
    build_quiz_html,
    make_download_filename,
    safe_job_id,
    save_html_file,
)

logger = logging.getLogger(f"app.{__name__}")
APP_MODE = os.environ.get("APP_MODE", "cloud").strip().lower()
DESKTOP_LOCAL_MODE = APP_MODE == "desktop-local"

AudienceLevel = Literal[
    "auto",
    "early_learning",
    "elementary",
    "middle_school",
    "high_school",
    "university",
]

_AUDIENCE_GUIDANCE: dict[str, str] = {
    "early_learning": (
        "Target audience: Early learning learners. Use very simple, concrete language, short "
        "sentences, familiar examples, playful repetition, and one idea at a time."
    ),
    "elementary": (
        "Target audience: Elementary learners. Use clear, concrete language, short explanations, "
        "and relatable examples. Introduce ideas step by step and avoid unnecessary abstraction."
    ),
    "middle_school": (
        "Target audience: Middle school learners. Use clear language, scaffold multi-step ideas, "
        "define key terms, and connect concepts to practical examples."
    ),
    "high_school": (
        "Target audience: High school learners. Use age-appropriate vocabulary, structured "
        "reasoning, and enough technical detail to support understanding without being overwhelming."
    ),
    "university": (
        "Target audience: University learners. Use precise academic terminology, explain "
        "important assumptions, include appropriate mathematical or technical depth, and "
        "assume a solid introductory foundation unless the topic says otherwise."
    ),
}


def _normalize_audience(audience: object | None) -> str | None:
    """Normalize the supported learner-level values and ignore unsupported input."""
    if audience is None:
        return None

    value = str(audience).strip().lower()
    if not value or value in {"auto", "none"}:
        return None
    if value in _AUDIENCE_GUIDANCE:
        return value
    return None


def _with_audience_guidance(text: str, audience: object | None) -> str:
    """Attach trusted learner-level guidance without changing the saved user prompt."""
    normalized = _normalize_audience(audience)
    if not normalized:
        return text

    guidance = _AUDIENCE_GUIDANCE.get(normalized)
    if not guidance:
        return text
    return (
        f"{text.rstrip()}\n\n"
        "<LEARNER_LEVEL_REQUIREMENTS>\n"
        f"{guidance}\n"
        "Keep the material factually complete for the topic while adapting its vocabulary, "
        "examples, pacing, visuals, interactions, and assessment difficulty to this audience.\n"
        "</LEARNER_LEVEL_REQUIREMENTS>"
    )

try:
    from google.cloud import firestore as gcf  # type: ignore
except Exception:  # pragma: no cover
    gcf = None

_DESKTOP_STORE: dict[str, dict] = {}
_DESKTOP_STATE_DIR = pathlib.Path(
    os.environ.get("UPCURVED_DESKTOP_STATE_DIR", ".desktop-state")
)
_DESKTOP_STATE_FILE = _DESKTOP_STATE_DIR / "desktop_store.json"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _generation_job_id(value: object | None) -> str:
    return safe_job_id(str(value or uuid4().hex[:12]))


def _append_artifact_generation_audit(
    *,
    generation_type: str,
    job_id: str,
    operation: str,
    outcome: str,
    provider: str | None,
    model: str | None,
    llm_calls: int,
    started_monotonic: float,
    failure_stage: str | None = None,
    error_summary: object | None = None,
) -> None:
    try:
        append_generation_audit(
            {
                "type": generation_type,
                "job_id": job_id,
                "operation": operation,
                "outcome": outcome,
                "provider": provider,
                "model": model,
                "llm_calls": max(0, int(llm_calls)),
                "failure_stage": failure_stage,
                "error_summary": (
                    summarize_error(error_summary) if error_summary else None
                ),
                "duration_seconds": max(
                    0.0, time.monotonic() - started_monotonic
                ),
            }
        )
    except Exception as exc:
        logger.warning(
            "generation_audit_append_failed type=%s job_id=%s error=%s",
            generation_type,
            job_id,
            exc,
        )


def _safe_client_created_at(value: object, fallback_ms: int) -> int:
    """Return a stable client creation time without trusting extreme values."""
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except Exception:
        return fallback_ms
    max_future_skew_ms = 24 * 60 * 60 * 1000
    if parsed <= 0 or parsed > fallback_ms + max_future_skew_ms:
        return fallback_ms
    return parsed


def _safe_message_sequence(
    value: object,
    client_created_at: int,
) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
        if parsed >= 0:
            return parsed
    except Exception:
        pass
    return client_created_at * 1000


def _stored_message_sort_key(message: dict) -> tuple[int, int, str]:
    return (
        int(message.get("createdAt", 0) or 0),
        int(message.get("sequence", 0) or 0),
        str(message.get("message_id") or ""),
    )


def _desktop_user(uid: str) -> dict:
    return _DESKTOP_STORE.setdefault(uid, {"chats": {}})


def _desktop_chat(uid: str, chat_id: str) -> dict | None:
    return _desktop_user(uid)["chats"].get(chat_id)


def _normalize_desktop_messages(messages: object) -> list[dict]:
    """Backfill stable IDs/order metadata for legacy desktop chat records."""
    if not isinstance(messages, list):
        return []
    normalized: list[dict] = []
    fallback_base = _now_ms()
    for index, value in enumerate(messages):
        if not isinstance(value, dict):
            continue
        message = dict(value)
        created_at = int(message.get("createdAt", 0) or 0)
        if created_at <= 0:
            created_at = fallback_base + index
            message["createdAt"] = created_at
        client_created_at = int(
            message.get("clientCreatedAt", 0) or 0
        ) or created_at
        message["clientCreatedAt"] = client_created_at
        message["sequence"] = int(message.get("sequence", 0) or 0) or (
            client_created_at * 1000 + index
        )
        message["message_id"] = str(
            message.get("message_id")
            or f"legacy-{created_at}-{index}"
        )
        normalized.append(message)
    return normalized


def _normalize_desktop_store(raw: dict | None) -> dict[str, dict]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict] = {}
    for uid, user_data in raw.items():
        if not isinstance(uid, str):
            continue
        chats: dict[str, dict] = {}
        if isinstance(user_data, dict):
            chats_in = user_data.get("chats", {})
            if isinstance(chats_in, dict):
                for chat_id, value in chats_in.items():
                    if not isinstance(chat_id, str) or not isinstance(value, dict):
                        continue
                    chat = dict(value)
                    chat["messages"] = _normalize_desktop_messages(
                        chat.get("messages", [])
                    )
                    chats[chat_id] = chat
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
        normalized = _normalize_desktop_store(data)
        _DESKTOP_STORE = normalized
        if normalized != data:
            _save_desktop_store()
    except Exception as exc:
        logger.warning(
            "Failed to load desktop state from %s: %s",
            _DESKTOP_STATE_FILE,
            exc,
        )
        _DESKTOP_STORE = {}


def _save_desktop_store() -> None:
    if not DESKTOP_LOCAL_MODE:
        return
    try:
        _DESKTOP_STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _DESKTOP_STATE_FILE.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(_DESKTOP_STORE, ensure_ascii=True),
            encoding="utf-8",
        )
        tmp.replace(_DESKTOP_STATE_FILE)
    except Exception as exc:
        logger.warning(
            "Failed to persist desktop state to %s: %s",
            _DESKTOP_STATE_FILE,
            exc,
        )


if DESKTOP_LOCAL_MODE:
    _load_desktop_store()


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


def _edit_widget(*args, **kwargs):
    from backend.mcp.widget_logic import edit_widget as _impl

    return _impl(*args, **kwargs)


def _edit_quiz_embedded(*args, **kwargs):
    from backend.mcp.quiz_logic import edit_quiz_embedded as _impl

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
            safe = re.sub(
                r"[^a-zA-Z0-9._-]",
                "_",
                x_desktop_user.strip(),
            )[:128]
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
    except Exception as exc:
        logger.warning("Auth failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid token") from exc


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
_all_origins = _DEFAULT_ORIGINS + [
    origin.strip()
    for origin in _extra_origins.split(",")
    if origin.strip()
]

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


class GenerationImageIn(BaseModel):
    dataUrl: str
    mimeType: Literal["image/png", "image/jpeg", "image/webp"]
    name: str | None = None


def _generation_image_payload(images: list[GenerationImageIn]) -> list[dict[str, str]]:
    if len(images) > MAX_GENERATION_IMAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Up to {MAX_GENERATION_IMAGES} images can be attached to one generation.",
        )
    return [
        {
            "data_url": image.dataUrl,
            "mime_type": image.mimeType,
            "name": image.name or f"image_{index}",
        }
        for index, image in enumerate(images, start=1)
    ]


class GenerateIn(BaseModel):
    prompt: str
    images: list[GenerationImageIn] = Field(default_factory=list)
    keys: dict[str, str] = {}
    provider: ProviderName | None = None
    model: str | None = None
    mode: Literal["standard", "story"] | None = "standard"
    audience: str | None = "auto"
    storyOptions: dict | None = None
    jobId: str | None = None
    chatId: str | None = None
    sessionId: str | None = None


class QuizIn(BaseModel):
    prompt: str
    images: list[GenerationImageIn] = Field(default_factory=list)
    num_questions: int = 5
    difficulty: Literal["easy", "medium", "hard"] | None = "medium"
    keys: dict[str, str] = {}
    provider: ProviderName | None = None
    model: str | None = None
    context: str | None = None
    audience: str | None = "auto"
    userEmail: str | None = None
    jobId: str | None = None
    chatId: str | None = None
    sessionId: str | None = None


class PodcastIn(BaseModel):
    prompt: str
    images: list[GenerationImageIn] = Field(default_factory=list)
    keys: dict[str, str] = {}
    provider: ProviderName | None = None
    model: str | None = None
    mode: Literal["standard", "debate"] | None = "standard"
    audience: str | None = "auto"
    jobId: str | None = None
    chatId: str | None = None
    sessionId: str | None = None


class WidgetIn(BaseModel):
    prompt: str
    images: list[GenerationImageIn] = Field(default_factory=list)
    keys: dict[str, str] = {}
    provider: ProviderName | None = None
    model: str | None = None
    audience: str | None = "auto"
    jobId: str | None = None
    chatId: str | None = None
    sessionId: str | None = None


class EditVideoIn(BaseModel):
    original_code: str
    edit_instructions: str
    keys: dict[str, str] = {}
    provider: ProviderName | None = None
    model: str | None = None
    audience: str | None = "auto"
    jobId: str | None = None
    chatId: str | None = None
    sessionId: str | None = None


class EditWidgetIn(BaseModel):
    original_html: str
    edit_instructions: str
    original_title: str | None = None
    keys: dict[str, str] = {}
    provider: ProviderName | None = None
    model: str | None = None
    audience: str | None = "auto"
    jobId: str | None = None
    chatId: str | None = None
    sessionId: str | None = None


class EditStoryIn(BaseModel):
    original_html: str
    edit_instructions: str
    original_title: str | None = None
    keys: dict[str, str] = {}
    provider: ProviderName | None = None
    model: str | None = None
    storyOptions: dict | None = None
    audience: str | None = "auto"
    jobId: str | None = None
    chatId: str | None = None
    sessionId: str | None = None


class EditQuizIn(BaseModel):
    original_quiz: dict
    edit_instructions: str
    num_questions: int | None = None
    difficulty: Literal["easy", "medium", "hard"] | None = "medium"
    keys: dict[str, str] = {}
    provider: ProviderName | None = None
    model: str | None = None
    audience: str | None = "auto"
    jobId: str | None = None
    chatId: str | None = None
    sessionId: str | None = None


class BurnCaptionsIn(BaseModel):
    video_url: str
    subtitle_url: str | None = None
    subtitle_text: str | None = None
    filename: str | None = None
    artifactId: str | None = None
    gcsPath: str | None = None
    chatId: str | None = None


class AudioPackageIn(BaseModel):
    audio_url: str
    subtitle_url: str | None = None
    subtitle_text: str | None = None
    filename: str | None = None
    artifactId: str | None = None
    gcsPath: str | None = None
    chatId: str | None = None


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
    artifactKind: str | None = None
    downloadFilename: str | None = None
    generationDiagnostics: dict | None = None


class MessageCreateIn(BaseModel):
    message_id: str | None = None
    role: Literal["user", "assistant"]
    content: str
    media: MessageMedia | None = None
    clientCreatedAt: int | None = None
    sequence: int | None = None
    quizAnchor: bool | None = None
    quizTitle: str | None = None
    quizData: dict | None = None


class MessageOut(BaseModel):
    message_id: str
    role: Literal["user", "assistant"]
    content: str
    createdAt: int | None = None
    clientCreatedAt: int | None = None
    sequence: int | None = None
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
    # platform/interpreter let a desktop shell tell its own backend apart from an
    # unrelated one already holding the port. WSL2 mirrors localhost into Windows, so a
    # `desktop:dev` backend in WSL is otherwise indistinguishable from the installed
    # Windows app's own bundled runtime.
    return {
        "ok": True,
        "mode": APP_MODE,
        "platform": sys.platform,
        "interpreter": sys.executable,
        "pid": os.getpid(),
    }


@app.get("/diagnostics/generation-export")
def export_generation_diagnostics(
    _uid: str = Depends(require_firebase_user),
):
    """Download a privacy-safe local generation audit and aggregate summary."""
    if not DESKTOP_LOCAL_MODE:
        raise HTTPException(status_code=404, detail="Not available")
    try:
        from backend.utils.failure_log import build_generation_export

        export_path = build_generation_export()
        return FileResponse(
            path=str(export_path),
            media_type="application/zip",
            filename=export_path.name,
        )
    except Exception as exc:
        logger.exception("generation diagnostics export failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Could not export generation diagnostics.",
        ) from exc


@app.post("/echo")
def echo(body: GenerateIn):
    logger.info("/echo called")
    code = echo_manim_code(body.prompt)
    result = run_job_from_code(code)
    logger.info("/echo completed: %s", result.get("status"))
    return result


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
        doc = (
            db.collection("users")
            .document(uid)
            .collection("artifacts")
            .document()
        )
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
    except Exception as exc:
        logger.warning("save artifact failed: %s", exc)
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
            body.append(
                re.sub(
                    r"(\d\d:\d\d:\d\d),(\d\d\d)",
                    r"\1.\2",
                    line,
                )
            )
        return "WEBVTT\n\n" + "\n".join(body) + "\n"


def _html_download_payload(
    *,
    uid: str,
    chat_id: str | None,
    kind: str,
    title: str | None,
    html_text: str,
    job_id: str | None = None,
) -> dict:
    """Save a self-contained HTML artifact and return download metadata."""
    jid = safe_job_id(job_id)
    filename = make_download_filename(kind, title)
    data = html_text.encode("utf-8")
    content_type = "text/html; charset=utf-8"
    gcs_bucket = _get_bucket_name()

    if gcs_bucket:
        chat_path = chat_id or "uncategorized"
        gcs_path = f"{uid}/chats/{chat_path}/exports/{jid}_{filename}"
        _upload_bytes(gcs_bucket, gcs_path, data, content_type)
        artifact_id = _save_artifact(
            uid,
            chat_id,
            kind,
            gcs_path,
            len(data),
            content_type,
            derived=True,
        )
        return {
            "download_url": _sign_url(gcs_bucket, gcs_path),
            "download_filename": filename,
            "download_artifact_id": artifact_id,
            "download_gcs_path": gcs_path,
        }

    local_path = save_html_file(jid, filename, html_text)
    return {
        "download_url": to_static_url(local_path),
        "download_filename": filename,
        "download_artifact_id": None,
        "download_gcs_path": None,
    }


def _find_ffmpeg_bin() -> str:
    for key in (
        "UPCURVED_FFMPEG_PATH",
        "IMAGEIO_FFMPEG_EXE",
        "FFMPEG_BINARY",
    ):
        value = (os.environ.get(key) or "").strip()
        if value and pathlib.Path(value).exists():
            return value

    found = shutil.which("ffmpeg")
    if found:
        return found

    raise RuntimeError(
        "ffmpeg not found. Set UPCURVED_FFMPEG_PATH or install ffmpeg."
    )


def _static_url_to_path(url: str) -> pathlib.Path | None:
    try:
        parsed = urlparse(url)
        path = parsed.path if parsed.scheme else url
        if path.startswith("/static/"):
            candidate = pathlib.Path(STORAGE) / path.replace("/static/", "", 1)
            if candidate.exists():
                return candidate
    except Exception:
        return None
    return None


def _download_url_to_file(
    url: str,
    dest: pathlib.Path,
    *,
    timeout: int = 180,
) -> pathlib.Path:
    local = _static_url_to_path(url)
    if local is not None:
        return local

    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    dest.write_bytes(response.content)
    return dest


def _write_caption_text(text: str, out_dir: pathlib.Path) -> pathlib.Path:
    clean = (text or "").replace("\r\n", "\n").strip()
    if not clean:
        raise ValueError("subtitle_text is empty")

    suffix = ".vtt" if clean.upper().startswith("WEBVTT") else ".srt"
    path = out_dir / f"captions{suffix}"
    path.write_text(clean + "\n", encoding="utf-8")
    return path


def _materialize_caption_file(
    *,
    subtitle_url: str | None,
    subtitle_text: str | None,
    tmp_dir: pathlib.Path,
) -> pathlib.Path:
    if subtitle_text and subtitle_text.strip():
        return _write_caption_text(subtitle_text, tmp_dir)

    if not subtitle_url:
        raise ValueError("Missing subtitle_url or subtitle_text")

    local = _static_url_to_path(subtitle_url)
    if local is not None:
        text = local.read_text(encoding="utf-8", errors="ignore")
        return _write_caption_text(text, tmp_dir)

    response = requests.get(subtitle_url, timeout=120)
    response.raise_for_status()
    return _write_caption_text(response.text, tmp_dir)


def _safe_media_filename(name: str | None, fallback: str) -> str:
    raw = (name or fallback or "upcurved_video_captions.mp4").strip()
    raw = re.sub(r"[^a-zA-Z0-9._-]+", "_", raw)
    raw = re.sub(r"_+", "_", raw).strip("._") or fallback
    if not raw.lower().endswith(".mp4"):
        raw += ".mp4"
    return raw


def _safe_filename_with_extension(
    name: str | None,
    fallback: str,
    extension: str,
) -> str:
    ext = extension if extension.startswith(".") else f".{extension}"
    raw = (name or fallback or f"upcurved_export{ext}").strip()
    raw = re.sub(r"[^a-zA-Z0-9._-]+", "_", raw)
    raw = re.sub(r"_+", "_", raw).strip("._") or fallback
    if not raw.lower().endswith(ext.lower()):
        raw = re.sub(r"\.[a-zA-Z0-9]{1,8}$", "", raw)
        raw += ext
    return raw


def _caption_text_to_vtt(caption_text: str) -> str:
    clean = (caption_text or "").replace("\r\n", "\n").strip()
    if not clean:
        raise ValueError("caption text is empty")
    if clean.upper().startswith("WEBVTT"):
        return clean + "\n"
    return _srt_to_vtt_text(clean)


def _caption_text_to_transcript(caption_text: str) -> str:
    """Convert VTT/SRT caption text into a readable transcript."""
    text = (caption_text or "").replace("\r\n", "\n").strip()
    if not text:
        return ""

    lines: list[str] = []
    previous = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        upper = line.upper()
        if upper == "WEBVTT" or upper.startswith(
            ("NOTE", "STYLE", "REGION", "KIND:", "LANGUAGE:")
        ):
            continue
        if "-->" in line:
            continue
        if re.fullmatch(r"\d+", line):
            continue
        line = re.sub(r"<[^>]+>", "", line)
        line = re.sub(r"\{[^}]+\}", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        if not line or line == previous:
            continue
        lines.append(line)
        previous = line

    transcript = "\n".join(lines).strip()
    return transcript + "\n" if transcript else ""


def _ffmpeg_filter_path(path: pathlib.Path) -> str:
    """Quote and escape a path for use inside an ffmpeg filter argument.

    ffmpeg splits filter options on ":", so on Windows the drive letter can end
    the filename early and the rest of the path may be parsed as another filter
    option. Escape filter-sensitive characters and quote the complete filename.
    """
    escaped = (
        path.as_posix()
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace(":", "\\:")
    )
    return f"'{escaped}'"


def _burn_captions_with_ffmpeg(
    *,
    video_path: pathlib.Path,
    subtitle_path: pathlib.Path,
    output_path: pathlib.Path,
    logs_dir: pathlib.Path,
) -> None:
    ffmpeg_bin = _find_ffmpeg_bin()
    logs_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    subtitles_filter = f"subtitles={_ffmpeg_filter_path(subtitle_path)}"
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(video_path),
        "-vf",
        subtitles_filter,
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=600,
    )
    (logs_dir / "burn_captions_cmd.txt").write_text(
        " ".join(cmd),
        encoding="utf-8",
    )
    (logs_dir / "burn_captions_stdout.txt").write_text(
        proc.stdout or "",
        encoding="utf-8",
    )
    (logs_dir / "burn_captions_stderr.txt").write_text(
        proc.stderr or "",
        encoding="utf-8",
    )

    if proc.returncode != 0 or not output_path.exists():
        detail = (proc.stderr or proc.stdout or "Unknown ffmpeg error")[-1500:]
        raise RuntimeError(f"ffmpeg caption burn failed: {detail}")


def _structured_result_local_paths(
    result: dict,
) -> tuple[pathlib.Path, pathlib.Path | None]:
    video_url = str(result.get("video_url") or "")
    relative_path = video_url.replace("/static/", "", 1)
    video_path = pathlib.Path(STORAGE) / relative_path

    vtt_path: pathlib.Path | None = None
    vtt_url = result.get("vtt_url")
    if vtt_url:
        vtt_path = pathlib.Path(STORAGE) / str(vtt_url).replace(
            "/static/",
            "",
            1,
        )
    elif video_path.exists():
        candidate = video_path.with_suffix(".vtt")
        if candidate.exists():
            vtt_path = candidate

    return video_path, vtt_path


def _publish_structured_video_result(
    *,
    result: dict,
    uid: str,
    chat_id: str | None,
    fallback_job_id: str | None,
    message: str,
    provider: str | None = None,
    model: str | None = None,
    generation_mode: str | None = None,
) -> dict:
    """Publish a structured video result locally or to GCS."""
    if str(result.get("status") or "").strip() == "needs_clarification":
        return {
            "ok": False,
            "status": "needs_clarification",
            "error": "needs_clarification",
            "message": str(result.get("message") or ""),
            "video_url": None,
            "scene_results": [],
            "generation_diagnostics": result.get("generation_diagnostics"),
        }

    video_url = result.get("video_url")
    render_ok = bool(result.get("ok") and video_url)
    job_id = result.get("job_id") or fallback_job_id or "unknown"
    scene_code = result.get("scene_code") or ""

    if not render_ok or not video_url:
        detail = str(
            result.get("error_detail")
            or result.get("error")
            or result.get("message")
            or "Structured video generation failed."
        )
        root_category = str(result.get("error_category") or "").strip()
        step = "Voice generation" if root_category == "voice_synthesis" else "Manim scene rendering"
        payload = diagnostic_payload(
            feature="video",
            step=step,
            error=detail,
            provider=provider,
            model=model,
        )
        if root_category:
            payload["diagnostics"]["category"] = root_category
        if result.get("retryable") is not None:
            payload["diagnostics"]["retryable"] = bool(result.get("retryable"))
        if result.get("during_stage"):
            payload["diagnostics"]["during_stage"] = result.get("during_stage")
        payload.update(
            {
                "video_url": None,
                # Keep the frontend-safe field for backward compatibility, but never expose
                # raw tracebacks or local paths in the chat response.
                "debug_detail": payload.get("message"),
                "scene_results": result.get("scene_results"),
                "used_fallback": result.get("used_fallback"),
                "generation_diagnostics": result.get(
                    "generation_diagnostics"
                ),
            }
        )
        return payload

    video_path, vtt_path = _structured_result_local_paths(result)
    gcs_bucket = _get_bucket_name()
    signed_video_url = None
    signed_subtitle_url = None
    saved_artifact_id = None
    gcs_path = None

    if gcs_bucket:
        try:
            if not video_path.exists():
                raise RuntimeError(
                    f"Rendered video file not found: {video_path}"
                )

            chat_path = chat_id or "uncategorized"
            video_data = video_path.read_bytes()
            content_type = (
                mimetypes.guess_type(video_path.name)[0]
                or "video/mp4"
            )
            gcs_path = f"{uid}/chats/{chat_path}/video_{job_id}.mp4"
            _upload_bytes(
                gcs_bucket,
                gcs_path,
                video_data,
                content_type,
            )
            signed_video_url = _sign_url(gcs_bucket, gcs_path)
            saved_artifact_id = _save_artifact(
                uid,
                chat_id,
                "video",
                gcs_path,
                len(video_data),
                content_type,
                derived=False,
            )

            if vtt_path is not None and vtt_path.exists():
                vtt_data = vtt_path.read_bytes()
                vtt_gcs_path = (
                    f"{uid}/chats/{chat_path}/video_{job_id}.vtt"
                )
                _upload_bytes(
                    gcs_bucket,
                    vtt_gcs_path,
                    vtt_data,
                    "text/vtt",
                )
                signed_subtitle_url = _sign_url(
                    gcs_bucket,
                    vtt_gcs_path,
                )
                _save_artifact(
                    uid,
                    chat_id,
                    "subtitle",
                    vtt_gcs_path,
                    len(vtt_data),
                    "text/vtt",
                    derived=True,
                )

            if scene_code:
                bundle_data = scene_code.encode("utf-8")
                bundle_path = (
                    f"{uid}/chats/{chat_path}/"
                    f"scene_bundle_{job_id}.txt"
                )
                _upload_bytes(
                    gcs_bucket,
                    bundle_path,
                    bundle_data,
                    "text/plain",
                )
                _save_artifact(
                    uid,
                    chat_id,
                    "script",
                    bundle_path,
                    len(bundle_data),
                    "text/plain",
                    derived=True,
                )
        except Exception as exc:
            logger.exception(
                "Structured video GCS upload failed: %s",
                exc,
            )
            payload = diagnostic_payload(
                feature="video",
                step="video publishing",
                error=exc,
                provider=provider,
                model=model,
            )
            payload["video_url"] = None
            payload["generation_diagnostics"] = result.get(
                "generation_diagnostics"
            )
            return payload

        final_video_url = signed_video_url
    else:
        final_video_url = video_url
        if vtt_path is not None and vtt_path.exists():
            signed_subtitle_url = to_static_url(vtt_path)

    response = {
        "ok": True,
        "status": "ok",
        "video_url": final_video_url,
        "signed_video_url": signed_video_url,
        "signed_subtitle_url": signed_subtitle_url,
        "srt_url": result.get("srt_url"),
        "artifact_id": saved_artifact_id,
        "gcs_path": gcs_path,
        "scene_code": scene_code,
        "scene_plan": result.get("scene_plan"),
        "scene_results": result.get("scene_results"),
        "used_fallback": result.get("used_fallback"),
        "generation_diagnostics": result.get("generation_diagnostics"),
        "message": message,
    }
    if generation_mode is not None:
        response["generation_mode"] = generation_mode
    return response


@app.post("/generate")
def generate(body: GenerateIn, uid: str = Depends(require_firebase_user)):
    gen_mode = (body.mode or "standard").strip().lower()

    if gen_mode == "story":
        started = time.monotonic()
        job_id = _generation_job_id(body.jobId)
        with track_llm_calls() as llm_counter:
            try:
                provider, model = _resolve_provider_model(
                    body.keys,
                    body.provider,
                    body.model,
                )
                provider_keys = _provider_keys_with_env(body.keys)
                logger.info(
                    "/generate called provider=%s model=%s mode=%s",
                    provider,
                    model,
                    gen_mode,
                )
                image_payload = _generation_image_payload(body.images)
                effective_prompt, default_image_prompt_used = resolve_effective_learner_prompt(
                    body.prompt,
                    image_payload,
                )
                story_res = _generate_story_slider(
                    prompt=_with_audience_guidance(effective_prompt, body.audience),
                    learner_prompt=body.prompt,
                    images=image_payload,
                    default_image_prompt_used=default_image_prompt_used,
                    provider=provider,
                    model=model,
                    provider_keys=provider_keys,
                    story_options=body.storyOptions or {},
                )
                if story_res.get("status") == "needs_clarification":
                    _append_artifact_generation_audit(
                        generation_type="story",
                        job_id=job_id,
                        operation="generate",
                        outcome="needs_clarification",
                        provider=provider,
                        model=model,
                        llm_calls=llm_counter.count,
                        started_monotonic=started,
                    )
                    return {
                        "ok": False,
                        "status": "needs_clarification",
                        "error": "needs_clarification",
                        "message": story_res.get("message"),
                        "widget_html": None,
                        "generation_mode": "story",
                        "generation_diagnostics": story_res.get("generation_diagnostics"),
                    }

                widget_html = story_res.get("widget_html")
                if story_res.get("status") == "ok" and widget_html:
                    story_plan = story_res.get("story_plan") or {}
                    story_title = (
                        story_plan.get("title")
                        if isinstance(story_plan, dict)
                        else body.prompt
                    )
                    download_meta = _html_download_payload(
                        uid=uid,
                        chat_id=body.chatId,
                        kind="story",
                        title=story_title or body.prompt,
                        html_text=widget_html,
                        job_id=job_id,
                    )
                    _append_artifact_generation_audit(
                        generation_type="story",
                        job_id=job_id,
                        operation="generate",
                        outcome="clean_success",
                        provider=provider,
                        model=model,
                        llm_calls=llm_counter.count,
                        started_monotonic=started,
                    )
                    return {
                        "ok": True,
                        "status": "ok",
                        "widget_html": widget_html,
                        "story_plan": story_plan,
                        "generation_mode": "story",
                        "message": "Story scene slider generated.",
                        "generation_diagnostics": story_res.get("generation_diagnostics"),
                        **download_meta,
                    }

                detail = (
                    story_res.get("error_detail")
                    or story_res.get("error")
                    or story_res.get("message")
                    or "Story generation failed."
                )
                _append_artifact_generation_audit(
                    generation_type="story",
                    job_id=job_id,
                    operation="generate",
                    outcome="failed",
                    provider=provider,
                    model=model,
                    llm_calls=llm_counter.count,
                    started_monotonic=started,
                    failure_stage="story_generation",
                    error_summary=detail,
                )
                return {
                    "ok": False,
                    "status": "error",
                    "error": "story_slider_failed",
                    "message": "Story generation failed.",
                    "video_url": None,
                }
            except Exception as exc:
                _append_artifact_generation_audit(
                    generation_type="story",
                    job_id=job_id,
                    operation="generate",
                    outcome="failed",
                    provider=locals().get("provider"),
                    model=locals().get("model"),
                    llm_calls=llm_counter.count,
                    started_monotonic=started,
                    failure_stage="story_generation",
                    error_summary=exc,
                )
                logger.exception("/generate story failed with exception: %s", exc)
                return diagnostic_error_response(
                    feature="story",
                    step="story generation",
                    error=exc,
                    provider=locals().get("provider"),
                    model=locals().get("model"),
                )

    try:
        provider, model = _resolve_provider_model(
            body.keys,
            body.provider,
            body.model,
        )
        provider_keys = _provider_keys_with_env(body.keys)
        logger.info(
            "/generate called provider=%s model=%s mode=%s",
            provider,
            model,
            gen_mode,
        )
        from backend.agent.structured_video import (
            generate_structured_manim_video,
        )

        image_payload = _generation_image_payload(body.images)
        effective_prompt, default_image_prompt_used = resolve_effective_learner_prompt(
            body.prompt,
            image_payload,
        )
        result = generate_structured_manim_video(
            prompt=_with_audience_guidance(effective_prompt, body.audience),
            learner_prompt=body.prompt,
            images=image_payload,
            default_image_prompt_used=default_image_prompt_used,
            provider_keys=provider_keys,
            provider=provider,
            model=model,
            job_id=body.jobId,
        )
        response = _publish_structured_video_result(
            result=result,
            uid=uid,
            chat_id=body.chatId,
            fallback_job_id=body.jobId,
            message="Video generated.",
            provider=provider,
            model=model,
            generation_mode="standard",
        )

        if response.get("status") == "needs_clarification":
            logger.info(
                "/generate needs clarification (job_id=%s)",
                result.get("job_id"),
            )
        elif response.get("ok"):
            logger.info(
                "/generate completed: ok (job_id=%s)",
                result.get("job_id"),
            )
        else:
            logger.warning(
                "/generate failed (job_id=%s)",
                result.get("job_id"),
            )
        return response

    except Exception as exc:
        logger.exception("/generate failed with exception: %s", exc)
        return diagnostic_error_response(
            feature="video",
            step="video generation",
            error=exc,
            provider=locals().get("provider"),
            model=locals().get("model"),
        )


@app.post("/edit")
def edit_video(body: EditVideoIn, uid: str = Depends(require_firebase_user)):
    """Edit a structured scene bundle and re-render it scene by scene."""
    logger.info("=" * 50)
    logger.info("/edit endpoint called")

    if not body.original_code or not body.original_code.strip():
        raise HTTPException(
            status_code=400,
            detail="original_code is required and cannot be empty",
        )
    if not body.edit_instructions or not body.edit_instructions.strip():
        raise HTTPException(
            status_code=400,
            detail="edit_instructions is required and cannot be empty",
        )

    from backend.agent.structured_video import (
        edit_structured_manim_video,
        is_structured_scene_bundle,
    )

    if not is_structured_scene_bundle(body.original_code):
        raise HTTPException(
            status_code=400,
            detail=(
                "This video does not contain a structured scene bundle. "
                "Legacy monolithic video editing has been removed."
            ),
        )

    provider, model = _resolve_provider_model(
        body.keys,
        body.provider,
        body.model,
    )
    provider_keys = _provider_keys_with_env(body.keys)
    logger.info(
        "/edit using provider=%s model=%s",
        provider,
        model,
    )

    try:
        result = edit_structured_manim_video(
            original_bundle=body.original_code,
            edit_instructions=_with_audience_guidance(
                body.edit_instructions,
                body.audience,
            ),
            provider=provider,
            model=model,
            provider_keys=provider_keys,
            job_id=body.jobId,
        )
        response = _publish_structured_video_result(
            result=result,
            uid=uid,
            chat_id=body.chatId,
            fallback_job_id=body.jobId,
            message="Video edited successfully.",
            provider=provider,
            model=model,
        )
        if response.get("ok"):
            logger.info(
                "/edit completed: ok (job_id=%s)",
                result.get("job_id"),
            )
        return response
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("/edit failed with exception: %s", exc)
        return diagnostic_error_response(
            feature="video",
            step="video editing",
            error=exc,
            provider=locals().get("provider"),
            model=locals().get("model"),
        )


@app.post("/quiz/embedded")
def quiz_embedded(body: QuizIn, uid: str = Depends(require_firebase_user)):
    started = time.monotonic()
    job_id = _generation_job_id(body.jobId)
    with track_llm_calls() as llm_counter:
        try:
            provider, model = _resolve_provider_model(
                body.keys,
                body.provider,
                body.model,
            )
            provider_keys = _provider_keys_with_env(body.keys)
            image_payload = _generation_image_payload(body.images)
            effective_prompt, default_image_prompt_used = resolve_effective_learner_prompt(
                body.prompt,
                image_payload,
            )
            quiz = _generate_quiz_embedded(
                prompt=_with_audience_guidance(effective_prompt, body.audience),
                learner_prompt=body.prompt,
                images=image_payload,
                default_image_prompt_used=default_image_prompt_used,
                num_questions=body.num_questions,
                difficulty=body.difficulty or "medium",
                provider=provider,
                model=model,
                provider_keys=provider_keys,
                context=body.context,
            )
            if quiz.get("status") == "needs_clarification":
                _append_artifact_generation_audit(
                    generation_type="quiz",
                    job_id=job_id,
                    operation="generate",
                    outcome="needs_clarification",
                    provider=provider,
                    model=model,
                    llm_calls=llm_counter.count,
                    started_monotonic=started,
                )
                return {
                    "ok": False,
                    "status": "needs_clarification",
                    "error": "needs_clarification",
                    "message": quiz.get("message"),
                    "quiz": None,
                    "generation_diagnostics": quiz.get("generation_diagnostics"),
                }

            quiz_html = build_quiz_html(quiz, source_title=body.prompt)
            download_meta = _html_download_payload(
                uid=uid,
                chat_id=body.chatId,
                kind="quiz",
                title=quiz.get("title") or body.prompt,
                html_text=quiz_html,
                job_id=job_id,
            )
            _append_artifact_generation_audit(
                generation_type="quiz",
                job_id=job_id,
                operation="generate",
                outcome="clean_success",
                provider=provider,
                model=model,
                llm_calls=llm_counter.count,
                started_monotonic=started,
            )
            return {
                "status": "ok",
                "quiz": quiz,
                "generation_diagnostics": quiz.get("generation_diagnostics"),
                **download_meta,
            }
        except Exception as exc:
            _append_artifact_generation_audit(
                generation_type="quiz",
                job_id=job_id,
                operation="generate",
                outcome="failed",
                provider=locals().get("provider"),
                model=locals().get("model"),
                llm_calls=llm_counter.count,
                started_monotonic=started,
                failure_stage="quiz_generation",
                error_summary=exc,
            )
            logger.exception("/quiz/embedded failed: %s", exc)
            return diagnostic_error_response(
                feature="quiz",
                step="quiz generation",
                error=exc,
                provider=locals().get("provider"),
                model=locals().get("model"),
            )


@app.post("/quiz/media")
def quiz_media(body: dict, uid: str = Depends(require_firebase_user)):
    started = time.monotonic()
    job_id = _generation_job_id(body.get("jobId"))
    with track_llm_calls() as llm_counter:
        try:
            transcript = body.get("transcript", "").strip()
            if not transcript:
                raise ValueError("Transcript from VTT captions is required")

            provider_keys = _provider_keys_with_env(
                body.get("provider_keys", {})
            )
            provider, model = _resolve_provider_model(
                provider_keys,
                body.get("provider"),
                body.get("model"),
                default_provider="gemini",
            )
            context = body.get("sceneCode")
            num_questions = body.get("num_questions", 5)
            difficulty = body.get("difficulty", "medium")
            media_prompt = (
                "Generate quiz questions based ONLY on the following content "
                "(from captions):\n\n"
                f"{transcript}"
            )
            media_prompt = _with_audience_guidance(
                media_prompt,
                body.get("audience"),
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
            if quiz.get("status") == "needs_clarification":
                _append_artifact_generation_audit(
                    generation_type="quiz",
                    job_id=job_id,
                    operation="generate",
                    outcome="needs_clarification",
                    provider=provider,
                    model=model,
                    llm_calls=llm_counter.count,
                    started_monotonic=started,
                )
                return {
                    "ok": False,
                    "status": "needs_clarification",
                    "error": "needs_clarification",
                    "message": quiz.get("message"),
                    "quiz": None,
                    "generation_diagnostics": quiz.get("generation_diagnostics"),
                }

            quiz_html = build_quiz_html(quiz, source_title="Media quiz")
            download_meta = _html_download_payload(
                uid=uid,
                chat_id=body.get("chatId"),
                kind="quiz",
                title=quiz.get("title") or "Media quiz",
                html_text=quiz_html,
                job_id=job_id,
            )
            _append_artifact_generation_audit(
                generation_type="quiz",
                job_id=job_id,
                operation="generate",
                outcome="clean_success",
                provider=provider,
                model=model,
                llm_calls=llm_counter.count,
                started_monotonic=started,
            )
            return {"status": "ok", "quiz": quiz, **download_meta}
        except Exception as exc:
            _append_artifact_generation_audit(
                generation_type="quiz",
                job_id=job_id,
                operation="generate",
                outcome="failed",
                provider=locals().get("provider"),
                model=locals().get("model"),
                llm_calls=llm_counter.count,
                started_monotonic=started,
                failure_stage="quiz_media_generation",
                error_summary=exc,
            )
            logger.exception("/quiz/media failed: %s", exc)
            return diagnostic_error_response(
                feature="quiz",
                step="quiz from media captions",
                error=exc,
                provider=locals().get("provider"),
                model=locals().get("model"),
            )


@app.post("/podcast")
def podcast(body: PodcastIn, uid: str = Depends(require_firebase_user)):
    started = time.monotonic()
    job_id = _generation_job_id(body.jobId)
    with track_llm_calls() as llm_counter:
        try:
            provider, model = _resolve_provider_model(
                body.keys,
                body.provider,
                body.model,
            )
            provider_keys = _provider_keys_with_env(body.keys)
            image_payload = _generation_image_payload(body.images)
            effective_prompt, default_image_prompt_used = resolve_effective_learner_prompt(
                body.prompt,
                image_payload,
            )
            result = _generate_podcast(
                prompt=_with_audience_guidance(effective_prompt, body.audience),
                learner_prompt=body.prompt,
                images=image_payload,
                default_image_prompt_used=default_image_prompt_used,
                provider=provider,
                model=model,
                provider_keys=provider_keys,
                mode=body.mode or "standard",
                job_id=job_id,
            )
            if result.get("status") == "needs_clarification":
                _append_artifact_generation_audit(
                    generation_type="podcast",
                    job_id=job_id,
                    operation="generate",
                    outcome="needs_clarification",
                    provider=provider,
                    model=model,
                    llm_calls=llm_counter.count,
                    started_monotonic=started,
                )
                return result

            gcs_bucket = _get_bucket_name()
            if gcs_bucket and result.get("video_url"):
                try:
                    result_job_id = result.get("job_id", job_id)
                    relative_path = result["video_url"].replace("/static/", "")
                    path = pathlib.Path(STORAGE) / relative_path
                    if path.exists():
                        data = path.read_bytes()
                        content_type = (
                            mimetypes.guess_type(path.name)[0]
                            or "audio/mpeg"
                        )
                        gcs_path = (
                            f"{uid}/chats/{body.chatId or 'uncategorized'}/"
                            f"podcast_{result_job_id}.mp3"
                        )
                        _upload_bytes(
                            gcs_bucket,
                            gcs_path,
                            data,
                            content_type,
                        )
                        result["signed_video_url"] = _sign_url(
                            gcs_bucket,
                            gcs_path,
                        )
                        result["gcs_path"] = gcs_path
                        result["artifact_id"] = _save_artifact(
                            uid,
                            body.chatId,
                            "podcast",
                            gcs_path,
                            len(data),
                            content_type,
                            derived=False,
                        )

                        if result.get("script"):
                            script_bytes = result["script"].encode("utf-8")
                            chat_path = body.chatId or "uncategorized"
                            script_gcs_path = (
                                f"{uid}/chats/{chat_path}/"
                                f"podcast_{result_job_id}_script.txt"
                            )
                            _upload_bytes(
                                gcs_bucket,
                                script_gcs_path,
                                script_bytes,
                                "text/plain",
                            )
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

                        vtt_path_local = None
                        if result.get("vtt_url"):
                            vtt_relative = result["vtt_url"].replace(
                                "/static/",
                                "",
                            )
                            vtt_path_local = pathlib.Path(STORAGE) / vtt_relative
                            if vtt_path_local.exists():
                                vtt_data = vtt_path_local.read_bytes()
                                chat_path = body.chatId or "uncategorized"
                                vtt_gcs_path = (
                                    f"{uid}/chats/{chat_path}/"
                                    f"podcast_{result_job_id}.vtt"
                                )
                                _upload_bytes(
                                    gcs_bucket,
                                    vtt_gcs_path,
                                    vtt_data,
                                    "text/vtt",
                                )
                                result["signed_subtitle_url"] = _sign_url(
                                    gcs_bucket,
                                    vtt_gcs_path,
                                )
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
                                if path.exists():
                                    path.unlink()
                                if (
                                    result.get("signed_subtitle_url")
                                    and vtt_path_local is not None
                                    and vtt_path_local.exists()
                                ):
                                    vtt_path_local.unlink()
                            except Exception as exc:
                                logger.warning(
                                    "Failed to clean up local podcast files: %s",
                                    exc,
                                )
                except Exception as exc:
                    logger.warning("GCS podcast upload failed: %s", exc)
                    if gcs_bucket:
                        raise HTTPException(
                            status_code=500,
                            detail=(
                                "Podcast generated but GCS upload failed. "
                                "Please try again."
                            ),
                        ) from exc
            elif result.get("vtt_url"):
                result["signed_subtitle_url"] = result["vtt_url"]

            if gcs_bucket:
                if not result.get("signed_video_url"):
                    raise HTTPException(
                        status_code=500,
                        detail=(
                            "GCS bucket configured but upload failed. "
                            "Please try again."
                        ),
                    )
                result["video_url"] = result["signed_video_url"]

            succeeded = bool(
                result.get("ok") is True
                or result.get("status") == "ok"
                or result.get("video_url")
            )
            if succeeded:
                _append_artifact_generation_audit(
                    generation_type="podcast",
                    job_id=job_id,
                    operation="generate",
                    outcome="clean_success",
                    provider=provider,
                    model=model,
                    llm_calls=llm_counter.count,
                    started_monotonic=started,
                )
            else:
                detail = (
                    result.get("error_detail")
                    or result.get("error")
                    or result.get("message")
                    or "Podcast generation failed."
                )
                _append_artifact_generation_audit(
                    generation_type="podcast",
                    job_id=job_id,
                    operation="generate",
                    outcome="failed",
                    provider=provider,
                    model=model,
                    llm_calls=llm_counter.count,
                    started_monotonic=started,
                    failure_stage="podcast_generation",
                    error_summary=detail,
                )
            return result
        except Exception as exc:
            _append_artifact_generation_audit(
                generation_type="podcast",
                job_id=job_id,
                operation="generate",
                outcome="failed",
                provider=locals().get("provider"),
                model=locals().get("model"),
                llm_calls=llm_counter.count,
                started_monotonic=started,
                failure_stage="podcast_generation",
                error_summary=exc,
            )
            logger.exception("/podcast failed: %s", exc)
            return diagnostic_error_response(
                feature="podcast",
                step="podcast generation",
                error=exc,
                provider=locals().get("provider"),
                model=locals().get("model"),
            )


def _extract_complete_html_document(raw: str) -> str:
    """Extract and lightly validate a complete HTML document."""
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    low = text.lower()
    html_start = low.find("<!doctype")
    if html_start < 0:
        html_start = low.find("<html")
    if html_start > 0:
        text = text[html_start:].strip()
        low = text.lower()

    if (
        "<html" not in low
        or "</html>" not in low
        or "<body" not in low
        or "</body>" not in low
    ):
        raise RuntimeError("Model did not return a complete HTML document.")
    if "<script" in low and "</script>" not in low:
        raise RuntimeError(
            "Edited HTML appears truncated (missing </script>)."
        )

    text = re.sub(
        r"""<script\b[^>]*\bsrc\s*=\s*['\"]https?://[^'\"]*['\"][^>]*>\s*</script>""",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"""<link\b[^>]*\brel\s*=\s*['\"]stylesheet['\"][^>]*>""",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"""@import\s+url\(['\"]?https?://[^'\")]+['\"]?\)\s*;?""",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return text


def _strip_llm_code_fence(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _parse_llm_json_object(raw: str) -> dict:
    text = _strip_llm_code_fence(raw)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return json.loads(text)


def _find_story_plan_json_bounds(html: str) -> tuple[int, int]:
    """Find the JSON object assigned to ``const P = {...}``."""
    marker = "const P ="
    pos = html.find(marker)
    if pos < 0:
        raise RuntimeError(
            "Could not find story plan JSON (const P) in story HTML."
        )
    start = html.find("{", pos)
    if start < 0:
        raise RuntimeError(
            "Could not find story plan JSON start in story HTML."
        )

    depth = 0
    in_str = False
    escaped = False
    for index in range(start, len(html)):
        char = html[index]
        if in_str:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_str = False
            continue

        if char == '"':
            in_str = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return start, index + 1

    raise RuntimeError("Could not find story plan JSON end in story HTML.")


def _extract_story_plan_from_html(html: str) -> dict:
    start, end = _find_story_plan_json_bounds(html)
    return json.loads(html[start:end])


def _replace_story_plan_in_html(html: str, plan: dict) -> str:
    start, end = _find_story_plan_json_bounds(html)
    plan_json = json.dumps(
        plan,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return html[:start] + plan_json + html[end:]


def _looks_like_bad_story_draw_js(draw_js: object) -> bool:
    text = str(draw_js or "").strip()
    if not text:
        return True
    low = text.lower()
    bad_phrases = (
        "we are given",
        "let's plan",
        "lets plan",
        "constraints:",
        "visual description:",
        "we need to show",
        "the scene should",
        "```",
    )
    if any(phrase in low for phrase in bad_phrases):
        return True
    code_markers = (
        "x.",
        "draw",
        "const ",
        "let ",
        "for(",
        "for (",
        "Math.",
    )
    return not any(marker in text for marker in code_markers)


def _story_scene_summaries_for_edit(plan: dict) -> list[dict]:
    scenes = plan.get("scenes") if isinstance(plan, dict) else []
    output: list[dict] = []
    if not isinstance(scenes, list):
        return output

    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            continue
        draw_js = str(scene.get("draw_js") or "")
        output.append(
            {
                "scene_number": index,
                "heading": scene.get("heading") or "",
                "caption": scene.get("caption") or "",
                "lesson": scene.get("lesson") or "",
                "science_fact": scene.get("science_fact") or "",
                "vocabulary": scene.get("vocabulary") or [],
                "cause_effect": scene.get("cause_effect") or "",
                "misconception_fix": (
                    scene.get("misconception_fix") or ""
                ),
                "speech_bubble": scene.get("speech_bubble") or "",
                "visual": scene.get("visual") or "",
                "draw_js_status": (
                    "invalid_or_generic"
                    if _looks_like_bad_story_draw_js(draw_js)
                    else "probably_executable"
                ),
                "draw_js_excerpt": draw_js[:900],
            }
        )
    return output


def _apply_story_patch_to_plan(plan: dict, patch: dict) -> dict:
    if not isinstance(patch, dict):
        raise RuntimeError("Story edit patch was not a JSON object.")

    new_plan = json.loads(json.dumps(plan, ensure_ascii=False))
    for top_key in ("title", "moral", "conclusion"):
        value = patch.get(top_key)
        if isinstance(value, str) and value.strip():
            new_plan[top_key] = value.strip()

    scenes = new_plan.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise RuntimeError("Story plan has no scenes to edit.")

    updates = patch.get("updates")
    if not isinstance(updates, list) or not updates:
        raise RuntimeError(
            "Story edit patch did not include scene updates."
        )

    allowed = {
        "heading",
        "caption",
        "lesson",
        "science_fact",
        "vocabulary",
        "cause_effect",
        "misconception_fix",
        "speech_bubble",
        "visual",
        "draw_js",
        "duration_sec",
        "theme",
    }
    applied = 0

    for update in updates:
        if not isinstance(update, dict):
            continue
        raw_number = update.get("scene_number", update.get("index"))
        try:
            scene_index = int(raw_number) - 1
        except Exception:
            continue

        if (
            scene_index < 0
            or scene_index >= len(scenes)
            or not isinstance(scenes[scene_index], dict)
        ):
            continue

        for key_name, value in update.items():
            if key_name in ("scene_number", "index"):
                continue
            if key_name not in allowed:
                continue
            if key_name == "draw_js" and not isinstance(value, str):
                continue
            if isinstance(value, str) and not value.strip():
                continue
            scenes[scene_index][key_name] = value
            applied += 1

    if applied <= 0:
        raise RuntimeError(
            "Story edit patch contained no applicable changes."
        )
    return new_plan


def _edit_story_by_plan_patch(
    *,
    original_html: str,
    edit_instructions: str,
    original_title: str | None,
    provider: str,
    model: str | None,
    api_key: str,
) -> str:
    """Edit a story by patching its embedded JSON plan."""
    plan = _extract_story_plan_from_html(original_html)
    summaries = _story_scene_summaries_for_edit(plan)
    raw = call_llm(
        provider=provider,
        api_key=api_key,
        model=model,
        system=STORY_EDIT_PATCH_SYSTEM,
        user=build_story_edit_patch_user_prompt(
            original_title=original_title or plan.get("title"),
            scene_summaries=summaries,
            edit_instructions=edit_instructions,
        ),
        temperature=0.12,
        max_tokens=6000,
        max_output_tokens=6000,
    )
    patch = _parse_llm_json_object(raw)
    new_plan = _apply_story_patch_to_plan(plan, patch)
    return _replace_story_plan_in_html(original_html, new_plan)


def _edit_story_html(
    *,
    original_html: str,
    edit_instructions: str,
    original_title: str | None,
    provider: str,
    model: str | None,
    provider_keys: dict[str, str],
) -> str:
    """Edit an existing story slider."""
    key = _get_provider_key(provider, provider_keys)
    if not key:
        raise HTTPException(
            status_code=400,
            detail=f"Missing API key for '{provider}'",
        )
    if not original_html or not original_html.strip():
        raise HTTPException(
            status_code=400,
            detail="original_html is required",
        )
    if not edit_instructions or not edit_instructions.strip():
        raise HTTPException(
            status_code=400,
            detail="edit_instructions is required",
        )

    try:
        patched_html = _edit_story_by_plan_patch(
            original_html=original_html,
            edit_instructions=edit_instructions,
            original_title=original_title,
            provider=provider,
            model=model,
            api_key=key,
        )
        return _extract_complete_html_document(patched_html)
    except Exception as patch_error:
        logger.warning(
            "story edit: JSON patch path failed; "
            "trying full-HTML fallback: %s",
            patch_error,
        )

    raw = call_llm(
        provider=provider,
        api_key=key,
        model=model,
        system=STORY_EDIT_FULL_HTML_SYSTEM,
        user=build_story_edit_full_html_user_prompt(
            original_html=original_html,
            edit_instructions=edit_instructions,
            original_title=original_title,
        ),
        temperature=0.1,
        max_tokens=12000,
        max_output_tokens=12000,
    )
    html = _extract_complete_html_document(raw)
    low = html.lower()
    if (
        "<button" not in low
        and "onclick" not in low
        and "addeventlistener" not in low
    ):
        raise RuntimeError(
            "Edited story appears to have lost interactive navigation."
        )
    return html


@app.post("/widget")
def widget(body: WidgetIn, uid: str = Depends(require_firebase_user)):
    started = time.monotonic()
    job_id = _generation_job_id(body.jobId)
    with track_llm_calls() as llm_counter:
        try:
            provider, model = _resolve_provider_model(
                body.keys,
                body.provider,
                body.model,
            )
            provider_keys = _provider_keys_with_env(body.keys)
            logger.info("/widget called provider=%s model=%s", provider, model)
            image_payload = _generation_image_payload(body.images)
            effective_prompt, default_image_prompt_used = resolve_effective_learner_prompt(
                body.prompt,
                image_payload,
            )
            result = _generate_widget(
                prompt=_with_audience_guidance(effective_prompt, body.audience),
                learner_prompt=body.prompt,
                images=image_payload,
                default_image_prompt_used=default_image_prompt_used,
                provider=provider,
                model=model,
                provider_keys=provider_keys,
            )
            if result.get("status") == "needs_clarification":
                _append_artifact_generation_audit(
                    generation_type="widget",
                    job_id=job_id,
                    operation="generate",
                    outcome="needs_clarification",
                    provider=provider,
                    model=model,
                    llm_calls=llm_counter.count,
                    started_monotonic=started,
                )
                return result

            widget_html = result["widget_html"]
            download_meta = _html_download_payload(
                uid=uid,
                chat_id=body.chatId,
                kind="widget",
                title=body.prompt,
                html_text=widget_html,
                job_id=job_id,
            )
            _append_artifact_generation_audit(
                generation_type="widget",
                job_id=job_id,
                operation="generate",
                outcome="clean_success",
                provider=provider,
                model=model,
                llm_calls=llm_counter.count,
                started_monotonic=started,
            )
            logger.info(
                "/widget completed: ok, html_len=%d",
                len(widget_html),
            )
            return {
                "ok": True,
                "status": "ok",
                "widget_html": widget_html,
                "generation_diagnostics": result.get("generation_diagnostics"),
                **download_meta,
            }
        except Exception as exc:
            _append_artifact_generation_audit(
                generation_type="widget",
                job_id=job_id,
                operation="generate",
                outcome="failed",
                provider=locals().get("provider"),
                model=locals().get("model"),
                llm_calls=llm_counter.count,
                started_monotonic=started,
                failure_stage="widget_generation",
                error_summary=exc,
            )
            logger.exception("/widget failed: %s", exc)
            return diagnostic_error_response(
                feature="widget",
                step="widget generation",
                error=exc,
                provider=locals().get("provider"),
                model=locals().get("model"),
            )


@app.post("/edit/widget")
def edit_widget_endpoint(
    body: EditWidgetIn,
    uid: str = Depends(require_firebase_user),
):
    started = time.monotonic()
    job_id = _generation_job_id(body.jobId)
    with track_llm_calls() as llm_counter:
        try:
            provider, model = _resolve_provider_model(
                body.keys,
                body.provider,
                body.model,
            )
            provider_keys = _provider_keys_with_env(body.keys)
            logger.info("/edit/widget called provider=%s model=%s", provider, model)
            result = _edit_widget(
                original_html=body.original_html,
                edit_instructions=_with_audience_guidance(
                    body.edit_instructions,
                    body.audience,
                ),
                original_title=body.original_title,
                provider=provider,
                model=model,
                provider_keys=provider_keys,
            )
            widget_html = result["widget_html"]
            download_meta = _html_download_payload(
                uid=uid,
                chat_id=body.chatId,
                kind="widget",
                title=body.original_title or "Edited widget",
                html_text=widget_html,
                job_id=job_id,
            )
            _append_artifact_generation_audit(
                generation_type="widget",
                job_id=job_id,
                operation="edit",
                outcome="clean_success",
                provider=provider,
                model=model,
                llm_calls=llm_counter.count,
                started_monotonic=started,
            )
            return {
                "ok": True,
                "status": "ok",
                "widget_html": widget_html,
                **download_meta,
            }
        except Exception as exc:
            _append_artifact_generation_audit(
                generation_type="widget",
                job_id=job_id,
                operation="edit",
                outcome="failed",
                provider=locals().get("provider"),
                model=locals().get("model"),
                llm_calls=llm_counter.count,
                started_monotonic=started,
                failure_stage="widget_edit",
                error_summary=exc,
            )
            logger.exception("/edit/widget failed: %s", exc)
            return diagnostic_error_response(
                feature="widget",
                step="widget editing",
                error=exc,
                provider=locals().get("provider"),
                model=locals().get("model"),
            )


@app.post("/edit/story")
def edit_story_endpoint(
    body: EditStoryIn,
    uid: str = Depends(require_firebase_user),
):
    started = time.monotonic()
    job_id = _generation_job_id(body.jobId)
    with track_llm_calls() as llm_counter:
        try:
            provider, model = _resolve_provider_model(
                body.keys,
                body.provider,
                body.model,
            )
            provider_keys = _provider_keys_with_env(body.keys)
            logger.info("/edit/story called provider=%s model=%s", provider, model)
            story_html = _edit_story_html(
                original_html=body.original_html,
                edit_instructions=_with_audience_guidance(
                    body.edit_instructions,
                    body.audience,
                ),
                original_title=body.original_title,
                provider=provider,
                model=model,
                provider_keys=provider_keys,
            )
            download_meta = _html_download_payload(
                uid=uid,
                chat_id=body.chatId,
                kind="story",
                title=body.original_title or "Edited story",
                html_text=story_html,
                job_id=job_id,
            )
            _append_artifact_generation_audit(
                generation_type="story",
                job_id=job_id,
                operation="edit",
                outcome="clean_success",
                provider=provider,
                model=model,
                llm_calls=llm_counter.count,
                started_monotonic=started,
            )
            return {
                "ok": True,
                "status": "ok",
                "widget_html": story_html,
                "generation_mode": "story",
                "message": "Story edited successfully.",
                **download_meta,
            }
        except Exception as exc:
            _append_artifact_generation_audit(
                generation_type="story",
                job_id=job_id,
                operation="edit",
                outcome="failed",
                provider=locals().get("provider"),
                model=locals().get("model"),
                llm_calls=llm_counter.count,
                started_monotonic=started,
                failure_stage="story_edit",
                error_summary=exc,
            )
            logger.exception("/edit/story failed: %s", exc)
            return diagnostic_error_response(
                feature="story",
                step="story editing",
                error=exc,
                provider=locals().get("provider"),
                model=locals().get("model"),
            )


@app.post("/edit/quiz")
def edit_quiz_endpoint(
    body: EditQuizIn,
    uid: str = Depends(require_firebase_user),
):
    started = time.monotonic()
    job_id = _generation_job_id(body.jobId)
    with track_llm_calls() as llm_counter:
        try:
            provider, model = _resolve_provider_model(
                body.keys,
                body.provider,
                body.model,
            )
            provider_keys = _provider_keys_with_env(body.keys)
            logger.info("/edit/quiz called provider=%s model=%s", provider, model)
            quiz = _edit_quiz_embedded(
                original_quiz=body.original_quiz,
                edit_instructions=_with_audience_guidance(
                    body.edit_instructions,
                    body.audience,
                ),
                num_questions=body.num_questions,
                difficulty=body.difficulty or "medium",
                provider=provider,
                model=model,
                provider_keys=provider_keys,
            )
            quiz_html = build_quiz_html(
                quiz,
                source_title=(
                    quiz.get("title")
                    or body.original_quiz.get("title")
                    or "Edited quiz"
                ),
            )
            download_meta = _html_download_payload(
                uid=uid,
                chat_id=body.chatId,
                kind="quiz",
                title=quiz.get("title") or "Edited quiz",
                html_text=quiz_html,
                job_id=job_id,
            )
            _append_artifact_generation_audit(
                generation_type="quiz",
                job_id=job_id,
                operation="edit",
                outcome="clean_success",
                provider=provider,
                model=model,
                llm_calls=llm_counter.count,
                started_monotonic=started,
            )
            return {"status": "ok", "quiz": quiz, **download_meta}
        except Exception as exc:
            _append_artifact_generation_audit(
                generation_type="quiz",
                job_id=job_id,
                operation="edit",
                outcome="failed",
                provider=locals().get("provider"),
                model=locals().get("model"),
                llm_calls=llm_counter.count,
                started_monotonic=started,
                failure_stage="quiz_edit",
                error_summary=exc,
            )
            logger.exception("/edit/quiz failed: %s", exc)
            return diagnostic_error_response(
                feature="quiz",
                step="quiz editing",
                error=exc,
                provider=locals().get("provider"),
                model=locals().get("model"),
            )


def _chat_doc(uid: str, chat_id: str):
    return (
        _get_db()
        .collection("users")
        .document(uid)
        .collection("chats")
        .document(chat_id)
    )


def _paginate_messages(
    chat_id: str,
    uid: str,
    limit: int,
    before_ms: int | None,
) -> tuple[list[MessageOut], bool]:
    if DESKTOP_LOCAL_MODE:
        chat = _desktop_chat(uid, chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")
        messages = list(chat.get("messages", []))
        if before_ms is not None:
            messages = [
                message
                for message in messages
                if int(message.get("createdAt", 0) or 0) < before_ms
            ]
        messages.sort(key=_stored_message_sort_key)
        has_more = len(messages) > limit
        if has_more:
            messages = messages[-limit:]
        output = [
            MessageOut(
                message_id=str(message.get("message_id")),
                role=message.get("role", "assistant"),
                content=message.get("content", ""),
                createdAt=int(message.get("createdAt", 0) or 0),
                clientCreatedAt=int(
                    message.get("clientCreatedAt", 0) or 0
                ) or None,
                sequence=int(message.get("sequence", 0) or 0) or None,
                media=message.get("media"),
                quizAnchor=message.get("quizAnchor"),
                quizTitle=message.get("quizTitle"),
                quizData=message.get("quizData"),
            )
            for message in messages
        ]
        return output, has_more

    messages_ref = _chat_doc(uid, chat_id).collection("messages")
    if before_ms:
        query = (
            messages_ref.order_by(
                "createdAt",
                direction=gcf.Query.DESCENDING,
            )
            .where(
                "createdAt",
                "<",
                gcf.Timestamp(
                    before_ms // 1000,
                    (before_ms % 1000) * 1_000_000,
                ),
            )
            .limit(limit + 1)
        )
        snapshots = list(query.stream())
        has_more = len(snapshots) > limit
        if has_more:
            snapshots = snapshots[:limit]
        snapshots.reverse()
    else:
        query = messages_ref.order_by(
            "createdAt",
            direction=gcf.Query.DESCENDING,
        ).limit(limit + 1)
        snapshots = list(query.stream())
        has_more = len(snapshots) > limit
        if has_more:
            snapshots = snapshots[:limit]
        snapshots.reverse()

    output: list[MessageOut] = []
    for snapshot in snapshots:
        data = snapshot.to_dict() or {}
        output.append(
            MessageOut(
                message_id=snapshot.id,
                role=data.get("role", "assistant"),
                content=data.get("content", ""),
                createdAt=_to_ms(data.get("createdAt")),
                clientCreatedAt=(
                    int(data.get("clientCreatedAt"))
                    if data.get("clientCreatedAt") is not None
                    else None
                ),
                sequence=(
                    int(data.get("sequence"))
                    if data.get("sequence") is not None
                    else None
                ),
                media=data.get("media") or None,
                quizAnchor=data.get("quizAnchor") or None,
                quizTitle=data.get("quizTitle") or None,
                quizData=data.get("quizData") or None,
            )
        )
    output.sort(
        key=lambda message: (
            int(message.createdAt or 0),
            int(message.sequence or 0),
            message.message_id,
        )
    )
    return output, has_more


def get_chat(
    chat_id: str,
    uid: str,
    limit: int = 200,
    before_ms: int | None = None,
):
    if DESKTOP_LOCAL_MODE:
        chat = _desktop_chat(uid, chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")
        messages, _ = _paginate_messages(
            chat_id,
            uid,
            limit=limit,
            before_ms=before_ms,
        )
        return ChatDetailOut(
            chat_id=chat_id,
            title=chat.get("title", "Untitled"),
            dts=int(chat.get("updatedAt", 0) or 0),
            sessionId=chat.get("sessionId"),
            messages=messages,
            shareable=bool(chat.get("shareable", False)),
            share_token=chat.get("shareToken"),
            model=chat.get("model"),
        )

    chat_snapshot = _chat_doc(uid, chat_id).get()
    if not chat_snapshot.exists:
        raise HTTPException(status_code=404, detail="Chat not found")
    chat_data = chat_snapshot.to_dict() or {}
    messages, _ = _paginate_messages(
        chat_id,
        uid,
        limit=limit,
        before_ms=before_ms,
    )
    return ChatDetailOut(
        chat_id=chat_id,
        title=chat_data.get("title", "Untitled"),
        dts=_to_ms(chat_data.get("updatedAt")),
        sessionId=chat_data.get("sessionId"),
        messages=messages,
        shareable=bool(chat_data.get("shareable", False)),
        share_token=chat_data.get("shareToken"),
        model=chat_data.get("model"),
    )


def append_message(chat_id: str, body: MessageCreateIn, uid: str) -> MessageOut:
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

        messages = chat.setdefault("messages", [])
        existing_index = next(
            (
                index
                for index, message in enumerate(messages)
                if message.get("message_id") == message_id
            ),
            -1,
        )
        existing_message = (
            dict(messages[existing_index])
            if existing_index >= 0
            else {}
        )
        last_created_at = max(
            (int(message.get("createdAt", 0) or 0) for message in messages),
            default=0,
        )
        created_at = int(existing_message.get("createdAt", 0) or 0) or max(
            now_ms,
            last_created_at + 1,
        )
        client_created_at = int(
            existing_message.get("clientCreatedAt", 0) or 0
        ) or _safe_client_created_at(body.clientCreatedAt, now_ms)
        sequence = int(existing_message.get("sequence", 0) or 0) or _safe_message_sequence(
            body.sequence,
            client_created_at,
        )

        payload = {
            **existing_message,
            "message_id": message_id,
            "role": body.role,
            "content": body.content,
            "createdAt": created_at,
            "clientCreatedAt": client_created_at,
            "sequence": sequence,
            "media": media_dict,
            "quizAnchor": body.quizAnchor,
            "quizTitle": body.quizTitle,
            "quizData": body.quizData,
        }
        if existing_index >= 0:
            messages[existing_index] = payload
        else:
            messages.append(payload)
        messages.sort(key=_stored_message_sort_key)
        chat["updatedAt"] = max(now_ms, created_at)
        _save_desktop_store()
        return MessageOut(
            message_id=message_id,
            role=body.role,
            content=body.content,
            createdAt=created_at,
            clientCreatedAt=client_created_at,
            sequence=sequence,
            media=media_dict,
            quizAnchor=body.quizAnchor,
            quizTitle=body.quizTitle,
            quizData=body.quizData,
        )

    chat_ref = _chat_doc(uid, chat_id)
    if not chat_ref.get().exists:
        raise HTTPException(status_code=404, detail="Chat not found")

    message_ref = (
        chat_ref.collection("messages").document(body.message_id)
        if body.message_id
        else chat_ref.collection("messages").document()
    )
    existing = message_ref.get()
    existing_data = (existing.to_dict() or {}) if existing.exists else {}
    now_ms = _now_ms()
    client_created_at = int(
        existing_data.get("clientCreatedAt", 0) or 0
    ) or _safe_client_created_at(body.clientCreatedAt, now_ms)
    sequence = int(existing_data.get("sequence", 0) or 0) or _safe_message_sequence(
        body.sequence,
        client_created_at,
    )
    now = gcf.SERVER_TIMESTAMP
    data_to_set = {
        "role": body.role,
        "content": body.content,
        "createdAt": now,
        "clientCreatedAt": client_created_at,
        "sequence": sequence,
    }

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
        update_values = {
            key: value
            for key, value in data_to_set.items()
            if key != "createdAt"
        }
        # Preserve immutable order fields once a message has been stored.
        if existing_data.get("clientCreatedAt") is not None:
            update_values.pop("clientCreatedAt", None)
        if existing_data.get("sequence") is not None:
            update_values.pop("sequence", None)
        message_ref.update(update_values)
    else:
        message_ref.set(data_to_set)

    chat_ref.update({"updatedAt": now})
    snapshot = message_ref.get()
    data = snapshot.to_dict() or {}
    return MessageOut(
        message_id=message_ref.id,
        role=data.get("role", body.role),
        content=data.get("content", body.content),
        createdAt=_to_ms(data.get("createdAt")),
        clientCreatedAt=(
            int(data.get("clientCreatedAt"))
            if data.get("clientCreatedAt") is not None
            else None
        ),
        sequence=(
            int(data.get("sequence"))
            if data.get("sequence") is not None
            else None
        ),
        media=data.get("media") or None,
        quizAnchor=data.get("quizAnchor") or None,
        quizTitle=data.get("quizTitle") or None,
        quizData=data.get("quizData") or None,
    )


def list_chats(uid: str, limit: int = 50):
    if DESKTOP_LOCAL_MODE:
        chats = list(_desktop_user(uid)["chats"].items())
        chats.sort(
            key=lambda item: int(
                item[1].get("updatedAt", 0) or 0
            ),
            reverse=True,
        )
        output: list[ChatItemOut] = []
        for chat_id, data in chats[:limit]:
            output.append(
                ChatItemOut(
                    chat_id=chat_id,
                    title=data.get("title", "Untitled"),
                    dts=int(data.get("updatedAt", 0) or 0),
                    sessionId=data.get("sessionId"),
                    shareable=bool(data.get("shareable", False)),
                    share_token=data.get("shareToken"),
                )
            )
        return output

    db = _get_db()
    chats_ref = db.collection("users").document(uid).collection("chats")
    query = chats_ref.order_by(
        "updatedAt",
        direction=gcf.Query.DESCENDING,
    ).limit(limit)
    output: list[ChatItemOut] = []
    for document in query.stream():
        data = document.to_dict() or {}
        output.append(
            ChatItemOut(
                chat_id=document.id,
                title=data.get("title", "Untitled"),
                dts=_to_ms(data.get("updatedAt")),
                sessionId=data.get("sessionId"),
                shareable=bool(data.get("shareable", False)),
                share_token=data.get("shareToken"),
            )
        )
    return output


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
    chat_ref = (
        db.collection("users")
        .document(uid)
        .collection("chats")
        .document()
    )
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
    snapshot = chat_ref.get()
    data = snapshot.to_dict() or {}
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
        return ArtifactRefreshOut(
            ok=True,
            artifact_id=artifactId,
            gcs_path=gcsPath,
        )

    gcs_bucket = _get_bucket_name()
    if not gcs_bucket:
        raise HTTPException(
            status_code=400,
            detail="No GCS bucket configured",
        )

    path = gcsPath
    if artifactId and not path:
        try:
            snapshot = (
                _get_db()
                .collection("users")
                .document(uid)
                .collection("artifacts")
                .document(artifactId)
                .get()
            )
            if not snapshot.exists:
                raise HTTPException(
                    status_code=404,
                    detail="Artifact not found",
                )
            document = snapshot.to_dict() or {}
            path = document.get("gcsPath")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail="Artifact lookup failed",
            ) from exc

    if not path:
        raise HTTPException(
            status_code=400,
            detail="Missing artifactId or gcsPath",
        )

    try:
        signed_main = _sign_url(gcs_bucket, path)
        signed_sub = None
        if subtitle:
            base, _extension = os.path.splitext(path)
            signed_sub = _sign_url(gcs_bucket, base + ".vtt")
        return ArtifactRefreshOut(
            ok=True,
            signed_video_url=signed_main,
            signed_subtitle_url=signed_sub,
            gcs_path=path,
            artifact_id=artifactId,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Refresh failed",
        ) from exc


def list_messages(
    chat_id: str,
    uid: str,
    limit: int = 50,
    before_ms: int | None = None,
):
    if DESKTOP_LOCAL_MODE:
        chat = _desktop_chat(uid, chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")
        messages, has_more = _paginate_messages(
            chat_id,
            uid,
            limit=limit,
            before_ms=before_ms,
        )
        return MessagesPage(messages=messages, has_more=has_more)

    chat_snapshot = _chat_doc(uid, chat_id).get()
    if not chat_snapshot.exists:
        raise HTTPException(status_code=404, detail="Chat not found")
    messages, has_more = _paginate_messages(
        chat_id,
        uid,
        limit=limit,
        before_ms=before_ms,
    )
    return MessagesPage(messages=messages, has_more=has_more)


@app.get("/api/chats/{chat_id}/export")
def export_chat(
    chat_id: str,
    uid: str = Depends(require_firebase_user),
):
    if DESKTOP_LOCAL_MODE:
        chat = _desktop_chat(uid, chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")
        messages = sorted(
            list(chat.get("messages", [])),
            key=_stored_message_sort_key,
        )
        output_messages = [
            {
                "message_id": str(message.get("message_id")),
                "role": message.get("role"),
                "content": message.get("content"),
                "createdAt": int(
                    message.get("createdAt", 0) or 0
                ),
                "clientCreatedAt": int(
                    message.get("clientCreatedAt", 0) or 0
                ) or None,
                "sequence": int(
                    message.get("sequence", 0) or 0
                ) or None,
                "media": message.get("media") or None,
            }
            for message in messages
        ]
        return {
            "chat": {
                "chat_id": chat_id,
                "title": chat.get("title", "Untitled"),
                "createdAt": int(chat.get("createdAt", 0) or 0),
                "updatedAt": int(chat.get("updatedAt", 0) or 0),
            },
            "messages": output_messages,
            "version": 1,
        }

    chat_snapshot = _chat_doc(uid, chat_id).get()
    if not chat_snapshot.exists:
        raise HTTPException(status_code=404, detail="Chat not found")
    chat_data = chat_snapshot.to_dict() or {}
    snapshots = (
        _chat_doc(uid, chat_id)
        .collection("messages")
        .order_by(
            "createdAt",
            direction=gcf.Query.ASCENDING,
        )
        .stream()
    )
    output_messages = []
    for snapshot in snapshots:
        data = snapshot.to_dict() or {}
        output_messages.append(
            {
                "message_id": snapshot.id,
                "role": data.get("role"),
                "content": data.get("content"),
                "createdAt": _to_ms(data.get("createdAt")),
                "clientCreatedAt": data.get("clientCreatedAt"),
                "sequence": data.get("sequence"),
                "media": data.get("media") or None,
            }
        )
    return {
        "chat": {
            "chat_id": chat_id,
            "title": chat_data.get("title", "Untitled"),
            "createdAt": _to_ms(chat_data.get("createdAt")),
            "updatedAt": _to_ms(chat_data.get("updatedAt")),
        },
        "messages": output_messages,
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
    snapshot = chat_ref.get()
    if not snapshot.exists:
        raise HTTPException(status_code=404, detail="Chat not found")
    now = gcf.SERVER_TIMESTAMP
    chat_ref.update({"title": body.title, "updatedAt": now})
    snapshot = chat_ref.get()
    data = snapshot.to_dict() or {}
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
    snapshot = chat_ref.get()
    if not snapshot.exists:
        raise HTTPException(status_code=404, detail="Chat not found")
    data = snapshot.to_dict() or {}
    now = gcf.SERVER_TIMESTAMP
    shareable = bool(body.shareable)
    share_token = data.get("shareToken")
    if shareable and not share_token:
        share_token = uuid4().hex[:16]
    chat_ref.update(
        {
            "shareable": shareable,
            "shareToken": share_token,
            "updatedAt": now,
        }
    )
    updated_snapshot = chat_ref.get()
    updated = updated_snapshot.to_dict() or {}
    return ChatItemOut(
        chat_id=chat_id,
        title=updated.get(
            "title",
            data.get("title", "Untitled"),
        ),
        dts=_to_ms(updated.get("updatedAt")),
        sessionId=updated.get("sessionId"),
        shareable=bool(updated.get("shareable", False)),
        share_token=updated.get("shareToken"),
    )


@app.get("/api/share/{token}", response_model=ChatDetailOut)
def get_shared_chat(
    token: str,
    limit: int = Query(500, ge=1, le=1000),
):
    if DESKTOP_LOCAL_MODE:
        for _uid, user_data in _DESKTOP_STORE.items():
            for chat_id, chat in user_data.get("chats", {}).items():
                if (
                    chat.get("shareable")
                    and chat.get("shareToken") == token
                ):
                    messages = [
                        MessageOut(
                            message_id=str(message.get("message_id")),
                            role=message.get("role", "assistant"),
                            content=message.get("content", ""),
                            createdAt=int(
                                message.get("createdAt", 0) or 0
                            ),
                            clientCreatedAt=int(
                                message.get("clientCreatedAt", 0) or 0
                            ) or None,
                            sequence=int(
                                message.get("sequence", 0) or 0
                            ) or None,
                            media=message.get("media"),
                            quizAnchor=message.get("quizAnchor"),
                            quizTitle=message.get("quizTitle"),
                            quizData=message.get("quizData"),
                        )
                        for message in sorted(
                            chat.get("messages", []),
                            key=_stored_message_sort_key,
                        )[:limit]
                    ]
                    return ChatDetailOut(
                        chat_id=chat_id,
                        title=chat.get("title", "Untitled"),
                        dts=int(chat.get("updatedAt", 0) or 0),
                        sessionId=chat.get("sessionId"),
                        messages=messages,
                        shareable=True,
                        share_token=token,
                        model=chat.get("model"),
                    )
        raise HTTPException(
            status_code=404,
            detail="Shared chat not found",
        )

    db = _get_db()
    try:
        query = (
            db.collection_group("chats")
            .where("shareToken", "==", token)
            .limit(1)
        )
        documents = list(query.stream())
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Share lookup failed",
        ) from exc

    if not documents:
        raise HTTPException(
            status_code=404,
            detail="Shared chat not found",
        )
    document = documents[0]
    chat_data = document.to_dict() or {}
    if not chat_data.get("shareable"):
        raise HTTPException(
            status_code=404,
            detail="Shared chat not found",
        )

    chat_id = document.id
    message_snapshots = (
        document.reference.collection("messages")
        .order_by(
            "createdAt",
            direction=gcf.Query.ASCENDING,
        )
        .limit(limit)
        .stream()
    )
    messages: list[MessageOut] = []
    for snapshot in message_snapshots:
        data = snapshot.to_dict() or {}
        messages.append(
            MessageOut(
                message_id=snapshot.id,
                role=data.get("role", "assistant"),
                content=data.get("content", ""),
                createdAt=_to_ms(data.get("createdAt")),
                clientCreatedAt=(
                    int(data.get("clientCreatedAt"))
                    if data.get("clientCreatedAt") is not None
                    else None
                ),
                sequence=(
                    int(data.get("sequence"))
                    if data.get("sequence") is not None
                    else None
                ),
                media=data.get("media") or None,
                quizAnchor=data.get("quizAnchor") or None,
                quizTitle=data.get("quizTitle") or None,
                quizData=data.get("quizData") or None,
            )
        )
    messages.sort(
        key=lambda message: (
            int(message.createdAt or 0),
            int(message.sequence or 0),
            message.message_id,
        )
    )
    return ChatDetailOut(
        chat_id=chat_id,
        title=chat_data.get("title", "Untitled"),
        dts=_to_ms(chat_data.get("updatedAt")),
        sessionId=chat_data.get("sessionId"),
        messages=messages,
        shareable=True,
        share_token=token,
        model=chat_data.get("model"),
    )


@app.get("/api/chats", response_model=list[ChatItemOut])
def list_chats_route(
    limit: int = Query(50, ge=1, le=200),
    uid: str = Depends(require_firebase_user),
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
            append_message(
                result.chat_id,
                MessageCreateIn(role="user", content=body.content),
                uid,
            )
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


@app.post("/api/chats/{chat_id}", response_model=MessageOut)
def continue_chat_route(
    chat_id: str,
    body: MessageCreateIn,
    uid: str = Depends(require_firebase_user),
    x_session_id: str | None = Header(None, alias="X-Session-ID"),
    idempotency_key: str | None = Header(
        None,
        alias="Idempotency-Key",
    ),
):
    if idempotency_key and not body.message_id:
        body.message_id = idempotency_key
    return append_message(chat_id, body, uid)


@app.get(
    "/api/chats/{chat_id}/messages",
    response_model=MessagesPage,
)
def list_messages_route(
    chat_id: str,
    uid: str = Depends(require_firebase_user),
    limit: int = Query(50, ge=1, le=200),
    before: int | None = Query(None),
):
    return list_messages(chat_id, uid, limit, before)


@app.patch("/api/chats/{chat_id}", response_model=ChatItemOut)
def rename_chat_route(
    chat_id: str,
    body: ChatRenameIn,
    uid: str = Depends(require_firebase_user),
):
    return rename_chat(chat_id, body, uid)


@app.delete("/api/chats/{chat_id}")
def delete_chat_route(
    chat_id: str,
    uid: str = Depends(require_firebase_user),
):
    return _delete_chat_impl(chat_id, uid)


@app.delete("/api/account")
def delete_account_route(
    uid: str = Depends(require_firebase_user),
):
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
    snapshot = chat_ref.get()
    if not snapshot.exists:
        raise HTTPException(status_code=404, detail="Chat not found")

    db = _get_db()
    batch = db.batch()
    messages = chat_ref.collection("messages").stream()
    count = 0
    for message in messages:
        batch.delete(message.reference)
        count += 1
    batch.delete(chat_ref)
    batch.commit()

    gcs_bucket = _get_bucket_name()
    gcs_deleted = 0
    if gcs_bucket:
        try:
            gcs_deleted = _delete_folder(
                gcs_bucket,
                f"{uid}/chats/{chat_id}/",
            )
        except Exception as exc:
            logger.warning(
                "Failed to delete GCS folder for chat %s: %s",
                chat_id,
                exc,
            )
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
            "messages_removed": sum(
                len(chat.get("messages", []))
                for chat in chats
            ),
            "artifacts_removed": 0,
            "gcs_files_removed": 0,
        }

    db = _get_db()

    def delete_collection(collection_ref, batch_size=500):
        deleted = 0
        documents = collection_ref.limit(batch_size).stream()
        deleted_batch = 0
        for document in documents:
            document.reference.delete()
            deleted += 1
            deleted_batch += 1
        if deleted_batch >= batch_size:
            return deleted + delete_collection(
                collection_ref,
                batch_size,
            )
        return deleted

    total_chats = 0
    total_messages = 0
    chats_ref = db.collection("users").document(uid).collection("chats")
    chats = list(chats_ref.stream())
    for chat in chats:
        total_messages += delete_collection(
            chat.reference.collection("messages")
        )
        chat.reference.delete()
        total_chats += 1

    artifacts_ref = (
        db.collection("users")
        .document(uid)
        .collection("artifacts")
    )
    total_artifacts = delete_collection(artifacts_ref)

    total_gcs_files = 0
    gcs_bucket = _get_bucket_name()
    if gcs_bucket:
        try:
            total_gcs_files = _delete_folder(gcs_bucket, f"{uid}/")
            _delete_folder(gcs_bucket, f"{uid}/chats/")
        except Exception as exc:
            logger.warning(
                "Failed to delete GCS folder for user %s: %s",
                uid,
                exc,
            )

    try:
        user_ref = db.collection("users").document(uid)
        user_document = user_ref.get()
        if user_document.exists:
            user_ref.delete()
    except Exception as exc:
        logger.error(
            "Failed to delete Firestore user document for %s: %s",
            uid,
            exc,
        )

    return {
        "ok": True,
        "uid": uid,
        "chats_removed": total_chats,
        "messages_removed": total_messages,
        "artifacts_removed": total_artifacts,
        "gcs_files_removed": total_gcs_files,
    }


@app.post("/api/media/burn-captions")
def burn_captions_video(
    body: BurnCaptionsIn,
    uid: str = Depends(require_firebase_user),
):
    if not body.video_url or not str(body.video_url).strip():
        raise HTTPException(
            status_code=400,
            detail="video_url is required",
        )

    if not (
        body.subtitle_text and body.subtitle_text.strip()
    ) and not (
        body.subtitle_url and str(body.subtitle_url).strip()
    ):
        raise HTTPException(
            status_code=400,
            detail="subtitle_url or subtitle_text is required",
        )

    export_id = f"burn_{uuid4().hex[:8]}"
    job_dir = pathlib.Path(STORAGE) / "jobs" / export_id
    logs_dir = job_dir / "logs"
    output_path = job_dir / "video_captions.mp4"
    tmp_dir = pathlib.Path(
        tempfile.mkdtemp(prefix="upcurved_burn_")
    )

    try:
        job_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)

        video_path = _download_url_to_file(
            str(body.video_url),
            tmp_dir / "source.mp4",
        )
        subtitle_path = _materialize_caption_file(
            subtitle_url=(
                str(body.subtitle_url)
                if body.subtitle_url
                else None
            ),
            subtitle_text=body.subtitle_text,
            tmp_dir=tmp_dir,
        )

        _burn_captions_with_ffmpeg(
            video_path=video_path,
            subtitle_path=subtitle_path,
            output_path=output_path,
            logs_dir=logs_dir,
        )

        filename = _safe_media_filename(
            body.filename,
            "upcurved_video_captions.mp4",
        )
        download_url = to_static_url(output_path)
        signed_video_url = None
        gcs_path = None
        artifact_id = None

        gcs_bucket = _get_bucket_name()
        if gcs_bucket:
            data = output_path.read_bytes()
            chat_path = body.chatId or "uncategorized"
            gcs_path = (
                f"{uid}/chats/{chat_path}/"
                f"video_{export_id}_captions.mp4"
            )
            _upload_bytes(
                gcs_bucket,
                gcs_path,
                data,
                "video/mp4",
            )
            signed_video_url = _sign_url(gcs_bucket, gcs_path)
            artifact_id = _save_artifact(
                uid,
                body.chatId,
                "video",
                gcs_path,
                len(data),
                "video/mp4",
                derived=True,
            )
            download_url = signed_video_url

        return {
            "ok": True,
            "status": "ok",
            "download_url": download_url,
            "signed_video_url": signed_video_url,
            "filename": filename,
            "job_id": export_id,
            "artifact_id": artifact_id,
            "gcs_path": gcs_path,
            "message": "Captioned video created.",
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "/api/media/burn-captions failed: %s",
            exc,
        )
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.post("/api/media/audio-package")
def audio_package(
    body: AudioPackageIn,
    uid: str = Depends(require_firebase_user),
):
    if not body.audio_url or not str(body.audio_url).strip():
        raise HTTPException(
            status_code=400,
            detail="audio_url is required",
        )

    if not (
        body.subtitle_text and body.subtitle_text.strip()
    ) and not (
        body.subtitle_url and str(body.subtitle_url).strip()
    ):
        raise HTTPException(
            status_code=400,
            detail="subtitle_url or subtitle_text is required",
        )

    export_id = f"audio_pkg_{uuid4().hex[:8]}"
    job_dir = pathlib.Path(STORAGE) / "jobs" / export_id
    output_path = job_dir / "podcast_package.zip"
    tmp_dir = pathlib.Path(
        tempfile.mkdtemp(prefix="upcurved_audio_pkg_")
    )

    try:
        job_dir.mkdir(parents=True, exist_ok=True)

        audio_path = _download_url_to_file(
            str(body.audio_url),
            tmp_dir / "podcast.mp3",
        )
        caption_path = _materialize_caption_file(
            subtitle_url=(
                str(body.subtitle_url)
                if body.subtitle_url
                else None
            ),
            subtitle_text=body.subtitle_text,
            tmp_dir=tmp_dir,
        )
        raw_caption_text = caption_path.read_text(
            encoding="utf-8",
            errors="ignore",
        )
        vtt_text = _caption_text_to_vtt(raw_caption_text)
        transcript_text = _caption_text_to_transcript(vtt_text)
        if not transcript_text.strip():
            transcript_text = (
                "Transcript could not be extracted from the caption file.\n"
            )

        base_filename = _safe_filename_with_extension(
            body.filename,
            "upcurved_podcast_package.zip",
            ".zip",
        )
        audio_suffix = audio_path.suffix.lower() or ".mp3"
        if audio_suffix not in {
            ".mp3",
            ".m4a",
            ".wav",
            ".aac",
            ".ogg",
        }:
            audio_suffix = ".mp3"

        with zipfile.ZipFile(
            output_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as zip_file:
            zip_file.write(
                audio_path,
                arcname=f"podcast{audio_suffix}",
            )
            zip_file.writestr("captions.vtt", vtt_text)
            zip_file.writestr("transcript.txt", transcript_text)

        download_url = to_static_url(output_path)
        signed_url = None
        gcs_path = None
        artifact_id = None

        gcs_bucket = _get_bucket_name()
        if gcs_bucket:
            data = output_path.read_bytes()
            chat_path = body.chatId or "uncategorized"
            gcs_path = (
                f"{uid}/chats/{chat_path}/exports/"
                f"{export_id}_{base_filename}"
            )
            _upload_bytes(
                gcs_bucket,
                gcs_path,
                data,
                "application/zip",
            )
            signed_url = _sign_url(gcs_bucket, gcs_path)
            artifact_id = _save_artifact(
                uid,
                body.chatId,
                "audio_package",
                gcs_path,
                len(data),
                "application/zip",
                derived=True,
            )
            download_url = signed_url

        return {
            "ok": True,
            "status": "ok",
            "download_url": download_url,
            "signed_download_url": signed_url,
            "filename": base_filename,
            "job_id": export_id,
            "artifact_id": artifact_id,
            "gcs_path": gcs_path,
            "message": "Podcast package created.",
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "/api/media/audio-package failed: %s",
            exc,
        )
        return diagnostic_error_response(
            feature="podcast",
            step="audio package download",
            error=exc,
            status_code=500,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _to_ms(timestamp) -> int | None:
    try:
        if timestamp is None:
            return None
        if isinstance(timestamp, (int, float)):
            return int(timestamp)
        seconds = getattr(timestamp, "seconds", None)
        nanoseconds = getattr(timestamp, "nanoseconds", 0)
        if seconds is None:
            return None
        return int(seconds * 1000 + nanoseconds / 1_000_000)
    except Exception:
        return None


@app.post("/jobs/cancel")
def jobs_cancel(jobId: str = Query(...)):
    try:
        return cancel_job(jobId)
    except Exception as exc:
        logger.exception("/jobs/cancel failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
