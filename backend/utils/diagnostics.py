# backend/utils/diagnostics.py
"""Small helpers for consistent generation/edit diagnostics responses.

This module keeps full tracebacks in backend logs, but returns short,
teacher-friendly error messages to the frontend.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse


_MAX_PUBLIC_REASON_CHARS = 240


@dataclass
class DiagnosticError(RuntimeError):
    """Exception that carries a user-safe diagnostic step."""

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
    """Pull a clean message out of strings like 'API error 400: { ... }'."""
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
        message = parsed.get("message") or parsed.get("detail")
        if message:
            return str(message)

    return text


def _remove_sensitive_tokens(text: str) -> str:
    """Remove IDs / raw JSON fragments that should not appear in chat bubbles."""
    text = re.sub(r'"user_id"\s*:\s*"[^"]+"', '"user_id":"hidden"', text)
    text = re.sub(r"user_[A-Za-z0-9_-]+", "user_hidden", text)
    text = re.sub(r"sk-[A-Za-z0-9_-]+", "sk_hidden", text)
    return text


def public_error_message(error: Any) -> str:
    """Return a short, user-facing reason for a diagnostic response.

    Full raw errors should still be logged with logger.exception(...) at the
    call site. This value is meant for the chat UI.
    """
    text = _stringify_error(error).strip()
    if not text:
        return "Something went wrong while generating this artifact. Try again or switch models."

    text = _extract_json_error_message(text)
    text = _remove_sensitive_tokens(text).strip()

    lowered = text.lower()

    if "input must have at least 1 token" in lowered:
        return "The model received an empty prompt. Try again or switch models."

    if "keyerror" in lowered and "choices" in lowered:
        return "The model provider returned an unexpected response. Try again or switch models."

    if "missing choices" in lowered or "did not return choices" in lowered:
        return "The model provider returned an unexpected response. Try again or switch models."

    if "complete html document" in lowered or "incomplete html" in lowered:
        return "The model returned an incomplete HTML file. Try again or switch models."

    if "json" in lowered and ("parse" in lowered or "decode" in lowered or "invalid" in lowered):
        return "The model returned malformed JSON. Try again or switch models."

    if "rate limit" in lowered or "too many requests" in lowered or "429" in lowered:
        return "The model provider is rate-limiting requests. Wait a moment or switch models."

    if "unauthorized" in lowered or "invalid api key" in lowered or "401" in lowered:
        return "The API key was rejected. Check the key in Settings."

    if "forbidden" in lowered or "403" in lowered:
        return "The model provider blocked this request. Try a different model or rephrase the prompt."

    if "timeout" in lowered or "timed out" in lowered:
        return "The request took too long. Try again or switch models."

    if "ffmpeg" in lowered:
        return "The media export step failed. Try again, or check the backend terminal for details."

    # Collapse whitespace and keep the bubble readable.
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
    """Return a JSONResponse with a consistent generation diagnostics shape."""
    if status_code is None:
        if isinstance(error, DiagnosticError):
            status_code = error.status_code
        elif isinstance(error, HTTPException):
            status_code = int(getattr(error, "status_code", 500) or 500)
        else:
            status_code = 500
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
