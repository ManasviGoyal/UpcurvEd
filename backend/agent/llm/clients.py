# backend/agent/llm/clients.py
from typing import Literal

Provider = Literal["claude", "gemini"]


class LLMError(RuntimeError):
    pass


# ---------- Anthropic (Claude) ----------
def call_claude(
    api_key: str,
    model: str,
    system: str | None,
    user: str,
    max_tokens: int = 2048,
    temperature: float = 0.2,
) -> str:
    """
    Uses Anthropic's official SDK to call the Messages API.
    Returns the concatenated text from response.content blocks.
    """
    try:
        try:
            import anthropic
        except Exception as e:
            raise LLMError(
                "Claude SDK is not installed. Install 'anthropic' to use Claude."
            ) from e

        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system or "",
            messages=[{"role": "user", "content": user}],
        )
        # msg.content is a list of content blocks, e.g. [{"type": "text", "text": "..."}]
        out_parts = []
        for block in msg.content or []:
            if getattr(block, "type", None) == "text":
                out_parts.append(getattr(block, "text", "") or "")
            else:
                # some SDK versions wrap as dicts
                if isinstance(block, dict) and block.get("type") == "text":
                    out_parts.append(block.get("text", "") or "")
        text = "".join(out_parts).strip()
        if not text:
            raise LLMError("Claude returned empty text.")
        return text
    except Exception as e:
        raise LLMError(f"Claude SDK error: {e}") from e


# ---------- Google (Gemini) ----------
def _with_genai_key(api_key: str):
    """
    Configure the google-generativeai SDK with a specific API key.
    Note: genai.configure is global. For simple dev use (single-user),
    this is fine. If you add multi-user concurrency later, consider
    a per-request client (available in newer SDKs) or a key manager.
    """
    try:
        import google.generativeai as genai
    except Exception as e:
        raise LLMError(
            "Gemini SDK is not installed. Install 'google-generativeai' to use Gemini."
        ) from e
    genai.configure(api_key=api_key)


def call_gemini(
    api_key: str,
    model: str,
    system: str | None,
    user: str,
    max_output_tokens: int = 8192,
    temperature: float = 0.2,
) -> str:
    """
    Uses Google's official google-generativeai SDK to call Gemini 1.5.
    We attach system instruction to the GenerativeModel.
    """
    try:
        try:
            import google.generativeai as genai
        except Exception as e:
            raise LLMError(
                "Gemini SDK is not installed. Install 'google-generativeai' to use Gemini."
            ) from e

        if not user or not str(user).strip():
            raise LLMError("Prompt is empty.")

        _with_genai_key(api_key)
        # Use the same style as the user's working snippet.
        # Configure safety settings to be permissive for educational content
        safety_settings = {
            "HARM_CATEGORY_HARASSMENT": "BLOCK_NONE",
            "HARM_CATEGORY_HATE_SPEECH": "BLOCK_NONE",
            "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_NONE",
            "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_NONE",
        }
        gm = genai.GenerativeModel(
            model,
            system_instruction=(system or None),
            generation_config={
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
            },
            safety_settings=safety_settings,
        )
        resp = gm.generate_content(str(user))

        # Preferred accessor (guard against SDK raising when finish_reason!=OK)
        try:
            text = (resp.text or "").strip()  # property may raise
        except Exception:
            text = ""
        if not text:
            # Fallback: manually gather text parts from candidates
            try:
                candidates = getattr(resp, "candidates", []) or []
                parts = []
                for c in candidates:
                    content = getattr(c, "content", None)
                    if not content:
                        content = c.get("content") if isinstance(c, dict) else None
                    if content is None:
                        continue
                    cparts = getattr(content, "parts", None)
                    if cparts is None and isinstance(content, dict):
                        cparts = content.get("parts")
                    for p in cparts or []:
                        # p may be object with .text or dict {text:...}
                        val = getattr(p, "text", None)
                        if val is None and isinstance(p, dict):
                            val = p.get("text")
                        if val:
                            parts.append(str(val))
                text = ("\n".join(parts)).strip()
            except Exception:
                text = ""

        if not text:
            # Provide details about why (e.g., safety finish_reason)
            finish = None
            try:
                if getattr(resp, "candidates", None):
                    finish = getattr(resp.candidates[0], "finish_reason", None)
            except Exception:
                pass
            pf = getattr(resp, "prompt_feedback", None)
            # finish_reason: 1=STOP (normal), 2=SAFETY, 3=RECITATION, 4=OTHER
            error_msg = f"Gemini returned empty text. finish_reason={finish}"
            if finish == 2:
                error_msg = (
                    "Gemini blocked the content due to safety filters. "
                    "Try rephrasing your prompt or use Claude instead."
                )
            elif pf:
                error_msg += f", prompt_feedback={pf}"
            raise LLMError(error_msg)
        return text
    except Exception as e:
        raise LLMError(f"Gemini SDK error: {e}") from e


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
    """
    Dispatch to the chosen provider using sensible defaults.
    Temperature controls randomness: 0.0=deterministic, 1.0=creative.
    Recommended: 0.2 for code, 0.4-0.5 for quizzes, 0.5-0.7 for creative content.
    """
    if provider == "claude":
        model = model or "claude-sonnet-4-6"
        return call_claude(
            api_key=api_key,
            model=model,
            system=system,
            user=user,
            temperature=temperature,
            max_tokens=max_tokens or 2048,
        )
    elif provider == "gemini":
        model = model or "gemini-2.5-pro"
        return call_gemini(
            api_key=api_key,
            model=model,
            system=system,
            user=user,
            temperature=temperature,
            max_output_tokens=max_output_tokens or 8192,
        )
    else:
        raise LLMError(f"Unknown provider: {provider}")
