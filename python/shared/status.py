"""Read/write the EULawIngestionStatus Weaviate collection.

Per docs/handoff/03_SCHEMAS.md section 3, this collection IS the single
source of truth for "what has been ingested". It replaces the shipping
app's on-disk fetch_manifest.json so any machine with cluster creds can
resume from the current state.

Uniqueness key: uuid5(celex + "::" + language). Same CELEX in two
languages = two rows.

Field reference (schema in python/create_eustatus_collection.py):
    celex, language, document_type, cellar_recorded_at, text_hash,
    status, last_updated_at, superseded_by, retry_count, error_message
"""

from __future__ import annotations

import datetime as dt
import os
from typing import Iterable, Literal

import weaviate
from weaviate.classes.query import Filter

from .utils import deterministic_uuid, log


Status = Literal[
    "discovered", "fetched", "enriched", "embedded",
    "failed_fetch", "failed_enrich", "failed_embed", "failed_integrity",
    "superseded", "missing_source",
]

STATUS_COLLECTION = "EULawIngestionStatus"


def _client() -> weaviate.WeaviateClient:
    host = os.environ["WEAVIATE_HOST"]
    api_key = os.environ["WEAVIATE_API_KEY"]
    return weaviate.connect_to_weaviate_cloud(
        cluster_url=host,
        auth_credentials=weaviate.auth.AuthApiKey(api_key),
    )


def _uuid(celex: str, language: str) -> str:
    return deterministic_uuid(celex, language)


def upsert(*, celex: str, language: str, document_type: str,
           status: Status, cellar_recorded_at: dt.datetime | None = None,
           text_hash: str | None = None, superseded_by: str | None = None,
           error_message: str | None = None, retry_count: int | None = None) -> None:
    """Create or update one status row. Safe to call repeatedly — idempotent by uuid."""
    client = _client()
    try:
        coll = client.collections.get(STATUS_COLLECTION)
        props = {
            "celex": celex,
            "language": language,
            "document_type": document_type,
            "status": status,
            "last_updated_at": dt.datetime.now(dt.timezone.utc),
        }
        if cellar_recorded_at is not None:
            props["cellar_recorded_at"] = cellar_recorded_at
        if text_hash is not None:
            props["text_hash"] = text_hash
        if superseded_by is not None:
            props["superseded_by"] = superseded_by
        if error_message is not None:
            props["error_message"] = error_message
        if retry_count is not None:
            props["retry_count"] = retry_count
        coll.data.insert(uuid=_uuid(celex, language), properties=props)
    finally:
        client.close()


def mark(celex: str, language: str, status: Status, **extra) -> None:
    """Shortcut. Caller must know the document_type for first insert; subsequent
    mark() calls treat the row as already existing and patch status only."""
    upsert(celex=celex, language=language, status=status,
           document_type=extra.pop("document_type", "legislation"), **extra)


def list_by_status(status: Status, language: str | None = None) -> list[dict]:
    client = _client()
    try:
        coll = client.collections.get(STATUS_COLLECTION)
        flt = Filter.by_property("status").equal(status)
        if language:
            flt = flt & Filter.by_property("language").equal(language)
        return [o.properties for o in coll.query.fetch_objects(filters=flt, limit=10_000).objects]
    finally:
        client.close()


def list_embedded(language: str) -> list[str]:
    """CELEX list for language where status == 'embedded'. Used by language_adder."""
    rows = list_by_status("embedded", language=language)
    return [r["celex"] for r in rows]


def watermark_min_pending() -> dt.datetime | None:
    """MIN(cellar_recorded_at) for rows NOT yet embedded. Used to derive the
    Atom-feed watermark for incremental updates. See docs/handoff/01_ARCHITECTURE.md."""
    client = _client()
    try:
        coll = client.collections.get(STATUS_COLLECTION)
        flt = Filter.by_property("status").not_equal("embedded")
        objs = coll.query.fetch_objects(
            filters=flt, limit=10_000,
            return_properties=["cellar_recorded_at"],
        ).objects
        dates = [o.properties.get("cellar_recorded_at") for o in objs]
        dates = [d for d in dates if d is not None]
        return min(dates) if dates else None
    finally:
        client.close()


def aggregate_counts() -> dict[str, int]:
    """Per-status counts for the UI status panel."""
    client = _client()
    try:
        coll = client.collections.get(STATUS_COLLECTION)
        result = {}
        for s in ("discovered", "fetched", "enriched", "embedded",
                  "failed_fetch", "failed_enrich", "failed_embed",
                  "failed_integrity", "superseded", "missing_source"):
            flt = Filter.by_property("status").equal(s)
            r = coll.aggregate.over_all(filters=flt, total_count=True)
            result[s] = r.total_count or 0
        return result
    finally:
        client.close()


def should_skip(celex: str, language: str, current_text_hash: str) -> bool:
    """Skip if already embedded AND text hasn't changed. Main idempotency check."""
    client = _client()
    try:
        coll = client.collections.get(STATUS_COLLECTION)
        obj = coll.query.fetch_object_by_id(_uuid(celex, language))
        if obj is None:
            return False
        p = obj.properties
        return p.get("status") == "embedded" and p.get("text_hash") == current_text_hash
    finally:
        client.close()
