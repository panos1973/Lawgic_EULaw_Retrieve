"""Stage 2: LLM metadata extraction via DashScope + Gemini fallback.

DashScope (Alibaba) OpenAI-compatible endpoint — Singapore default.
Request shape ported verbatim from geneseas_localrules_embed/python/pipeline.py:714-748,
with `enable_thinking` hoisted to a per-call parameter (the shipping app
hardcoded False; we need it togglable for Qwen3.6 Plus tasks).

Cache metrics: every call logs prompt_tokens_details.cached_tokens. Per
docs/handoff/05_MODEL_STACK.md, if cache hit rate is <60% on legislation
extraction, prompt structure is wrong. 0% = caching not active on this
endpoint; flip Base URL to Beijing in Settings.

Prompt structure (stable prefix -> per-doc header -> per-chunk user):
    system: [STABLE_SCHEMA_PROMPT (~2k tokens, IDENTICAL every call)
            + Document: {celex} / {title} (~500 tokens, same per-doc)]
    user:   chunk_text (varies)

Process chunks of the same document SEQUENTIALLY, not parallelized across
docs. Parallelizing across docs defeats the per-doc cache prefix.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import requests

from python.shared.utils import CostLogger, load_config, log

from .model_router import fallback, model_for


# ---- Pricing (docs/handoff/06_COSTS.md). Used for cost_log.jsonl. ---------
PRICING_PER_M = {
    "qwen3.5-flash":   {"in": 0.065, "cached": 0.016, "out": 0.26},
    "qwen3.6-plus":    {"in": 0.325, "cached": 0.081, "out": 1.95},
    "gemini-2.5-flash": {"in": 0.15, "cached": 0.03, "out": 1.25},
}


def dashscope_base_url() -> str:
    """Allow override via env var; default to Singapore (international) endpoint."""
    return os.environ.get(
        "DASHSCOPE_BASE_URL",
        load_config("endpoints")["dashscope_singapore"],
    )


def call_qwen(model: str, messages: list[dict], *,
              enable_thinking: bool = False,
              temperature: float = 0.1,
              max_tokens: int = 4000,
              timeout: int = 120) -> dict[str, Any]:
    """DashScope OpenAI-compat request. PORT FROM geneseas pipeline.py:714-748."""
    api_key = os.environ["DASHSCOPE_API_KEY"]
    base_url = dashscope_base_url()
    resp = requests.post(
        f"{base_url}/chat/completions",
        json={
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "enable_search": False,
            "enable_thinking": enable_thinking,
            "max_tokens": max_tokens,
        },
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"DashScope error {resp.status_code}: {resp.text[:500]}")
    return resp.json()


def _cost_for(model: str, usage: dict) -> tuple[int, int, int, float]:
    in_tok = usage.get("prompt_tokens", 0)
    cached = usage.get("prompt_tokens_details", {}).get("cached_tokens", 0) or 0
    out_tok = usage.get("completion_tokens", 0)
    p = PRICING_PER_M.get(model, {"in": 0, "cached": 0, "out": 0})
    uncached = max(in_tok - cached, 0)
    cost = (
        uncached * p["in"] / 1_000_000 +
        cached * p["cached"] / 1_000_000 +
        out_tok * p["out"] / 1_000_000
    )
    return in_tok, cached, out_tok, cost


def extract_with_retry(*, task: str, messages: list[dict], celex: str,
                       known_celex_set: set[str] | None = None) -> dict:
    """Primary Qwen path with one retry + Gemini fallback on failure."""
    model, opts = model_for(task)
    enable_thinking = opts.get("enable_thinking", False)
    cost_logger = CostLogger()

    last_error: Exception | None = None
    for attempt in (1, 2):
        try:
            resp = call_qwen(model, messages, enable_thinking=enable_thinking)
            content = resp["choices"][0]["message"]["content"]
            parsed = json.loads(content)

            if known_celex_set is not None and not _celex_valid(parsed, known_celex_set):
                raise ValueError("hallucinated CELEX reference")

            in_tok, cached, out_tok, cost = _cost_for(model, resp.get("usage", {}))
            cost_logger.record(
                model=model, celex=celex, task=task,
                input_tokens=in_tok, cached_tokens=cached,
                output_tokens=out_tok, cost_usd=cost,
            )
            log("debug", "qwen_ok", celex=celex, task=task,
                cache_hit_ratio=(cached / in_tok if in_tok else 0))
            return parsed
        except json.JSONDecodeError as e:
            last_error = e
            log("warn", "qwen_json_invalid", celex=celex, task=task, attempt=attempt)
        except requests.HTTPError as e:  # noqa: PERF203
            last_error = e
            if attempt == 1 and hasattr(e, "response") and e.response.status_code == 429:
                time.sleep(2 ** attempt)
                continue
        except Exception as e:  # noqa: BLE001
            last_error = e
            log("warn", "qwen_error", celex=celex, task=task, error=str(e))

    log("warn", "falling_back_to_gemini", celex=celex, task=task,
        error=str(last_error))
    return _gemini_fallback(messages=messages, celex=celex, task=task)


def _celex_valid(parsed: dict, known: set[str]) -> bool:
    """Reject output that cites CELEX numbers not in our known set."""
    refs = parsed.get("cross_references") or []
    if isinstance(refs, list):
        return all((not isinstance(r, str) or r in known) for r in refs)
    return True


def _gemini_fallback(*, messages: list[dict], celex: str, task: str) -> dict:
    """Interactive Gemini call — for fallback volume we skip the 24h batch queue
    and call synchronously. If fallback rate is ever >5% we should switch to
    batch mode (see 05_MODEL_STACK.md)."""
    import google.generativeai as genai  # local import — heavy dep

    genai.configure(api_key=os.environ["GOOGLE_AI_STUDIO_API_KEY"])
    model_name, _opts = fallback()
    model = genai.GenerativeModel(model_name)

    system = "\n".join(m["content"] for m in messages if m["role"] == "system")
    user = "\n".join(m["content"] for m in messages if m["role"] == "user")
    prompt = f"{system}\n\nReturn valid JSON only.\n\n{user}"

    resp = model.generate_content(prompt)
    return json.loads(resp.text)
