"""One-off: verify that Alibaba DashScope implicit caching is active.

Per docs/handoff/10_OPEN_QUESTIONS.md #1, caching was SKIPPED during
planning - the sandbox couldn't reach DashScope. This script makes two
identical requests with a >2k-token stable prefix and logs the
cached_tokens count reported in the second response.

Decision rule:
    - 2nd call cache_hit_ratio > 0.6 on the stable-prefix tokens -> works.
    - 2nd call cache_hit_ratio ~ 0             -> caching not active on
      this endpoint. Switch to Beijing base URL in Settings and re-run.

Usage:
    DASHSCOPE_API_KEY=sk-... python scripts/verify_qwen_cache.py
"""

from __future__ import annotations

import os

from python.eu.extractor import call_qwen


STABLE_PREFIX = ("You are a legal-text extraction assistant for EU law. " * 200) + "\n\n"


def main() -> None:
    messages = [
        {"role": "system", "content": STABLE_PREFIX},
        {"role": "user", "content": "Return JSON {\"ok\": true}."},
    ]
    print("Base URL:", os.environ.get("DASHSCOPE_BASE_URL", "<default: Singapore>"))
    print()

    for i in (1, 2):
        resp = call_qwen("qwen3.5-flash", messages, enable_thinking=False)
        usage = resp.get("usage", {})
        cached = usage.get("prompt_tokens_details", {}).get("cached_tokens", 0) or 0
        total = usage.get("prompt_tokens", 0)
        pct = (100 * cached / total) if total else 0
        print(f"Call #{i}: prompt_tokens={total}  cached={cached}  cache_hit={pct:.1f}%")

    print()
    print("If call #2 cache_hit is >60% -> caching works.")
    print("If ~0% -> caching not active on this endpoint. Switch to Beijing URL.")


if __name__ == "__main__":
    main()
