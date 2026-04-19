"""Estimate ingestion cost for a scope + language combination.

Reads token-volume assumptions from docs/handoff/06_COSTS.md:
    Tier A MVP:    ~10k legislation + ~25k case law, priority domains
    Per language:  ~$97 embeddings + $0 LLM (metadata stays English)

Usage:
    python scripts/estimate_cost.py --scope tier_a --language en
    python scripts/estimate_cost.py --scope tier_a --language el

Outputs a JSON breakdown suitable for the Electron confirmation dialog.
"""

from __future__ import annotations

import argparse
import json


PRICING = {
    "voyage_in":           0.18 / 1_000_000,
    "qwen35_in":           0.065 / 1_000_000,
    "qwen35_cached":       0.016 / 1_000_000,
    "qwen35_out":          0.26 / 1_000_000,
    "qwen36_in":           0.325 / 1_000_000,
    "qwen36_cached":       0.081 / 1_000_000,
    "qwen36_out":          1.95 / 1_000_000,
    "gemini_batch_in":     0.15 / 1_000_000,
    "gemini_batch_cached": 0.03 / 1_000_000,
    "gemini_batch_out":    1.25 / 1_000_000,
}

SCOPES = {
    "tier_a": {
        "legislation_docs": 10_000,
        "case_law_docs":    25_000,
        "legislation_chunks_per_doc": 15,
        "case_law_chunks_per_doc":    8,
        "avg_chunk_tokens": 730,
        "per_doc_legislation_in":  15_000,
        "per_doc_legislation_out": 2_000,
        "per_doc_case_law_holding_in":   20_000,
        "per_doc_case_law_holding_out":  1_500,
        "cache_rate_legislation": 0.50,
        "cache_rate_case_law_holding": 0.10,
        "gemini_fallback_rate": 0.03,
    },
    "tier_b": {
        "legislation_docs": 20_000,
        "case_law_docs":    150_000,
        "legislation_chunks_per_doc": 15,
        "case_law_chunks_per_doc":    8,
        "avg_chunk_tokens": 730,
        "per_doc_legislation_in":  15_000,
        "per_doc_legislation_out": 2_000,
        "per_doc_case_law_holding_in":   20_000,
        "per_doc_case_law_holding_out":  1_500,
        "cache_rate_legislation": 0.50,
        "cache_rate_case_law_holding": 0.10,
        "gemini_fallback_rate": 0.03,
    },
}


def estimate_language(scope: dict, is_first_language: bool) -> dict:
    total_chunks = (
        scope["legislation_docs"] * scope["legislation_chunks_per_doc"] +
        scope["case_law_docs"] * scope["case_law_chunks_per_doc"]
    )
    voyage_tokens = total_chunks * scope["avg_chunk_tokens"]
    voyage_cost = voyage_tokens * PRICING["voyage_in"]

    result = {
        "total_chunks": total_chunks,
        "voyage_embedding_tokens": voyage_tokens,
        "voyage_embedding_usd": round(voyage_cost, 2),
        "llm_metadata_usd": 0.0,
        "gemini_fallback_usd": 0.0,
        "total_usd": round(voyage_cost, 2),
    }

    if is_first_language:
        leg_docs = scope["legislation_docs"]
        cached_rate = scope["cache_rate_legislation"]
        leg_in = leg_docs * scope["per_doc_legislation_in"]
        leg_out = leg_docs * scope["per_doc_legislation_out"]
        leg_cost = (
            leg_in * (1 - cached_rate) * PRICING["qwen35_in"] +
            leg_in * cached_rate        * PRICING["qwen35_cached"] +
            leg_out                     * PRICING["qwen35_out"]
        )

        case_docs = scope["case_law_docs"]
        cl_cached_rate = scope["cache_rate_case_law_holding"]
        cl_in = case_docs * scope["per_doc_case_law_holding_in"]
        cl_out = case_docs * scope["per_doc_case_law_holding_out"]
        cl_cost = (
            cl_in * (1 - cl_cached_rate) * PRICING["qwen36_in"] +
            cl_in * cl_cached_rate        * PRICING["qwen36_cached"] +
            cl_out                        * PRICING["qwen36_out"]
        )

        gemini_in = (leg_in + cl_in) * scope["gemini_fallback_rate"]
        gemini_out = (leg_out + cl_out) * scope["gemini_fallback_rate"]
        gemini_cost = (
            gemini_in * PRICING["gemini_batch_cached"] +
            gemini_out * PRICING["gemini_batch_out"]
        )

        result["llm_metadata_usd"] = round(leg_cost + cl_cost, 2)
        result["gemini_fallback_usd"] = round(gemini_cost, 2)
        result["total_usd"] = round(
            voyage_cost + leg_cost + cl_cost + gemini_cost, 2
        )
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", choices=list(SCOPES.keys()), default="tier_a")
    ap.add_argument("--language", default="en")
    ap.add_argument("--first-language", action="store_true",
                    help="Include one-time LLM metadata cost.")
    args = ap.parse_args()

    scope_def = SCOPES[args.scope]
    estimate = estimate_language(scope_def, is_first_language=args.first_language)
    estimate["scope"] = args.scope
    estimate["language"] = args.language
    estimate["first_language"] = args.first_language
    print(json.dumps(estimate, indent=2))


if __name__ == "__main__":
    main()
