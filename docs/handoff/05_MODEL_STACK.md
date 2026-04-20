# Model Stack

## Final locked stack

| Role | Model | Mode | Purpose |
|---|---|---|---|
| Default (bulk) | **Qwen3.5 Flash** | Reasoning OFF | Summaries, metadata extraction, amendment parsing — 95% of token volume |
| Reasoning-required | **Qwen3.6 Plus** | Reasoning always ON | Case law holdings + legal principle + any future reasoning task |
| Fallback | **Gemini 2.5 Flash** | Batch mode + implicit cache | JSON invalid / timeout / rate-limit safety net only |

**No Claude anywhere.** Simpler stack, fewer vendors, one cost optimization strategy.

## Model router (task → model mapping)

File: `python/eu/model_router.py`

```python
MODEL_FOR_TASK = {
    "doc_summary_legislation":       ("qwen3.5-flash",  {"enable_thinking": False}),
    "doc_summary_case_law":          ("qwen3.5-flash",  {"enable_thinking": False}),
    "chunk_summary":                 ("qwen3.5-flash",  {"enable_thinking": False}),
    "metadata_extraction":           ("qwen3.5-flash",  {"enable_thinking": False}),
    "case_law_operational_metadata": ("qwen3.5-flash",  {"enable_thinking": False}),
    "amendment_article_extraction":  ("qwen3.5-flash",  {"enable_thinking": False}),
    "case_law_holdings":             ("qwen3.6-plus",   {}),  # always reasons, no flag needed
    "case_law_legal_principle":      ("qwen3.6-plus",   {}),
    "interpretation_strength":       ("qwen3.6-plus",   {}),
    "complex_reasoning_any":         ("qwen3.6-plus",   {}),  # future use
}

FALLBACK = ("gemini-2.5-flash", {"batch": True, "use_cache": True})
```

Flipping any task to a different model = one line change.

## Alibaba DashScope integration

**Endpoint:** `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` (Singapore, OpenAI-compatible mode — same as shipping app)

**Request pattern** (copy verbatim from `geneseas_localrules_embed/python/pipeline.py:714-748`):
```python
import requests

def call_qwen(model, messages, api_key, enable_thinking=False, base_url=None):
    base_url = base_url or "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    resp = requests.post(
        f"{base_url}/chat/completions",
        json={
            "model": model,
            "messages": messages,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "enable_search": False,
            "enable_thinking": enable_thinking,
            "max_tokens": 4000,
        },
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=120,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"DashScope error {resp.status_code}: {resp.text[:500]}")
    return resp.json()
```

**Key difference from shipping app:** `enable_thinking` is now a parameter passed per call from the model router, NOT hardcoded to `False`. The shipping app hardcodes it; we need it toggleable for Qwen3.6 Plus vs Qwen3.5 Flash tasks (though 3.6 Plus ignores the flag — always reasons regardless).

**Rate limiting:** `LLM_CONCURRENCY` env var, default 3 QPS (safe on free tier). Paid tier raises to 10+ QPS.

**Model names on DashScope:**
- `qwen3.5-flash` — also accepts `qwen3.5-flash-2026-02-23` for pinned version
- `qwen3.6-plus` — released April 2026

## Caching on DashScope

**Status:** implicit caching supported on Qwen models via OpenAI-compat mode. The test was skipped to save time. Caching behavior will be validated on the first real extraction batch via logs.

**Expected behavior:**
- Cached tokens reported in `response.usage.prompt_tokens_details.cached_tokens`.
- No `cache_control` parameter needed — automatic server-side prefix matching.
- Cache discount rate: ~0.25x base input price (inferred; confirm on first batch).
- Requires stable prefix of >1024 tokens to activate reliably.

**How to structure prompts to maximize cache hits:**
```python
messages = [
    {
        "role": "system",
        "content": [
            STABLE_SCHEMA_PROMPT,          # ~2k tokens, IDENTICAL every call
            f"Document: {celex} / {title}",  # ~500 tokens, SAME for all chunks of this doc
        ]
    },
    {
        "role": "user",
        "content": chunk_text              # VARIES per call
    }
]
```

**Critical rule:** process chunks of the same document **sequentially**, not parallelized across docs. Parallelizing across docs defeats the per-document cache prefix. Within a doc, chunks 2-N hit the cache on the stable+header blocks.

**Cache verification in production** — the extractor must log cache metrics on every call:
```python
cached = response["usage"].get("prompt_tokens_details", {}).get("cached_tokens", 0)
total = response["usage"].get("prompt_tokens", 0)
logger.info(f"Cache hit: {cached}/{total} ({100*cached/total if total else 0:.0f}%)")
```

If cache hit rate is <60% on legislation extraction, something is wrong in the prompt structure. If it's 0% consistently, caching isn't active on this endpoint — switch Base URL in Settings to Beijing (`https://dashscope.aliyuncs.com/compatible-mode/v1`) and re-verify.

## Gemini fallback pattern

**Endpoint:** Google AI Studio API  
**Model:** `gemini-2.5-flash`  
**Batch API:** `POST /v1beta/models/gemini-2.5-flash:batchGenerateContent` — 24h SLA, 50% off standard pricing  
**Implicit caching:** automatic, $0.03/M cached-input token (vs $0.15/M uncached) — no code needed

**When to invoke fallback:**
- Qwen returned malformed JSON (validator fails after 1 retry)
- Qwen timed out (>120s)
- Qwen rate-limit hit (HTTP 429) after backoff exhausted
- Qwen returned hallucinated CELEX reference (validator check)

**Recommended flow:**
```python
# Primary: Qwen interactive
try:
    result = call_qwen(model, messages, api_key)
    if not validate_json(result) or has_hallucinated_celex(result, known_celex_set):
        raise ValueError("invalid output")
except (Timeout, RateLimit, ValueError):
    gemini_batch_queue.append((celex, chunk_id, messages))

# At end of batch:
if gemini_batch_queue:
    submit_gemini_batch_job(gemini_batch_queue)
    # wait for completion, merge results back
```

## Why this stack over alternatives

Cost comparison on Tier A MVP (35k legislation docs):

| Model | Total extraction cost | Quality |
|---|---|---|
| Claude Haiku 4.5 | ~$1,500 | High, verified |
| Claude Haiku 4.5 batch + cache | ~$406 | High, verified |
| Gemini 2.5 Flash batch + cache | ~$158 | High, verified |
| **Qwen3.5 Flash + cache** | **~$49** | **Needs eval, probably adequate** |

Qwen is ~3-30x cheaper than alternatives. Quality risk mitigated by:
1. Gemini fallback on JSON failures
2. Qwen3.6 Plus (higher-capacity model) for the 5% highest-stakes tasks (case law holdings)
3. Eval harness validating quality against Gemini baseline before committing to production

## Settings panel UI (in Electron)

Three model preset dropdowns + two API key fields:
```
DashScope API Key:  [_______________________]  (Alibaba - primary)
Google AI Studio:   [_______________________]  (fallback)

Extraction model:   [▾ qwen3.5-flash (default)     ]
Reasoning model:    [▾ qwen3.6-plus (holdings)     ]
Fallback model:     [▾ gemini-2.5-flash (batch)    ]

Base URL (optional): [https://dashscope-intl.aliyuncs.com/compatible-mode/v1]
```

Strip Claude entirely from the UI. Don't even show it as an option to avoid confusion.

## API key sourcing

- **DashScope:** https://modelstudio.console.alibabacloud.com/ → API-Key → Create. International endpoint works with the Singapore base URL above. Free tier sufficient for small runs.
- **Google AI Studio:** https://aistudio.google.com/ → Get API Key. Free tier exists but batch requires paid tier.

## Security

API keys live in the Electron app's settings file (same pattern as shipping app — NOT in the repo, stored in user's OS keychain or local config dir). Never commit keys to git. The shipping app's settings panel already handles this correctly; copy verbatim.

## Rate limit backoff

DashScope returns HTTP 429 on rate limit. Implement exponential backoff: 2s, 4s, 8s, 16s, then route to Gemini fallback. Don't retry past 16s.
