"""Quality eval harness for Stage 2 metadata extraction.

Per docs/handoff/10_OPEN_QUESTIONS.md #2, Qwen3.6 Plus quality on EU case
law holdings is not in reported benchmarks. Run this on 20 diverse CJEU
judgments and manually review:
    - holding (operative part restated clearly)
    - legal_principle (the rule of law established)
    - case_summary (facts + decision, 3-5 sentences)

Decision rule:
    - Qwen3.6 Plus within ~10-15% semantic fidelity of Gemini -> ship Qwen.
    - Worse -> use Gemini 2.5 Flash interactive for holdings only.

Usage:
    python scripts/eval_extraction.py --docs 20 \\
           --models qwen3.5-flash,qwen3.6-plus,gemini-2.5-flash \\
           --out data/eval_extraction.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", type=int, default=20)
    ap.add_argument("--models", default="qwen3.5-flash,qwen3.6-plus,gemini-2.5-flash")
    ap.add_argument("--out", type=Path,
                    default=Path("data") / "eval_extraction.jsonl")
    args = ap.parse_args()

    print(f"Eval harness - not yet wired. TODO:", file=sys.stderr)
    print(f"  1. Sample {args.docs} CJEU judgments from EULawIngestionStatus", file=sys.stderr)
    print(f"  2. Run each through: {args.models.split(',')}", file=sys.stderr)
    print(f"  3. Persist enriched output per (doc, model) to {args.out}", file=sys.stderr)
    print(f"  4. Print summary: JSON-valid rate, field-completeness, cache-hit rate per model", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
