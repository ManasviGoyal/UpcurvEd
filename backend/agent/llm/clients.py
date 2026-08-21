# backend/agent/llm/clients.py
from __future__ import annotations

import base64
import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator

import requests

from backend.agent.llm.provider_config import (
    ProviderName,
    default_openai_model,
    default_openrouter_model,
    get_default_model,
)

Provider = ProviderName


class LLMError(RuntimeError):
    pass


@dataclass
class LLMCallCounter:
    """Request-local count of attempted model calls."""

    count: int = 0


_ACTIVE_LLM_CALL_COUNTER: ContextVar[LLMCallCounter | None] = ContextVar(
    "upcurved_llm_call_counter",
    default=None,
)


@contextmanager
def track_llm_calls() -> Iterator[LLMCallCounter]:
    """Track every ``call_llm`` invocation in the current request context."""
    counter = LLMCallCounter()
    token = _ACTIVE_LLM_CALL_COUNTER.set(counter)
    try:
        yield counter
    finally:
        _ACTIVE_LLM_CALL_COUNTER.reset(token)


def _record_llm_call() -> None:
    counter = _ACTIVE_LLM_CALL_COUNTER.get()
    if counter is not None:
        counter.count += 1


def _require_prompt(user: str) -> str:
    text = str(user or "").strip()
    if not text:
        raise LLMError("Prompt is empty.")
    return text


def _normalize_images(images: list[dict[str, str]] | None) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for index, image in enumerate(images or [], start=1):
        if not isinstance(image, dict):
            raise LLMError(f"Image {index} is invalid.")
        data_url = str(image.get("data_url") or image.get("dataUrl") or "").strip()
        mime_type = str(image.get("mime_type") or image.get("mimeType") or "").strip().lower()
        if not data_url or not mime_type:
            raise LLMError(f"Image {index} is missing data or MIME type.")
        output.append({"data_url": data_url, "mime_type": mime_type})
    return output


def _base64_bytes_from_data_url(data_url: str, expected_mime: str) -> bytes:
    match = re.fullmatch(
        r"data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=\r\n]+)",
        str(data_url or "").strip(),
        flags=re.IGNORECASE,
    )
    if not match:
        raise LLMError("Image data URL is invalid.")
    mime_type = match.group(1).lower()
    if expected_mime and mime_type != str(expected_mime).lower():
        raise LLMError("Image MIME type does not match its data URL.")
    try:
        payload = re.sub(r"\s+", "", match.group(2))
        return base64.b64decode(payload, validate=True)
    except Exception as exc:
        raise LLMError("Image contains invalid base64 data.") from exc


def _base64_payload_from_data_url(data_url: str, expected_mime: str) -> str:
    raw = _base64_bytes_from_data_url(data_url, expected_mime)
    return base64.b64encode(raw).decode("ascii")


def _json_error_message(
    data: object,
    *,
    fallback: str,
) -> str:
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("code") or error.get("type")
            if message:
                return str(message)
        elif isinstance(error, str) and error.strip():
            return error.strip()

        message = data.get("message") or data.get("detail")
        if message:
            return str(message)
    return fallback


# ---------- OpenRouter ----------
def _call_openrouter(
    api_key: str,
    model: str | None,
    system: str | None,
    user: str,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    images: list[dict[str, str]] | None = None,
) -> str:
    model = str(model or default_openrouter_model()).strip()
    prompt = _require_prompt(user)
    image_list = _normalize_images(images)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.environ.get(
            "OPENROUTER_HTTP_REFERER",
            "http://localhost:8080",
        ),
        "X-OpenRouter-Title": os.environ.get(
            "OPENROUTER_APP_TITLE",
            "UpcurvEd",
        ),
    }

    messages: list[dict[str, Any]] = []
    if system and str(system).strip():
        messages.append({"role": "system", "content": str(system)})
    if image_list:
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        content.extend(
            {"type": "image_url", "image_url": {"url": image["data_url"]}}
            for image in image_list
        )
        messages.append({"role": "user", "content": content})
    else:
        messages.append({"role": "user", "content": prompt})

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = int(max_tokens)

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=float(os.environ.get("OPENROUTER_TIMEOUT_SECONDS", "120")),
    )

    try:
        data = response.json()
    except Exception:
        data = None

    if response.status_code >= 400:
        detail = _json_error_message(
            data,
            fallback=response.text[:800] or "OpenRouter request failed.",
        )
        raise RuntimeError(f"OpenRouter API error {response.status_code}: {detail}")

    if not isinstance(data, dict):
        raise RuntimeError(
            f"OpenRouter returned non-JSON response: {response.text[:300]}"
        )

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        detail = _json_error_message(
            data,
            fallback="OpenRouter returned an unexpected response.",
        )
        raise RuntimeError(
            f"OpenRouter response missing choices. Model: {model}. Reason: {detail}"
        )

    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first, dict) else {}
    content = ""
    if isinstance(message, dict):
        content = str(message.get("content") or "")
    elif isinstance(first, dict):
        content = str(first.get("text") or "")

    if not content.strip():
        finish = first.get("finish_reason") if isinstance(first, dict) else None
        raise RuntimeError(
            f"OpenRouter returned empty content. Model: {model}. finish_reason={finish}"
        )

    return content


# ---------- OpenAI ----------
def _extract_openai_response_text(data: object) -> str:
    if not isinstance(data, dict):
        return ""

    direct = data.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    parts: list[str] = []
    output = data.get("output")
    if not isinstance(output, list):
        return ""

    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") not in {"output_text", "text"}:
                continue
            text = block.get("text")
            if isinstance(text, str) and text:
                parts.append(text)
    return "\n".join(parts).strip()


def _call_openai(
    api_key: str,
    model: str | None,
    system: str | None,
    user: str,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    images: list[dict[str, str]] | None = None,
) -> str:
    """Call the direct OpenAI Responses API without adding an SDK dependency."""
    model = str(model or default_openai_model()).strip()
    prompt = _require_prompt(user)
    image_list = _normalize_images(images)

    if image_list:
        content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
        content.extend(
            {"type": "input_image", "image_url": image["data_url"], "detail": "auto"}
            for image in image_list
        )
        input_value: Any = [{"role": "user", "content": content}]
    else:
        input_value = prompt

    payload: dict[str, Any] = {
        "model": model,
        "input": input_value,
    }
    if system and str(system).strip():
        payload["instructions"] = str(system)
    if max_tokens is not None:
        payload["max_output_tokens"] = int(max_tokens)

    if model.startswith("gpt-5"):
        if not model.endswith("-pro"):
            payload["reasoning"] = {
                "effort": os.environ.get("OPENAI_REASONING_EFFORT", "none")
            }
    else:
        payload["temperature"] = float(temperature)

    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=float(os.environ.get("OPENAI_TIMEOUT_SECONDS", "180")),
    )

    try:
        data = response.json()
    except Exception:
        data = None

    if response.status_code >= 400:
        detail = _json_error_message(
            data,
            fallback=response.text[:800] or "OpenAI request failed.",
        )
        raise RuntimeError(f"OpenAI API error {response.status_code}: {detail}")

    if not isinstance(data, dict):
        raise RuntimeError(f"OpenAI returned non-JSON response: {response.text[:300]}")

    text = _extract_openai_response_text(data)
    if not text:
        status = data.get("status")
        incomplete = data.get("incomplete_details")
        refusal = data.get("refusal")
        detail = refusal or incomplete or status or "No output_text content was returned."
        raise RuntimeError(
            f"OpenAI returned empty content. Model: {model}. Reason: {detail}"
        )
    return text


# ---------- Anthropic (Claude) ----------
def call_claude(
    api_key: str,
    model: str,
    system: str | None,
    user: str,
    max_tokens: int = 2048,
    temperature: float = 0.2,
    images: list[dict[str, str]] | None = None,
) -> str:
    """Use Anthropic's official SDK and return concatenated text blocks."""
    try:
        try:
            import anthropic
        except Exception as exc:
            raise LLMError(
                "Claude SDK is not installed. Install 'anthropic' to use Claude."
            ) from exc

        prompt = _require_prompt(user)
        image_list = _normalize_images(images)
        if image_list:
            content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
            for image in image_list:
                content.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": image["mime_type"],
                            "data": _base64_payload_from_data_url(
                                image["data_url"], image["mime_type"]
                            ),
                        },
                    }
                )
            user_content: Any = content
        else:
            user_content = prompt

        client = anthropic.Anthropic(api_key=api_key)
        # Anthropic SDK v1 removed direct sampling parameters such as
        # ``temperature`` from Messages.create(). Keep ``temperature`` in this
        # wrapper's signature so the shared call_llm interface stays stable,
        # but do not forward it to Claude.
        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system or "",
            messages=[{"role": "user", "content": user_content}],
        )
        out_parts: list[str] = []
        for block in message.content or []:
            if getattr(block, "type", None) == "text":
                out_parts.append(getattr(block, "text", "") or "")
            elif isinstance(block, dict) and block.get("type") == "text":
                out_parts.append(str(block.get("text") or ""))
        text = "".join(out_parts).strip()
        if not text:
            raise LLMError("Claude returned empty text.")
        return text
    except Exception as exc:
        if isinstance(exc, LLMError):
            raise
        raise LLMError(f"Claude SDK error: {exc}") from exc


# ---------- Google (Gemini) ----------
def _with_genai_key(api_key: str) -> None:
    try:
        import google.generativeai as genai
    except Exception as exc:
        raise LLMError(
            "Gemini SDK is not installed. Install 'google-generativeai' to use Gemini."
        ) from exc
    genai.configure(api_key=api_key)


def call_gemini(
    api_key: str,
    model: str,
    system: str | None,
    user: str,
    max_output_tokens: int = 8192,
    temperature: float = 0.2,
    images: list[dict[str, str]] | None = None,
) -> str:
    """Use Google's official google-generativeai SDK."""
    try:
        try:
            import google.generativeai as genai
        except Exception as exc:
            raise LLMError(
                "Gemini SDK is not installed. Install 'google-generativeai' to use Gemini."
            ) from exc

        prompt = _require_prompt(user)
        image_list = _normalize_images(images)
        _with_genai_key(api_key)
        safety_settings = {
            "HARM_CATEGORY_HARASSMENT": "BLOCK_NONE",
            "HARM_CATEGORY_HATE_SPEECH": "BLOCK_NONE",
            "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_NONE",
            "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_NONE",
        }
        model_client = genai.GenerativeModel(
            model,
            system_instruction=(system or None),
            generation_config={
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
            },
            safety_settings=safety_settings,
        )
        if image_list:
            content: list[Any] = [prompt]
            for image in image_list:
                content.append(
                    {
                        "mime_type": image["mime_type"],
                        "data": _base64_bytes_from_data_url(
                            image["data_url"], image["mime_type"]
                        ),
                    }
                )
            response = model_client.generate_content(content)
        else:
            response = model_client.generate_content(prompt)

        try:
            text = (response.text or "").strip()
        except Exception:
            text = ""

        if not text:
            try:
                candidates = getattr(response, "candidates", []) or []
                parts: list[str] = []
                for candidate in candidates:
                    content_obj = getattr(candidate, "content", None)
                    if not content_obj and isinstance(candidate, dict):
                        content_obj = candidate.get("content")
                    if content_obj is None:
                        continue
                    content_parts = getattr(content_obj, "parts", None)
                    if content_parts is None and isinstance(content_obj, dict):
                        content_parts = content_obj.get("parts")
                    for part in content_parts or []:
                        value = getattr(part, "text", None)
                        if value is None and isinstance(part, dict):
                            value = part.get("text")
                        if value:
                            parts.append(str(value))
                text = "\n".join(parts).strip()
            except Exception:
                text = ""

        if not text:
            finish = None
            try:
                if getattr(response, "candidates", None):
                    finish = getattr(response.candidates[0], "finish_reason", None)
            except Exception:
                pass
            prompt_feedback = getattr(response, "prompt_feedback", None)
            error_message = f"Gemini returned empty text. finish_reason={finish}"
            if finish == 2:
                error_message = (
                    "Gemini blocked the content due to safety filters. "
                    "Try rephrasing your prompt or switch models."
                )
            elif prompt_feedback:
                error_message += f", prompt_feedback={prompt_feedback}"
            raise LLMError(error_message)
        return text
    except Exception as exc:
        if isinstance(exc, LLMError):
            raise
        raise LLMError(f"Gemini SDK error: {exc}") from exc


# ---------- Unified entrypoint ----------
def call_llm(
    provider: Provider,
    api_key: str,
    model: str | None,
    system: str | None,
    user: str,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    max_output_tokens: int | None = None,
    images: list[dict[str, str]] | None = None,
) -> str:
    """Dispatch to the selected provider using centralized model defaults."""
    resolved_model = str(model or get_default_model(provider) or "").strip()
    output_limit = max_tokens or max_output_tokens
    _record_llm_call()

    if provider == "claude":
        return call_claude(
            api_key=api_key,
            model=resolved_model,
            system=system,
            user=user,
            temperature=temperature,
            max_tokens=output_limit or 2048,
            images=images,
        )
    if provider == "gemini":
        return call_gemini(
            api_key=api_key,
            model=resolved_model,
            system=system,
            user=user,
            temperature=temperature,
            max_output_tokens=output_limit or 8192,
            images=images,
        )
    if provider == "openai":
        return _call_openai(
            api_key=api_key,
            model=resolved_model,
            system=system,
            user=user,
            temperature=temperature,
            max_tokens=output_limit,
            images=images,
        )
    if provider == "openrouter":
        return _call_openrouter(
            api_key=api_key,
            model=resolved_model,
            system=system,
            user=user,
            temperature=temperature,
            max_tokens=output_limit,
            images=images,
        )
    raise LLMError(f"Unknown provider: {provider}")
