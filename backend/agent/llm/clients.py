# backend/agent/llm/clients.py
from __future__ import annotations

import base64
import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from typing import Any, Iterator

from backend.agent.llm.usage import estimate_call_cost

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
class LLMCallRecord:
    """Privacy-safe token/cost record for one attempted model call."""

    provider: str
    model: str
    purpose: str = "generation"
    actual_model: str = ""
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    usage_reported: bool = False
    status: str = "attempted"
    pricing_known: bool = False
    estimated_cost_usd: float | None = None
    input_rate_per_1m: float | None = None
    output_rate_per_1m: float | None = None
    long_context_pricing_applied: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LLMCallCounter:
    """Request-local model call, token, and estimated-cost tracker."""

    count: int = 0
    calls: list[LLMCallRecord] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        input_tokens = sum(max(0, int(call.input_tokens)) for call in self.calls)
        cached_input_tokens = sum(max(0, int(call.cached_input_tokens)) for call in self.calls)
        cache_write_input_tokens = sum(max(0, int(call.cache_write_input_tokens)) for call in self.calls)
        output_tokens = sum(max(0, int(call.output_tokens)) for call in self.calls)
        total_tokens = sum(
            max(0, int(call.total_tokens or (call.input_tokens + call.output_tokens)))
            for call in self.calls
        )
        priced = [call for call in self.calls if call.pricing_known and call.estimated_cost_usd is not None]
        usage_reported_calls = sum(1 for call in self.calls if call.usage_reported)
        unpriced_calls = sum(1 for call in self.calls if call.usage_reported and not call.pricing_known)
        estimated_cost = sum(float(call.estimated_cost_usd or 0.0) for call in priced)
        return {
            "llm_calls": int(self.count),
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_input_tokens,
            "cache_write_input_tokens": cache_write_input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "estimated_cost_usd": round(estimated_cost, 10),
            "pricing_complete": usage_reported_calls == self.count and unpriced_calls == 0,
            "usage_complete": usage_reported_calls == self.count,
            "unpriced_calls": unpriced_calls,
            "usage_missing_calls": max(0, self.count - usage_reported_calls),
            "calls": [call.to_dict() for call in self.calls],
        }


_ACTIVE_LLM_CALL_COUNTER: ContextVar[LLMCallCounter | None] = ContextVar(
    "upcurved_llm_call_counter",
    default=None,
)


@contextmanager
def track_llm_calls() -> Iterator[LLMCallCounter]:
    """Track every ``call_llm`` invocation in the current request context.

    Nested use shares the existing tracker so helper/fallback calls stay in one generation total.
    """
    existing = _ACTIVE_LLM_CALL_COUNTER.get()
    if existing is not None:
        yield existing
        return
    counter = LLMCallCounter()
    token = _ACTIVE_LLM_CALL_COUNTER.set(counter)
    try:
        yield counter
    finally:
        _ACTIVE_LLM_CALL_COUNTER.reset(token)


def current_llm_usage_summary() -> dict[str, Any]:
    counter = _ACTIVE_LLM_CALL_COUNTER.get()
    return counter.summary() if counter is not None else {
        "llm_calls": 0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "cache_write_input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
        "pricing_complete": False,
        "usage_complete": False,
        "unpriced_calls": 0,
        "usage_missing_calls": 0,
        "calls": [],
    }


_ACTIVE_LLM_CALL_RECORD: ContextVar[LLMCallRecord | None] = ContextVar(
    "upcurved_llm_call_record",
    default=None,
)


def _record_llm_call(provider: str, model: str, purpose: str | None) -> LLMCallRecord | None:
    counter = _ACTIVE_LLM_CALL_COUNTER.get()
    if counter is None:
        return None
    counter.count += 1
    record = LLMCallRecord(
        provider=str(provider or ""),
        model=str(model or ""),
        purpose=str(purpose or "generation"),
    )
    counter.calls.append(record)
    return record


def _mark_current_call_success() -> None:
    record = _ACTIVE_LLM_CALL_RECORD.get()
    if record is not None and record.status == "attempted":
        record.status = "ok"


def _capture_current_call_usage(
    *,
    input_tokens: object | None,
    output_tokens: object | None,
    total_tokens: object | None = None,
    cached_input_tokens: object | None = None,
    cache_write_input_tokens: object | None = None,
    actual_model: object | None = None,
) -> None:
    record = _ACTIVE_LLM_CALL_RECORD.get()
    if record is None:
        return
    if input_tokens is None and output_tokens is None and total_tokens is None:
        return
    try:
        prompt_tokens = max(0, int(input_tokens or 0))
    except Exception:
        prompt_tokens = 0
    try:
        completion_tokens = max(0, int(output_tokens or 0))
    except Exception:
        completion_tokens = 0
    try:
        total = max(0, int(total_tokens or 0))
    except Exception:
        total = 0
    if total <= 0:
        total = prompt_tokens + completion_tokens
    try:
        cached_tokens = min(prompt_tokens, max(0, int(cached_input_tokens or 0)))
    except Exception:
        cached_tokens = 0
    try:
        cache_write_tokens = min(
            max(0, prompt_tokens - cached_tokens),
            max(0, int(cache_write_input_tokens or 0)),
        )
    except Exception:
        cache_write_tokens = 0
    record.input_tokens = prompt_tokens
    record.cached_input_tokens = cached_tokens
    record.cache_write_input_tokens = cache_write_tokens
    record.output_tokens = completion_tokens
    record.total_tokens = total
    record.actual_model = str(actual_model or "").strip()
    record.usage_reported = True
    record.status = "ok"
    pricing = estimate_call_cost(
        provider=record.provider,
        model=record.model,
        input_tokens=prompt_tokens,
        output_tokens=completion_tokens,
        cached_input_tokens=cached_tokens,
        cache_write_input_tokens=cache_write_tokens,
    )
    record.pricing_known = bool(pricing.get("pricing_known"))
    cost = pricing.get("estimated_cost_usd")
    record.estimated_cost_usd = float(cost) if cost is not None else None
    input_rate = pricing.get("input_rate_per_1m")
    output_rate = pricing.get("output_rate_per_1m")
    record.input_rate_per_1m = float(input_rate) if input_rate is not None else None
    record.output_rate_per_1m = float(output_rate) if output_rate is not None else None
    record.long_context_pricing_applied = bool(pricing.get("long_context_pricing_applied"))


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

    usage = data.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    _capture_current_call_usage(
        input_tokens=usage.get("prompt_tokens") or usage.get("input_tokens"),
        output_tokens=usage.get("completion_tokens") or usage.get("output_tokens"),
        total_tokens=usage.get("total_tokens"),
        actual_model=data.get("model"),
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

    _mark_current_call_success()
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

    usage = data.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    input_details = usage.get("input_tokens_details")
    input_details = input_details if isinstance(input_details, dict) else {}
    _capture_current_call_usage(
        input_tokens=usage.get("input_tokens") or usage.get("prompt_tokens"),
        output_tokens=usage.get("output_tokens") or usage.get("completion_tokens"),
        total_tokens=usage.get("total_tokens"),
        cached_input_tokens=input_details.get("cached_tokens"),
        cache_write_input_tokens=input_details.get("cache_write_tokens"),
        actual_model=data.get("model"),
    )

    text = _extract_openai_response_text(data)
    if not text:
        status = data.get("status")
        incomplete = data.get("incomplete_details")
        refusal = data.get("refusal")
        detail = refusal or incomplete or status or "No output_text content was returned."
        raise RuntimeError(
            f"OpenAI returned empty content. Model: {model}. Reason: {detail}"
        )
    _mark_current_call_success()
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
        usage = getattr(message, "usage", None)
        input_tokens = getattr(usage, "input_tokens", None) if usage is not None else None
        output_tokens = getattr(usage, "output_tokens", None) if usage is not None else None
        # UpcurvEd does not currently opt into Anthropic prompt caching, so its standard
        # input/output token counts map directly to the maintained standard pricing table.
        _capture_current_call_usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=(int(input_tokens or 0) + int(output_tokens or 0)) if usage is not None else None,
            actual_model=getattr(message, "model", None),
        )
        if not text:
            raise LLMError("Claude returned empty text.")
        _mark_current_call_success()
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

        usage = getattr(response, "usage_metadata", None)
        prompt_tokens = getattr(usage, "prompt_token_count", None) if usage is not None else None
        candidate_tokens = getattr(usage, "candidates_token_count", None) if usage is not None else None
        thought_tokens = getattr(usage, "thoughts_token_count", 0) if usage is not None else 0
        output_tokens = (int(candidate_tokens or 0) + int(thought_tokens or 0)) if usage is not None else None
        total_tokens = getattr(usage, "total_token_count", None) if usage is not None else None
        _capture_current_call_usage(
            input_tokens=prompt_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            actual_model=model,
        )

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
        _mark_current_call_success()
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
    purpose: str | None = None,
) -> str:
    """Dispatch to the selected provider and record request-local usage when available."""
    resolved_model = str(model or get_default_model(provider) or "").strip()
    output_limit = max_tokens or max_output_tokens
    record = _record_llm_call(str(provider), resolved_model, purpose)
    record_token = _ACTIVE_LLM_CALL_RECORD.set(record) if record is not None else None

    try:
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
    except Exception:
        if record is not None:
            record.status = "failed"
        raise
    finally:
        if record_token is not None:
            _ACTIVE_LLM_CALL_RECORD.reset(record_token)
