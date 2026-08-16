"""Shared backend provider configuration and resolution helpers.

Keep provider names, environment-key mappings, automatic selection order, and
model defaults here. Artifact modules should import these helpers rather than
maintaining local provider lists.
"""
from __future__ import annotations

import os
from typing import Literal, Mapping, cast


ProviderName = Literal["claude", "gemini", "openai", "openrouter"]

SUPPORTED_PROVIDERS: tuple[ProviderName, ...] = (
    "claude",
    "gemini",
    "openai",
    "openrouter",
)

# Used only when the request does not explicitly select a provider.
PROVIDER_PRIORITY: tuple[ProviderName, ...] = (
    "gemini",
    "claude",
    "openai",
    "openrouter",
)

PROVIDER_ENV_KEYS: dict[ProviderName, str] = {
    "claude": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def _env_value(*names: str) -> str:
    for name in names:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def default_openrouter_model() -> str:
    """Return the configured OpenRouter model with backward-compatible env support."""
    return _env_value("OPENROUTER_MODEL", "OPENROUTER_FREE_MODEL") or (
        "nvidia/nemotron-3-ultra-550b-a55b:free"
    )


def default_openai_model() -> str:
    """Return the configured direct OpenAI model."""
    return _env_value("OPENAI_MODEL") or "gpt-5.6"


def get_default_model(provider: str | None) -> str | None:
    normalized = normalize_provider(provider)
    if normalized == "claude":
        return _env_value("ANTHROPIC_MODEL", "CLAUDE_MODEL") or "claude-haiku-4-5"
    if normalized == "gemini":
        return _env_value("GEMINI_MODEL") or "gemini-3-flash-preview"
    if normalized == "openai":
        return default_openai_model()
    if normalized == "openrouter":
        return default_openrouter_model()
    return None


def normalize_provider(provider: str | None) -> ProviderName | None:
    value = str(provider or "").strip().lower()
    if not value:
        return None
    if value not in SUPPORTED_PROVIDERS:
        supported = ", ".join(SUPPORTED_PROVIDERS)
        raise RuntimeError(f"Unsupported provider '{value}'. Supported providers: {supported}.")
    return cast(ProviderName, value)


def merge_provider_keys(keys: Mapping[str, str] | None) -> dict[str, str]:
    """Merge request keys with environment keys without overwriting explicit values."""
    merged = {
        str(name): str(value or "").strip()
        for name, value in dict(keys or {}).items()
    }
    for provider, env_name in PROVIDER_ENV_KEYS.items():
        if not merged.get(provider):
            env_value = (os.environ.get(env_name) or "").strip()
            if env_value:
                merged[provider] = env_value
    return merged


def infer_provider(
    keys: Mapping[str, str] | None,
    *,
    default_provider: str | None = None,
) -> ProviderName | None:
    merged = merge_provider_keys(keys)
    for candidate in PROVIDER_PRIORITY:
        if merged.get(candidate):
            return candidate
    return normalize_provider(default_provider)


def resolve_provider(
    provider: str | None,
    keys: Mapping[str, str] | None,
    *,
    default_provider: str | None = None,
) -> ProviderName | None:
    return normalize_provider(provider) or infer_provider(
        keys,
        default_provider=default_provider,
    )


def resolve_provider_model(
    keys: Mapping[str, str] | None,
    provider: str | None,
    model: str | None,
    *,
    default_provider: str | None = None,
) -> tuple[ProviderName | None, str | None]:
    resolved_provider = resolve_provider(
        provider,
        keys,
        default_provider=default_provider,
    )
    resolved_model = str(model or "").strip() or get_default_model(resolved_provider)
    return resolved_provider, resolved_model


def resolve_provider_and_key(
    provider: str | None,
    keys: Mapping[str, str] | None,
    *,
    default_provider: str | None = None,
) -> tuple[ProviderName, str]:
    merged = merge_provider_keys(keys)
    resolved_provider = resolve_provider(
        provider,
        merged,
        default_provider=default_provider,
    )
    if not resolved_provider:
        supported = ", ".join(SUPPORTED_PROVIDERS)
        raise RuntimeError(
            f"No provider keys available. Provide a key for one of: {supported}."
        )

    api_key = str(merged.get(resolved_provider) or "").strip()
    if not api_key:
        raise RuntimeError(f"Missing API key for provider '{resolved_provider}'.")
    return resolved_provider, api_key


def get_provider_key(
    provider: str | None,
    keys: Mapping[str, str] | None,
) -> str | None:
    normalized = normalize_provider(provider)
    if not normalized:
        return None
    return merge_provider_keys(keys).get(normalized) or None
