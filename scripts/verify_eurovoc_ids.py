"""Verify EuroVoc concept IDs in config/priority_domains.json against the
live thesaurus. Per docs/handoff/10_OPEN_QUESTIONS.md #5, wrong IDs cause
SPARQL queries to return zero results silently.

Usage:
    python scripts/verify_eurovoc_ids.py

Sets `verified: true` on entries that resolve; prints a warning and leaves
`verified: false` on ones that don't.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import requests


CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "priority_domains.json"


def verify(uri: str) -> bool:
    try:
        resp = requests.head(uri, allow_redirects=True, timeout=15,
                             headers={"User-Agent": "Lawgic_EULaw_Retrieve/0.1"})
        return resp.status_code < 400
    except requests.RequestException:
        return False


def main() -> None:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    ok = fail = 0
    for tier in ("tier_1", "tier_2"):
        for entry in cfg[tier]:
            alive = verify(entry["uri"])
            entry["verified"] = alive
            (ok := ok + 1) if alive else (fail := fail + 1)
            status = "OK" if alive else "MISSING"
            print(f"  [{status}] {entry['id']:>5} {entry['label']:30} {entry['uri']}")

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    print(f"\n{ok} verified, {fail} missing.")
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
