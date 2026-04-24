"""Create the EULaws Weaviate collection (regulations, directives, decisions).

Schema per docs/handoff/03_SCHEMAS.md §1, infrastructure per DocumentVault
production setup (HNSW+RQ, BM25 tuned for long legal text, bilingual stopwords,
sharding/replication, per-property tokenization + index flags).

Named vectors per language: vector_en required, vector_el/de/fr/it reserved
for later population via language_adder.

Idempotent: if the collection exists, this script is a NO-OP. To recreate,
delete manually from the Weaviate console first — we never drop production
data from a script.
"""

from __future__ import annotations

import os

import weaviate
from weaviate.classes.config import DataType, Property, Tokenization

from python.shared.weaviate_config import (
    all_named_vectors,
    inverted_index_config,
    replication_config,
    sharding_config,
)


COLLECTION_NAME = "EULaws"


def _text(name: str, *, description: str = "",
          tokenization: Tokenization = Tokenization.WORD,
          searchable: bool = True, filterable: bool = False) -> Property:
    return Property(
        name=name, description=description, data_type=DataType.TEXT,
        tokenization=tokenization,
        index_searchable=searchable, index_filterable=filterable,
    )


def _keyword(name: str, *, description: str = "") -> Property:
    """Exact-match identifier (celex, eli_uri, content_hash, chunk_id)."""
    return Property(
        name=name, description=description, data_type=DataType.TEXT,
        tokenization=Tokenization.FIELD,
        index_searchable=False, index_filterable=True,
    )


def _filterable_text(name: str, *, description: str = "") -> Property:
    """Controlled-vocab text used in WHERE filters (legal_domain, subtype)."""
    return Property(
        name=name, description=description, data_type=DataType.TEXT,
        tokenization=Tokenization.WORD,
        index_searchable=True, index_filterable=True,
    )


def _date(name: str, *, description: str = "", range_filter: bool = True) -> Property:
    return Property(
        name=name, description=description, data_type=DataType.DATE,
        index_filterable=True, index_range_filters=range_filter,
    )


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
            description="EU legislation: regulations, directives, decisions. "
                        "One row per chunk (article-level). Named vectors per language.",
            vectorizer_config=all_named_vectors(),
            inverted_index_config=inverted_index_config(),
            sharding_config=sharding_config(),
            replication_config=replication_config(),
            properties=[
                # Identity
                _keyword("celex", description="Primary EU document identifier"),
                _keyword("eli_uri", description="European Legislation Identifier URI"),
                _keyword("chunk_id", description="art_N, recital_group_N, annex_N"),
                Property(name="chunk_index", data_type=DataType.INT, index_filterable=True),
                _keyword("content_hash", description="SHA-256 of chunk text"),

                # Text per language (embedded via named vector)
                _text("text_en", description="Chunk text — English (primary)",
                      tokenization=Tokenization.WORD, searchable=True),
                _text("text_el", description="Chunk text — Greek",
                      tokenization=Tokenization.WORD, searchable=True),
                _text("text_de", description="Chunk text — German",
                      tokenization=Tokenization.WORD, searchable=True),
                _text("text_fr", description="Chunk text — French",
                      tokenization=Tokenization.WORD, searchable=True),
                _text("text_it", description="Chunk text — Italian",
                      tokenization=Tokenization.WORD, searchable=True),

                # Summaries (English, LLM-generated; attached to every chunk)
                _text("document_summary",
                      description="3-5 sentence summary of the entire act; same across chunks",
                      tokenization=Tokenization.TRIGRAM),
                _text("chunk_summary",
                      description="1-2 sentence summary of this specific chunk",
                      tokenization=Tokenization.TRIGRAM),
                _text("contextual_prefix",
                      description="Anthropic-pattern ~50-token prefix prepended to chunk text at embed time",
                      tokenization=Tokenization.WORD, searchable=False),

                # Document metadata (language-independent)
                _filterable_text("document_subtype",
                                 description="regulation|directive|decision|implementing_regulation|delegated_regulation|consolidated"),
                _date("document_date", description="cdm:work_date_document"),
                _date("date_in_force"),
                Property(name="in_force", data_type=DataType.BOOL, index_filterable=True),
                _keyword("superseded_by", description="CELEX of repealing act, null if still in force"),
                _text("source_citation",
                      description="Official Journal reference",
                      tokenization=Tokenization.WORD),
                Property(name="eurovoc_concepts", data_type=DataType.TEXT_ARRAY,
                         tokenization=Tokenization.WORD,
                         index_searchable=True, index_filterable=True),
                Property(name="eurovoc_ids", data_type=DataType.TEXT_ARRAY,
                         tokenization=Tokenization.FIELD, index_filterable=True),
                _text("title", description="Document title",
                      tokenization=Tokenization.TRIGRAM),

                # LLM-extracted metadata (English, controlled vocab)
                _filterable_text("legal_domain",
                                 description="data_protection|employment|competition|tax|IP|environmental|consumer|company|financial|commercial|criminal|asylum"),
                Property(name="topic_tags", data_type=DataType.TEXT_ARRAY,
                         tokenization=Tokenization.WORD,
                         index_searchable=True, index_filterable=True),
                Property(name="obligations", data_type=DataType.OBJECT_ARRAY,
                         nested_properties=[
                             Property(name="actor", data_type=DataType.TEXT,
                                      tokenization=Tokenization.WORD),
                             Property(name="action", data_type=DataType.TEXT,
                                      tokenization=Tokenization.WORD),
                             Property(name="deadline", data_type=DataType.TEXT,
                                      tokenization=Tokenization.WORD),
                             Property(name="condition", data_type=DataType.TEXT,
                                      tokenization=Tokenization.WORD),
                         ]),
                Property(name="applies_to", data_type=DataType.TEXT_ARRAY,
                         tokenization=Tokenization.WORD,
                         index_searchable=True, index_filterable=True),
                Property(name="definitions", data_type=DataType.OBJECT,
                         nested_properties=[
                             Property(name="term", data_type=DataType.TEXT,
                                      tokenization=Tokenization.WORD),
                             Property(name="definition", data_type=DataType.TEXT,
                                      tokenization=Tokenization.WORD),
                         ]),
                Property(name="cross_references", data_type=DataType.TEXT_ARRAY,
                         tokenization=Tokenization.FIELD, index_filterable=True),
                Property(name="penalty_type", data_type=DataType.TEXT_ARRAY,
                         tokenization=Tokenization.WORD, index_filterable=True),
                Property(name="effective_dates", data_type=DataType.DATE_ARRAY,
                         index_filterable=True, index_range_filters=True),
                Property(name="international_conventions", data_type=DataType.TEXT_ARRAY,
                         tokenization=Tokenization.WORD, index_filterable=True),

                # Ingestion bookkeeping
                Property(name="language_list", data_type=DataType.TEXT_ARRAY,
                         tokenization=Tokenization.WORD, index_filterable=True),
                _date("fetched_at"),
                _date("extracted_at"),
                Property(name="word_count", data_type=DataType.INT,
                         index_filterable=True, index_range_filters=True),
                Property(name="char_count", data_type=DataType.INT),
            ],
        )
        print(f"Created collection {COLLECTION_NAME}.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
