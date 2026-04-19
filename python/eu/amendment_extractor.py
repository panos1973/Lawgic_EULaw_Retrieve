"""Knowledge graph population. Two-pass design per docs/handoff/03_SCHEMAS.md #4.

Pass 1 (fast, high confidence):
    CELLAR SPARQL dump of amendment/repeal/based_on edges. Document level.
    Upserts with confidence=1.0, data_source='cellar_sparql'.

Pass 2 (LLM, medium confidence):
    Runs during Stage 2 metadata extraction. Extracts article-level edges
    from the amending act's text ('Article X is replaced by...') and
    interpretation-strength classification for case-law edges.
    Upserts with confidence=0.85-0.95, data_source='llm_extraction'.

Deduplication: ON CONFLICT DO UPDATE SET confidence = GREATEST(...).
Higher-confidence row wins, both sources keep their own rows' data
provenance via data_source field.
"""

from __future__ import annotations

import datetime as dt
import os
from typing import Iterable

import psycopg

from python.shared.utils import emit, log

from .fetcher import build_amendments_query, run_sparql


def _conn():
    return psycopg.connect(os.environ["DATABASE_URL"])


def upsert_edge(*, source_celex: str, target_celex: str, relation_type: str,
                confidence: float, data_source: str,
                source_article: str | None = None,
                target_article: str | None = None,
                effective_date: dt.date | None = None,
                interpretation_strength: str | None = None,
                source_doc_type: str | None = None) -> None:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO eu_law_edges
                (source_celex, source_article, target_celex, target_article,
                 relation_type, interpretation_strength, effective_date,
                 confidence, data_source, source_doc_type)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_celex, source_article, target_celex, target_article, relation_type)
            DO UPDATE SET
                confidence = GREATEST(EXCLUDED.confidence, eu_law_edges.confidence),
                data_source = CASE
                    WHEN EXCLUDED.confidence > eu_law_edges.confidence
                        THEN EXCLUDED.data_source
                    ELSE eu_law_edges.data_source
                END,
                interpretation_strength = COALESCE(
                    EXCLUDED.interpretation_strength,
                    eu_law_edges.interpretation_strength
                ),
                effective_date = COALESCE(EXCLUDED.effective_date, eu_law_edges.effective_date),
                extracted_at = NOW()
        """, (source_celex, source_article, target_celex, target_article,
              relation_type, interpretation_strength, effective_date,
              confidence, data_source, source_doc_type))


def run_pass1_sparql_edges(limit: int = 2000) -> int:
    """Pass 1 — bulk amendment/repeal/based_on edges from CELLAR SPARQL."""
    emit("pass1_started", limit=limit)
    rows = run_sparql(build_amendments_query(limit=limit))
    emit("pass1_sparql_done", row_count=len(rows))

    count = 0
    for r in rows:
        try:
            src = r["source_celex"]["value"]
            tgt = r["target_celex"]["value"]
            rel = r["relationship"]["value"]
            date_str = r.get("date", {}).get("value")
            eff = dt.date.fromisoformat(date_str[:10]) if date_str else None
            upsert_edge(
                source_celex=src, target_celex=tgt, relation_type=rel,
                confidence=1.0, data_source="cellar_sparql",
                effective_date=eff, source_doc_type="legislation",
            )
            count += 1
        except Exception as e:  # noqa: BLE001
            log("warn", "pass1_edge_failed", error=str(e))
    emit("pass1_completed", edge_count=count)
    return count


def record_llm_edges(*, source_celex: str, source_doc_type: str,
                     cross_references: Iterable[dict]) -> int:
    """Pass 2 — called from Stage 2 extractor for each chunk's cross_references.

    Each ref is expected as:
        {"celex": "32016R0679", "article": "17", "relation": "cites",
         "interpretation_strength": "applies"}  # interpretation fields optional
    """
    count = 0
    for ref in cross_references:
        try:
            upsert_edge(
                source_celex=source_celex,
                source_article=ref.get("source_article"),
                target_celex=ref["celex"],
                target_article=ref.get("article"),
                relation_type=ref.get("relation", "cites"),
                interpretation_strength=ref.get("interpretation_strength"),
                confidence=float(ref.get("confidence", 0.9)),
                data_source="llm_extraction",
                source_doc_type=source_doc_type,
            )
            count += 1
        except Exception as e:  # noqa: BLE001
            log("warn", "pass2_edge_failed", error=str(e),
                source_celex=source_celex, target=ref.get("celex"))
    return count
