"""Consistent, user-safe diagnostics for generation and editing failures.

Call sites should continue logging full exceptions with ``logger.exception``.
This module converts raw provider/render/export errors into concise messages
and structured metadata that the frontend can display safely.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse


_MAX_PUBLIC_REASON_CHARS = 240

_CAPACITY_PHRASES = (
    "resourceexhausted",
    "resource exhausted",
    "request limit reached",
    "worker local total request limit reached",
    "upstream capacity",
    "model is overloaded",
    "temporarily overloaded",
    "temporarily unavailable",
    "no available providers",
    "provider unavailable",
    "service unavailable",
)

_RATE_LIMIT_PHRASES = (
    "rate limit",
    "rate-limit",
    "too many requests",
    "quota exceeded",
    "429",
)

_TIMEOUT_PHRASES = (
    "timeout",
    "timed out",
    "deadline exceeded",
    "gateway timeout",
)


@dataclass
class DiagnosticError(RuntimeError):
    """Exception carrying a user-safe diagnostic context."""

    message: str
    feature: str | None = None
    step: str | None = None
    provider: str | None = None
    model: str | None = None
    status_code: int = 500

    def __str__(self) -> str:
        return self.message


def _stringify_error(error: Any) -> str:
    if isinstance(error, HTTPException):
        detail = getattr(error, "detail", None)
        if isinstance(detail, str):
            return detail
        if detail is not None:
            return str(detail)
    if isinstance(error, DiagnosticError):
        return str(error)
    if isinstance(error, str):
        return error
    msg = str(error or "").strip()
    return msg or type(error).__name__


def _extract_json_error_message(text: str) -> str:
    """Pull a clean message out of strings like ``API error 400: {...}``."""
    start = text.find("{")
    if start < 0:
        return text

    candidate = text[start:].strip()
    try:
        parsed = json.loads(candidate)
    except Exception:
        return text

    if isinstance(parsed, dict):
        error = parsed.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("code")
            if message:
                return str(message)
        elif isinstance(error, str) and error.strip():
            return error.strip()

        message = parsed.get("message") or parsed.get("detail")
        if message:
            return str(message)

    return text


def _remove_sensitive_tokens(text: str) -> str:
    """Remove IDs, credentials, and raw tokens from public messages."""
    text = re.sub(r'"user_id"\s*:\s*"[^"]+"', '"user_id":"hidden"', text)
    text = re.sub(r"user_[A-Za-z0-9_-]+", "user_hidden", text)
    text = re.sub(r"sk-[A-Za-z0-9_-]+", "sk_hidden", text)
    text = re.sub(
        r"(?i)(api[_ -]?key\s*[:=]\s*)[A-Za-z0-9._-]+",
        r"\1hidden",
        text,
    )
    return text


def diagnostic_category(error: Any) -> str:
    """Classify an error without exposing its raw contents to the frontend."""
    lowered = _stringify_error(error).lower()

    # Capacity must be checked before the generic "missing choices" case,
    # because OpenRouter may wrap an upstream capacity error that way.
    if any(phrase in lowered for phrase in _CAPACITY_PHRASES):
        return "provider_capacity"

    if any(phrase in lowered for phrase in _RATE_LIMIT_PHRASES):
        return "rate_limit"

    if "unauthorized" in lowered or "invalid api key" in lowered or "401" in lowered:
        return "authentication"

    if "forbidden" in lowered or "403" in lowered:
        return "provider_blocked"

    if any(phrase in lowered for phrase in _TIMEOUT_PHRASES):
        return "timeout"

    if "input must have at least 1 token" in lowered or "empty prompt" in lowered:
        return "empty_prompt"

    if "complete html document" in lowered or "incomplete html" in lowered:
        return "incomplete_html"

    if "json" in lowered and (
        "parse" in lowered
        or "decode" in lowered
        or "invalid" in lowered
        or "malformed" in lowered
    ):
        return "malformed_json"

    if "missing choices" in lowered or "did not return choices" in lowered:
        return "unexpected_provider_response"

    if "keyerror" in lowered and "choices" in lowered:
        return "unexpected_provider_response"

    if "ffmpeg" in lowered:
        return "media_export"

    if "manim" in lowered or "render" in lowered:
        return "render"

    return "unknown"


def diagnostic_retryable(error: Any) -> bool:
    return diagnostic_category(error) in {
        "provider_capacity",
        "rate_limit",
        "timeout",
        "unexpected_provider_response",
    }


def diagnostic_status_code(error: Any) -> int:
    """Select an HTTP status that reflects the underlying failure."""
    if isinstance(error, DiagnosticError):
        return int(error.status_code or 500)

    if isinstance(error, HTTPException):
        return int(getattr(error, "status_code", 500) or 500)

    category = diagnostic_category(error)
    if category == "provider_capacity":
        return 503
    if category == "rate_limit":
        return 429
    if category == "authentication":
        return 401
    if category == "provider_blocked":
        return 403
    if category == "timeout":
        return 504
    if category == "empty_prompt":
        return 400
    return 500


def public_error_message(error: Any) -> str:
    """Return a concise, safe reason suitable for a chat bubble."""
    text = _stringify_error(error).strip()
    if not text:
        return "Something went wrong while generating this artifact. Try again or switch models."

    text = _extract_json_error_message(text)
    text = _remove_sensitive_tokens(text).strip()
    category = diagnostic_category(text)

    messages = {
        "provider_capacity": (
            "The selected model is temporarily at capacity. "
            "Try again in a moment or switch models."
        ),
        "rate_limit": (
            "The model provider is rate-limiting requests. "
            "Wait a moment or switch models."
        ),
        "authentication": "The API key was rejected. Check the key in Settings.",
        "provider_blocked": (
            "The model provider blocked this request. "
            "Try a different model or rephrase the prompt."
        ),
        "timeout": "The request took too long. Try again or switch models.",
        "empty_prompt": "The model received an empty prompt. Try again.",
        "unexpected_provider_response": (
            "The model provider returned an unexpected response. "
            "Try again or switch models."
        ),
        "incomplete_html": (
            "The model returned an incomplete HTML file. "
            "Try again or switch models."
        ),
        "malformed_json": (
            "The model returned malformed JSON. "
            "Try again or switch models."
        ),
        "media_export": (
            "The media export step failed. "
            "Try again, or check the backend terminal for details."
        ),
        "render": (
            "The video could not be rendered. "
            "Try again, or check the backend terminal for the failed scene."
        ),
    }
    if category in messages:
        return messages[category]

    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > _MAX_PUBLIC_REASON_CHARS:
        text = text[:_MAX_PUBLIC_REASON_CHARS].rstrip() + "…"
    return text


def diagnostic_payload(
    *,
    feature: str,
    step: str,
    error: Any,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Return the standard frontend-consumable diagnostics envelope."""
    if isinstance(error, DiagnosticError):
        feature = error.feature or feature
        step = error.step or step
        provider = error.provider or provider
        model = error.model or model

    category = diagnostic_category(error)
    reason = public_error_message(error)
    return {
        "ok": False,
        "status": "error",
        "error": reason,
        "message": reason,
        "diagnostics": {
            "feature": feature,
            "step": step,
            "provider": provider,
            "model": model,
            "category": category,
            "retryable": diagnostic_retryable(error),
        },
    }


def diagnostic_error_response(
    *,
    feature: str,
    step: str,
    error: Any,
    provider: str | None = None,
    model: str | None = None,
    status_code: int | None = None,
) -> JSONResponse:
    """Return a JSON response with a consistent diagnostics shape."""
    if status_code is None:
        status_code = diagnostic_status_code(error)

    return JSONResponse(
        status_code=status_code,
        content=diagnostic_payload(
            feature=feature,
            step=step,
            error=error,
            provider=provider,
            model=model,
        ),
    )
