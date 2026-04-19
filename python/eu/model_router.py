"""Task -> model mapping. Per docs/handoff/05_MODEL_STACK.md.

Flipping any task to a different model = one line change here. Gemini
is fallback only (invoked from extractor.py on JSON invalid / timeout /
rate-limit / hallucinated CELEX).
"""

from __future__ import annotations

from typing import Any


MODEL_FOR_TASK: dict[str, tuple[str, dict[str, Any]]] = {
    "doc_summary_legislation":       ("qwen3.5-flash",  {"enable_thinking": False}),
    "doc_summary_case_law":          ("qwen3.5-flash",  {"enable_thinking": False}),
    "chunk_summary":                 ("qwen3.5-flash",  {"enable_thinking": False}),
    "metadata_extraction":           ("qwen3.5-flash",  {"enable_thinking": False}),
    "case_law_operational_metadata": ("qwen3.5-flash",  {"enable_thinking": False}),
    "amendment_article_extraction":  ("qwen3.5-flash",  {"enable_thinking": False}),
    "case_law_holdings":             ("qwen3.6-plus",   {}),
    "case_law_legal_principle":     ("qwen3.6-plus",   {}),
    "interpretation_strength":       ("qwen3.6-plus",   {}),
    "complex_reasoning_any":         ("qwen3.6-plus",   {}),
}

FALLBACK: tuple[str, dict[str, Any]] = (
    "gemini-2.5-flash",
    {"batch": True, "use_cache": True},
)


def model_for(task: str) -> tuple[str, dict[str, Any]]:
    if task not in MODEL_FOR_TASK:
        raise KeyError(f"Unknown task: {task!r}. Add it to MODEL_FOR_TASK.")
    return MODEL_FOR_TASK[task]


def fallback() -> tuple[str, dict[str, Any]]:
    return FALLBACK
