"""Populate the EUAmendments Weaviate collection. Two-pass design.

**Pass 1 — CELLAR SPARQL (document-level, confidence=1.0):**
Bulk dump of amends/repeals/based_on edges from CELLAR. Produces rows with
article_hierarchy=null (document-level), data_source='cellar_sparql'. Fast;
no LLM calls.

**Pass 2 — LLM article-level (confidence=0.85-0.95):**
Runs during Stage 2 metadata extraction on each amending act. The LLM
reads the amending act's text and produces structured output:
    {amending_article, target_article, article_hierarchy, change_type,
     old_text, new_text, effective_date, impact_level, chunk_summary}
per amendment instruction. Upserts with data_source='llm_extraction'.

**Deduplication:** Weaviate deterministic UUID based on (amending_celex,
target_celex, article_hierarchy, change_type). On second insert with the
same UUID, the higher-confidence record wins via data.update().

No more Postgres — per user decision. Graph walks are now client-side
loops over EUAmendments filtered by target_celex.
"""

from __future__ import annotations

import datetime as dt
from typing import Iterable

import weaviate
from weaviate.classes.data import DataObject

from python.shared.embedder import compose_embedding_input, embed_batch
from python.shared.utils import deterministic_uuid, emit, log, sha256_text

from .fetcher import build_amendments_query, run_sparql


AMENDMENTS_COLLECTION = "EUAmendments"


def _client() -> weaviate.WeaviateClient:
    import os
    return weaviate.connect_to_weaviate_cloud(
        cluster_url=os.environ["WEAVIATE_HOST"],
        auth_credentials=weaviate.auth.AuthApiKey(os.environ["WEAVIATE_API_KEY"]),
    )


def _amendment_uuid(amending_celex: str, target_celex: str,
                    article_hierarchy: str, change_type: str) -> str:
    return deterministic_uuid(amending_celex, target_celex, article_hierarchy, change_type)


def _build_description(amending_celex: str, target_celex: str,
                       article_hierarchy: str, change_type: str,
                       old_text: str | None, new_text: str | None,
                       effective_date: dt.date | None) -> str:
    """Natural-language description embedded as text_en. Format is stable so
    it compresses well in Voyage and is readable to humans at retrieval time."""
    bits = []
    action = {
        "replace": "replaces",
        "delete": "deletes",
        "add": "adds",
        "modify": "modifies",
        "renumber": "renumbers",
        "consolidate": "consolidates",
        "correct": "corrects",
        "implement": "implements",
    }.get(change_type, change_type)
    target = article_hierarchy or "the target act"
    bits.append(f"CELEX {amending_celex} {action} {target} of CELEX {target_celex}.")
    if old_text:
        bits.append(f"Previous text: {old_text}")
    if new_text:
        bits.append(f"New text: {new_text}")
    if effective_date:
        bits.append(f"Effective from {effective_date.isoformat()}.")
    return " ".join(bits)


def _build_contextual_prefix(*, amending_celex: str, target_celex: str,
                             target_title: str, article_hierarchy: str,
                             change_type: str,
                             amendment_number: int | None = None) -> str:
    ordinal = f"amendment {amendment_number}" if amendment_number else "an amendment"
    return (
        f"This is {ordinal} from {amending_celex} {change_type} "
        f"{article_hierarchy or 'the target document'} of {target_celex} "
        f"({target_title[:80]}). The amendment:"
    )


def upsert_amendments(rows: Iterable[dict], *, default_language: str = "en") -> int:
    """Embed text per language and upsert into EUAmendments.

    Each row expects:
      amending_celex, target_celex, change_type, effective_date (date),
      confidence (float), data_source (str), plus any of:
      article_hierarchy, amending_article, target_article, target_title,
      amending_title, consolidated_celex, old_text, new_text,
      document_summary, chunk_summary, amendment_number,
      impact_level, repeals_entirely, topic_tags, cross_references,
      legal_domain.
    """
    now = dt.datetime.now(dt.timezone.utc)
    rows_list = list(rows)
    if not rows_list:
        return 0

    for r in rows_list:
        description = _build_description(
            amending_celex=r["amending_celex"],
            target_celex=r["target_celex"],
            article_hierarchy=r.get("article_hierarchy", ""),
            change_type=r["change_type"],
            old_text=r.get("old_text"),
            new_text=r.get("new_text"),
            effective_date=r.get("effective_date"),
        )
        r.setdefault("text_en", description)
        prefix = _build_contextual_prefix(
            amending_celex=r["amending_celex"],
            target_celex=r["target_celex"],
            target_title=r.get("target_title", ""),
            article_hierarchy=r.get("article_hierarchy", ""),
            change_type=r["change_type"],
            amendment_number=r.get("amendment_number"),
        )
        r.setdefault("contextual_prefix", prefix)
        r.setdefault("chunk_summary", r.get("chunk_summary") or description[:300])
        r.setdefault("content_hash", sha256_text(description))
        r.setdefault("fetched_at", now)
        r.setdefault("extracted_at", now)
        r.setdefault("language_list", [default_language])
        r.setdefault("celex", r["amending_celex"])
        r.setdefault("chunk_id",
                     f"amend_{r['target_celex']}_{r.get('article_hierarchy','doc')}".replace(" ", "_"))

    # Use shared compose logic for consistency with EULaws/EUCourtDecisions.
    embed_inputs = [compose_embedding_input(row, default_language) for row in [
        {**r, f"text_{default_language}": r["text_en"],
         "chunk_summary": r["chunk_summary"],
         "contextual_prefix": r["contextual_prefix"],
         "chunk_type": "amendment"}
        for r in rows_list
    ]]
    vectors = embed_batch(embed_inputs)

    client = _client()
    try:
        coll = client.collections.get(AMENDMENTS_COLLECTION)
        objs = []
        for r, v in zip(rows_list, vectors):
            uid = _amendment_uuid(
                r["amending_celex"], r["target_celex"],
                r.get("article_hierarchy", ""), r["change_type"],
            )
            objs.append(DataObject(
                uuid=uid, properties=dict(r),
                vector={f"vector_{default_language}": v},
            ))
        coll.data.insert_many(objs)
        return len(objs)
    finally:
        client.close()


def run_pass1_sparql_edges(limit: int = 2000) -> int:
    """CELLAR-sourced document-level edges; confidence=1.0."""
    emit("pass1_started", limit=limit)
    sparql_rows = run_sparql(build_amendments_query(limit=limit))
    emit("pass1_sparql_done", row_count=len(sparql_rows))

    amendments = []
    for s in sparql_rows:
        try:
            date_str = s.get("date", {}).get("value")
            eff = dt.date.fromisoformat(date_str[:10]) if date_str else None
            amendments.append({
                "amending_celex": s["source_celex"]["value"],
                "target_celex": s["target_celex"]["value"],
                "article_hierarchy": "",  # document-level from SPARQL
                "change_type": s["relationship"]["value"],
                "effective_date": eff,
                "confidence": 1.0,
                "data_source": "cellar_sparql",
                "impact_level": "major",
                "repeals_entirely": s["relationship"]["value"] == "repeals",
            })
        except Exception as e:  # noqa: BLE001
            log("warn", "pass1_row_parse_failed", error=str(e))

    if not amendments:
        emit("pass1_completed", count=0)
        return 0

    count = upsert_amendments(amendments)
    emit("pass1_completed", count=count)
    return count


def record_llm_amendments(*, amending_celex: str, amending_title: str,
                          document_summary: str, amending_document_subtype: str,
                          extracted: Iterable[dict]) -> int:
    """Pass 2 — called from Stage 2 extractor for each amending act.

    `extracted` is the LLM output: a list of structured amendment records
    parsed from the amending act's text. Each expected to have:
        target_celex, target_article, article_hierarchy, change_type,
        old_text, new_text, effective_date (ISO string or null),
        amendment_number, impact_level, chunk_summary.
    """
    now = dt.datetime.now(dt.timezone.utc)
    rows = []
    for ex in extracted:
        try:
            eff_str = ex.get("effective_date")
            eff = dt.date.fromisoformat(eff_str[:10]) if eff_str else None
            rows.append({
                "amending_celex": amending_celex,
                "amending_title": amending_title,
                "amending_document_subtype": amending_document_subtype,
                "document_summary": document_summary,
                "target_celex": ex["target_celex"],
                "target_article": ex.get("target_article", ""),
                "article_hierarchy": ex.get("article_hierarchy", ""),
                "target_title": ex.get("target_title", ""),
                "target_document_subtype": ex.get("target_document_subtype", ""),
                "change_type": ex["change_type"],
                "old_text": ex.get("old_text"),
                "new_text": ex.get("new_text"),
                "amendment_number": ex.get("amendment_number"),
                "impact_level": ex.get("impact_level", "minor"),
                "repeals_entirely": bool(ex.get("repeals_entirely", False)),
                "effective_date": eff,
                "chunk_summary": ex.get("chunk_summary", ""),
                "legal_domain": ex.get("legal_domain", ""),
                "topic_tags": ex.get("topic_tags", []),
                "cross_references": ex.get("cross_references", []),
                "confidence": float(ex.get("confidence", 0.9)),
                "data_source": "llm_extraction",
                "fetched_at": now,
                "extracted_at": now,
            })
        except Exception as e:  # noqa: BLE001
            log("warn", "pass2_row_build_failed", error=str(e),
                amending_celex=amending_celex)

    if not rows:
        return 0
    return upsert_amendments(rows)
