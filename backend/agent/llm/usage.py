"""Token pricing lookup and deterministic LLM cost estimation for UpcurvEd."""
from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

_PRICING_PATH = Path(__file__).with_name("model_pricing.json")


@lru_cache(maxsize=1)
def load_model_pricing() -> dict[str, Any]:
    try:
        data = json.loads(_PRICING_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _date_value(value: object | None) -> date | None:
    try:
        return date.fromisoformat(str(value or "").strip())
    except Exception:
        return None


def _active_rate(entry: dict[str, Any], *, on_date: date) -> dict[str, Any] | None:
    rates = entry.get("rates")
    if not isinstance(rates, list):
        return None
    eligible: list[tuple[date, dict[str, Any]]] = []
    for raw in rates:
        if not isinstance(raw, dict):
            continue
        start = _date_value(raw.get("effective_from")) or date.min
        end = _date_value(raw.get("effective_through")) or date.max
        if start <= on_date <= end:
            eligible.append((start, raw))
    if not eligible:
        return None
    eligible.sort(key=lambda item: item[0], reverse=True)
    return eligible[0][1]


def _tier_rate(entry: dict[str, Any], *, input_tokens: int) -> dict[str, Any] | None:
    tiers = entry.get("tiers")
    if not isinstance(tiers, list):
        return None
    for raw in tiers:
        if not isinstance(raw, dict):
            continue
        minimum = int(raw.get("min_input_tokens") or 0)
        maximum_raw = raw.get("max_input_tokens")
        maximum = int(maximum_raw) if maximum_raw is not None else None
        if input_tokens < minimum:
            continue
        if maximum is not None and input_tokens > maximum:
            continue
        return raw
    return None


def estimate_call_cost(
    *,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
    cache_write_input_tokens: int = 0,
    on_date: date | None = None,
) -> dict[str, Any]:
    """Estimate one call using repository pricing data.

    Unknown/custom models are deliberately returned as unpriced rather than silently treated as
    free. Rates are standard paid token rates; provider free tiers, credits, negotiated pricing,
    batch/priority modes, cache discounts, and separate tool charges are outside this estimate.
    """
    provider_name = str(provider or "").strip().lower()
    model_name = str(model or "").strip()
    prompt_tokens = max(0, int(input_tokens or 0))
    completion_tokens = max(0, int(output_tokens or 0))
    cached_tokens = min(prompt_tokens, max(0, int(cached_input_tokens or 0)))
    cache_write_tokens = min(
        max(0, prompt_tokens - cached_tokens),
        max(0, int(cache_write_input_tokens or 0)),
    )
    uncached_tokens = max(0, prompt_tokens - cached_tokens - cache_write_tokens)
    key = f"{provider_name}::{model_name}"
    pricing = load_model_pricing()
    models = pricing.get("models") if isinstance(pricing, dict) else None
    entry = models.get(key) if isinstance(models, dict) else None
    if not isinstance(entry, dict):
        return {
            "pricing_known": False,
            "estimated_cost_usd": None,
            "pricing_key": key,
            "input_rate_per_1m": None,
            "output_rate_per_1m": None,
        }

    today = on_date or date.today()
    rate = _tier_rate(entry, input_tokens=prompt_tokens) or _active_rate(entry, on_date=today)
    if not isinstance(rate, dict):
        return {
            "pricing_known": False,
            "estimated_cost_usd": None,
            "pricing_key": key,
            "input_rate_per_1m": None,
            "output_rate_per_1m": None,
        }

    try:
        input_rate = float(rate.get("input"))
        output_rate = float(rate.get("output"))
        cached_input_rate = float(rate.get("cached_input", input_rate))
        cache_write_rate = input_rate * float(entry.get("cache_write_multiplier") or 1.0)
    except Exception:
        return {
            "pricing_known": False,
            "estimated_cost_usd": None,
            "pricing_key": key,
            "input_rate_per_1m": None,
            "output_rate_per_1m": None,
        }

    long_context_applied = False
    long_context = entry.get("long_context")
    if isinstance(long_context, dict):
        threshold = int(long_context.get("threshold_input_tokens") or 0)
        if threshold and prompt_tokens > threshold:
            input_multiplier = float(long_context.get("input_multiplier") or 1.0)
            input_rate *= input_multiplier
            cached_input_rate *= input_multiplier
            cache_write_rate *= input_multiplier
            output_rate *= float(long_context.get("output_multiplier") or 1.0)
            long_context_applied = True

    input_cost = uncached_tokens / 1_000_000 * input_rate
    cached_input_cost = cached_tokens / 1_000_000 * cached_input_rate
    cache_write_cost = cache_write_tokens / 1_000_000 * cache_write_rate
    output_cost = completion_tokens / 1_000_000 * output_rate
    return {
        "pricing_known": True,
        "estimated_cost_usd": round(
            input_cost + cached_input_cost + cache_write_cost + output_cost, 10
        ),
        "pricing_key": key,
        "input_rate_per_1m": input_rate,
        "cached_input_rate_per_1m": cached_input_rate,
        "cache_write_input_rate_per_1m": cache_write_rate,
        "output_rate_per_1m": output_rate,
        "long_context_pricing_applied": long_context_applied,
        "pricing_last_verified": pricing.get("last_verified"),
    }
