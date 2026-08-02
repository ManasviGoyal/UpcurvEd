# backend/agent/llm/clients.py
from __future__ import annotations

import os
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
) -> str:
    model = str(model or default_openrouter_model()).strip()
    prompt = _require_prompt(user)

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

    messages: list[dict[str, str]] = []
    if system and str(system).strip():
        messages.append({"role": "system", "content": str(system)})
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
) -> str:
    """Call the direct OpenAI Responses API without adding an SDK dependency."""
    model = str(model or default_openai_model()).strip()
    prompt = _require_prompt(user)

    payload: dict[str, Any] = {
        "model": model,
        "input": prompt,
    }
    if system and str(system).strip():
        payload["instructions"] = str(system)
    if max_tokens is not None:
        payload["max_output_tokens"] = int(max_tokens)

    # Current GPT-5-family models expose an explicit no-reasoning mode. Keeping
    # reasoning off is appropriate for UpcurvEd's format-sensitive generation
    # calls and avoids spending output budget on hidden reasoning.
    if model.startswith("gpt-5"):
        # The -pro variants always reason and reject an explicit effort override,
        # so leave the request alone and let the API apply its own default.
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
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system or "",
            messages=[{"role": "user", "content": prompt}],
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
                    content = getattr(candidate, "content", None)
                    if not content and isinstance(candidate, dict):
                        content = candidate.get("content")
                    if content is None:
                        continue
                    content_parts = getattr(content, "parts", None)
                    if content_parts is None and isinstance(content, dict):
                        content_parts = content.get("parts")
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
        )
    if provider == "gemini":
        return call_gemini(
            api_key=api_key,
            model=resolved_model,
            system=system,
            user=user,
            temperature=temperature,
            max_output_tokens=output_limit or 8192,
        )
    if provider == "openai":
        return _call_openai(
            api_key=api_key,
            model=resolved_model,
            system=system,
            user=user,
            temperature=temperature,
            max_tokens=output_limit,
        )
    if provider == "openrouter":
        return _call_openrouter(
            api_key=api_key,
            model=resolved_model,
            system=system,
            user=user,
            temperature=temperature,
            max_tokens=output_limit,
        )
    raise LLMError(f"Unknown provider: {provider}")
