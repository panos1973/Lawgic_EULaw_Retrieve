"""One-off: parse the live CDM ontology OWL and rewrite config/cdm_predicates.json.

Per docs/handoff/02_DATA_SOURCES.md, predicate names hand-written from web
search are likely mostly correct but NOT guaranteed. SPARQL fails silently
on misspelled predicates. Run this BEFORE first production SPARQL.

Usage:
    python scripts/parse_cdm_ontology.py

Output: overwrites config/cdm_predicates.json with `_verified: true` and a
`_last_parsed_at` timestamp.

Also cross-check against the eurlex R package's tested query library:
    https://michalovadek.github.io/eurlex/reference/elx_make_query.html
"""

from __future__ import annotations

from pathlib import Path

from python.shared.cdm_ontology import fetch_and_parse_cdm, save_to_config


REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = REPO_ROOT / "config" / "cdm_predicates.json"


def main() -> None:
    print(f"Fetching + parsing CDM ontology...")
    predicates = fetch_and_parse_cdm()
    for group, preds in predicates.items():
        print(f"  {group}: {len(preds)} predicates")
    save_to_config(predicates, OUT_PATH)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
