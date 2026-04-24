"""Thin dispatcher. Three parallel ingestion verbs — one per content type.

Verbs wired from electron/main.js:
    status                   — emit counts from EULawIngestionStatus
    incremental-laws         — new legislation (EULaws)
    incremental-cases        — new court decisions (EUCourtDecisions)
    incremental-amendments   — new amendment rows (EUAmendments) for already-
                               embedded target CELEX.
    add-language             — layer a new language's vectors onto embedded docs
    fetch                    — Stage 1 only (dev)
    pass1-edges              — bulk SPARQL amendment seed (EUAmendments only)

All verbs emit single-line JSON events to stdout for Electron to parse.
"""

from __future__ import annotations

import argparse
import sys

from python.shared.utils import emit, log


def cmd_status(args) -> int:
    from python.shared.status import aggregate_counts
    counts = aggregate_counts()
    emit("status_aggregate", counts=counts)
    return 0


def cmd_incremental_laws(args) -> int:
    """Weekly/on-demand ingestion for legislation.

    1. Watermark from EULawIngestionStatus (kind='law').
    2. Atom feed -> new legislation CELEX list.
    3. For each: fetch, parse, Stage 2 LLM (English metadata), Stage 3 embed, mark.
    """
    emit("log", level="info",
         message=f"incremental-laws; languages={args.languages} scope={args.scope}")
    log("warn", "incremental-laws flow not yet wired. See docs/handoff/09_IMPLEMENTATION_PLAN.md Phase 2.")
    return 1


def cmd_incremental_cases(args) -> int:
    """Weekly/on-demand ingestion for court decisions.

    Two-level chunking: holding chunks use Qwen3.6 Plus (reasoning on).
    """
    emit("log", level="info",
         message=f"incremental-cases; languages={args.languages} scope={args.scope}")
    log("warn", "incremental-cases flow not yet wired. See docs/handoff/09_IMPLEMENTATION_PLAN.md Phase 4.")
    return 1


def cmd_incremental_amendments(args) -> int:
    """Run amendment extraction for already-embedded target CELEX.

    Needs EULaws to be populated first (otherwise target CELEX are unknown).
    """
    from python.eu.amendment_extractor import run_pass1_sparql_edges
    emit("log", level="info", message=f"incremental-amendments (Pass 1 SPARQL)")
    count = run_pass1_sparql_edges(limit=args.limit)
    emit("incremental_amendments_summary", pass1_count=count)
    # Pass 2 (article-level LLM) fires during incremental-laws Stage 2;
    # no separate command needed.
    return 0


def cmd_add_language(args) -> int:
    from python.eu.language_adder import add_language
    summary = add_language(args.language)
    emit("add_language_summary", **summary)
    return 0 if summary["failed"] == 0 else 2


def cmd_fetch(args) -> int:
    from python.eu.fetcher import run_legislation_fetch
    count = 0
    for _ in run_legislation_fetch(language=args.language, limit=args.limit):
        count += 1
    emit("fetch_completed", count=count)
    return 0


def cmd_pass1_edges(args) -> int:
    from python.eu.amendment_extractor import run_pass1_sparql_edges
    n = run_pass1_sparql_edges(limit=args.limit)
    emit("pass1_summary", edge_count=n)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pipeline")
    sub = p.add_subparsers(dest="verb", required=True)

    sp = sub.add_parser("status")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("incremental-laws")
    sp.add_argument("--languages", default="en")
    sp.add_argument("--scope", default="priority")
    sp.set_defaults(func=cmd_incremental_laws)

    sp = sub.add_parser("incremental-cases")
    sp.add_argument("--languages", default="en")
    sp.add_argument("--scope", default="priority")
    sp.set_defaults(func=cmd_incremental_cases)

    sp = sub.add_parser("incremental-amendments")
    sp.add_argument("--limit", type=int, default=2000)
    sp.set_defaults(func=cmd_incremental_amendments)

    sp = sub.add_parser("add-language")
    sp.add_argument("--language", required=True)
    sp.set_defaults(func=cmd_add_language)

    sp = sub.add_parser("fetch")
    sp.add_argument("--language", default="en")
    sp.add_argument("--limit", type=int, default=500)
    sp.set_defaults(func=cmd_fetch)

    sp = sub.add_parser("pass1-edges")
    sp.add_argument("--limit", type=int, default=2000)
    sp.set_defaults(func=cmd_pass1_edges)

    return p


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except KeyboardInterrupt:
        emit("log", level="warn", message="interrupted by user")
        return 130
    except Exception as e:  # noqa: BLE001
        emit("log", level="error", message=f"pipeline failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
