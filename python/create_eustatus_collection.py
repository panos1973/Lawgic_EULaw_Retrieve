"""Create the EULawIngestionStatus Weaviate collection.

Single source of truth for 'what has been ingested' — enables resumability
from any machine. No vectors; metadata-only. Shared BM25 / sharding config
still applies for the rare text searches (e.g. find by error message).

Uniqueness: uuid5(celex + '::' + language + '::' + collection_kind) where
collection_kind ∈ {'law', 'case', 'amendment'}. Same CELEX can have status
rows in multiple collections (e.g. an amending act is both a 'law' and
contributes 'amendment' rows).

Idempotent — no-op if exists.
"""

from __future__ import annotations

import os

import weaviate
from weaviate.classes.config import Configure, DataType, Property, Tokenization

from python.shared.weaviate_config import (
    inverted_index_config,
    replication_config,
    sharding_config,
)


COLLECTION_NAME = "EULawIngestionStatus"


def _keyword(name, *, description=""):
    return Property(name=name, description=description, data_type=DataType.TEXT,
                    tokenization=Tokenization.FIELD,
                    index_searchable=False, index_filterable=True)


def _filterable_text(name, *, description=""):
    return Property(name=name, description=description, data_type=DataType.TEXT,
                    tokenization=Tokenization.WORD,
                    index_searchable=True, index_filterable=True)


def main() -> None:
    client = weaviate.connect_to_weaviate_cloud(
        cluster_url=os.environ["WEAVIATE_HOST"],
        auth_credentials=weaviate.auth.AuthApiKey(os.environ["WEAVIATE_API_KEY"]),
    )
    try:
        if client.collections.exists(COLLECTION_NAME):
            print(f"Collection {COLLECTION_NAME} already exists — no-op.")
            return

        client.collections.create(
            name=COLLECTION_NAME,
            description="Per-document, per-language ingestion state. The watermark "
                        "for incremental updates is derived from cellar_recorded_at.",
            vectorizer_config=Configure.Vectorizer.none(),
            inverted_index_config=inverted_index_config(),
            sharding_config=sharding_config(),
            replication_config=replication_config(),
            properties=[
                _keyword("celex"),
                _filterable_text("language", description="ISO 639-1: en|el|de|fr|it"),
                _filterable_text("collection_kind",
                                 description="law | case | amendment — which content collection this state row tracks"),
                _filterable_text("document_type", description="legislation | case_law"),
                Property(name="cellar_recorded_at", data_type=DataType.DATE,
                         index_filterable=True, index_range_filters=True,
                         description="Monotonic publication timestamp from CELLAR Atom feed"),
                _keyword("text_hash", description="SHA-256 of fetched XHTML for change detection"),
                _filterable_text("status",
                                 description="discovered|fetched|enriched|embedded|failed_fetch|failed_enrich|failed_embed|failed_integrity|superseded|missing_source"),
                Property(name="last_updated_at", data_type=DataType.DATE,
                         index_filterable=True, index_range_filters=True),
                _keyword("superseded_by"),
                Property(name="retry_count", data_type=DataType.INT, index_filterable=True),
                Property(name="error_message", data_type=DataType.TEXT,
                         tokenization=Tokenization.WORD, index_searchable=True),
            ],
        )
        print(f"Created collection {COLLECTION_NAME}.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
