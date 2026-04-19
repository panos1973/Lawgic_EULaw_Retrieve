"""Thin dispatcher. Subcommands are called from electron/main.js via Python subprocess.

Verbs (mapped one-to-one with IPC in electron/main.js):
    status         — emit status_aggregate event with EULawIngestionStatus counts
    incremental    — Atom-feed-based incremental update across languages
    add-language   — layer a new language's vectors onto embedded docs
    fetch          — Stage 1 only (for Phase 2 dev)
    extract        — Stage 2 only (for Phase 2 dev)
    embed          — Stage 3 only (for Phase 2 dev)
    pass1-edges    — populate eu_law_edges from CELLAR SPARQL

All verbs emit single-line JSON events to stdout via python.shared.utils.emit().
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


def cmd_incremental(args) -> int:
    """Weekly/on-demand update. See docs/handoff/08_ELECTRON_APP.md "Incremental update flow".

    1. Pre-flight: derive watermark = MIN(cellar_recorded_at) WHERE status != 'embedded'.
    2. Poll CELLAR Atom feed for entries newer than watermark.
    3. For each new CELEX: fetch, extract (English only, once), embed per language.
    4. Refresh amendment graph for the incremental set.
    5. Repeal detection: mark superseded CELEX.
    """
    emit("log", level="info", message=f"Incremental update; languages={args.languages} scope={args.scope}")
    log("warn", "incremental flow not yet wired. See docs/handoff/09_IMPLEMENTATION_PLAN.md Phase 2-3.")
    return 1


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


def cmd_extract(args) -> int:
    emit("log", level="warn",
         message="extract stage CLI entry not yet wired; call from pipeline.py cmd_incremental or Phase 2 dev scripts.")
    return 1


def cmd_embed(args) -> int:
    emit("log", level="warn",
         message="embed stage CLI entry not yet wired; Stage 3 runs inline after Stage 2 during normal pipeline.")
    return 1


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

    sp = sub.add_parser("incremental")
    sp.add_argument("--languages", default="en")
    sp.add_argument("--scope", default="priority")
    sp.set_defaults(func=cmd_incremental)

    sp = sub.add_parser("add-language")
    sp.add_argument("--language", required=True)
    sp.set_defaults(func=cmd_add_language)

    sp = sub.add_parser("fetch")
    sp.add_argument("--language", default="en")
    sp.add_argument("--limit", type=int, default=500)
    sp.set_defaults(func=cmd_fetch)

    sp = sub.add_parser("extract")
    sp.set_defaults(func=cmd_extract)

    sp = sub.add_parser("embed")
    sp.set_defaults(func=cmd_embed)

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
