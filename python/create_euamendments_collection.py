"""Create the EUAmendments Weaviate collection.

One row per atomic amendment: 'Article X of CELEX A is replaced/deleted/
modified/renumbered by the text in CELEX B at its Article Y'. Each row
holds the actual TEXT of the change (old and new), semantic vectors per
language, and enough structured metadata to answer 'what changed, when,
in which target article'.

Replaces the Postgres eu_law_edges table that was in the original plan —
per user decision to keep everything in Weaviate.

Retrieval patterns this collection supports:
  - Semantic: 'find amendments that change how consent is defined'
  - Structured: 'all amendments to CELEX 32016R0679 Article 17 since 2022'
  - Graph-ish: 'chain of amendments for CELEX 32016R0679' → filter + sort
      by effective_date (up to depth 1 trivially; deeper chains are
      multi-query at retrieval time, ~app-level loop)

Uniqueness: uuid5(amending_celex + '::' + target_celex + '::' +
article_hierarchy + '::' + change_type). Re-runs overwrite the same
amendment instruction.

Schema per docs/handoff/03_SCHEMAS.md §4 (new, replaces Postgres §4).
Vault-grade infrastructure. Idempotent — no-op if exists.
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


COLLECTION_NAME = "EUAmendments"


def _text(name, *, description="", tokenization=Tokenization.WORD,
          searchable=True, filterable=False):
    return Property(name=name, description=description, data_type=DataType.TEXT,
                    tokenization=tokenization,
                    index_searchable=searchable, index_filterable=filterable)


def _keyword(name, *, description=""):
    return Property(name=name, description=description, data_type=DataType.TEXT,
                    tokenization=Tokenization.FIELD,
                    index_searchable=False, index_filterable=True)


def _filterable_text(name, *, description=""):
    return Property(name=name, description=description, data_type=DataType.TEXT,
                    tokenization=Tokenization.WORD,
                    index_searchable=True, index_filterable=True)


def _date(name, *, description="", range_filter=True):
    return Property(name=name, description=description, data_type=DataType.DATE,
                    index_filterable=True, index_range_filters=range_filter)


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
            description="Atomic amendments: each row is one 'replace/delete/add/modify/"
                        "renumber' instruction from an amending act against a target act. "
                        "Text per language, structured metadata, semantic vectors.",
            vectorizer_config=all_named_vectors(),
            inverted_index_config=inverted_index_config(),
            sharding_config=sharding_config(),
            replication_config=replication_config(),
            properties=[
                # Identity
                _keyword("chunk_id",
                         description="Deterministic: amend_{target_celex}_{article_hierarchy}"),
                Property(name="chunk_index", data_type=DataType.INT, index_filterable=True,
                         description="Position within the amending act (1 of 12, 2 of 12, ...)"),
                _keyword("content_hash"),
                _keyword("celex",
                         description="Mirror of amending_celex — present so EULaws-shaped retrievers work unchanged"),

                # Source (the amending act)
                _keyword("amending_celex",
                         description="CELEX of the amending act (e.g. 32024R1157)"),
                _filterable_text("amending_article",
                                 description="Which article of the amending act carries this change (e.g. 'Art 1(3)')"),
                _text("amending_title",
                      description="Title of the amending act; denormalized for easy display",
                      tokenization=Tokenization.TRIGRAM),
                _filterable_text("amending_document_subtype",
                                 description="regulation|directive|decision|implementing_regulation|delegated_regulation|corrigendum"),

                # Target (the act being changed)
                _keyword("target_celex", description="CELEX of the act being changed"),
                _filterable_text("target_article",
                                 description="Top-level article number, e.g. '17'"),
                _filterable_text("article_hierarchy",
                                 description="Precise target inside the article, e.g. 'Article 17(3)(c)'"),
                _text("target_title",
                      description="Title of the target act; denormalized",
                      tokenization=Tokenization.TRIGRAM),
                _filterable_text("target_document_subtype",
                                 description="Subtype of the target act"),
                _keyword("consolidated_celex",
                         description="Nullable; CELEX of consolidated version incorporating this amendment, if published"),

                # Change semantics
                _filterable_text("change_type",
                                 description="replace|delete|add|modify|renumber|consolidate|correct|implement"),
                _filterable_text("impact_level",
                                 description="major|minor|clarification|renumber — LLM-classified by legal consequence"),
                Property(name="repeals_entirely", data_type=DataType.BOOL, index_filterable=True,
                         description="True when the amendment deletes the target article entirely"),
                _date("effective_date",
                      description="When the amendment takes effect (not just publication)"),
                Property(name="amendment_number", data_type=DataType.INT,
                         index_filterable=True, index_range_filters=True,
                         description="Nth amendment in the amending act (1-based)"),

                # Text per language (embedded)
                _text("text_en", description="Full amendment description — English",
                      tokenization=Tokenization.WORD),
                _text("text_el", description="Full amendment description — Greek",
                      tokenization=Tokenization.WORD),
                _text("text_de", tokenization=Tokenization.WORD),
                _text("text_fr", tokenization=Tokenization.WORD),
                _text("text_it", tokenization=Tokenization.WORD),

                # Raw before/after (English-only, precision access)
                _text("old_text",
                      description="Text that was there before the amendment (null for ADD)",
                      tokenization=Tokenization.WORD),
                _text("new_text",
                      description="Text after the amendment (null for DELETE)",
                      tokenization=Tokenization.WORD),

                # Summaries
                _text("document_summary",
                      description="Summary of the whole AMENDING ACT (same across all its amendments)",
                      tokenization=Tokenization.TRIGRAM),
                _text("chunk_summary",
                      description="1-2 sentence summary of THIS specific amendment",
                      tokenization=Tokenization.TRIGRAM),
                _text("contextual_prefix",
                      description="~50-token prefix prepended at embed time",
                      tokenization=Tokenization.WORD, searchable=False),

                # Inherited / denormalized LLM metadata
                _filterable_text("legal_domain",
                                 description="Inherited from target act (GDPR → data_protection)"),
                Property(name="topic_tags", data_type=DataType.TEXT_ARRAY,
                         tokenization=Tokenization.WORD,
                         index_searchable=True, index_filterable=True),
                Property(name="cross_references", data_type=DataType.TEXT_ARRAY,
                         tokenization=Tokenization.FIELD, index_filterable=True,
                         description="Other CELEX numbers cited inside the amendment body"),

                # Provenance
                _filterable_text("data_source",
                                 description="cellar_sparql | llm_extraction | manual"),
                Property(name="confidence", data_type=DataType.NUMBER,
                         index_filterable=True, index_range_filters=True,
                         description="1.0 from SPARQL document-level, 0.85-0.95 from LLM article-level"),

                # Bookkeeping
                Property(name="language_list", data_type=DataType.TEXT_ARRAY,
                         tokenization=Tokenization.WORD, index_filterable=True),
                _date("fetched_at"),
                _date("extracted_at"),
                Property(name="word_count", data_type=DataType.INT),
                Property(name="char_count", data_type=DataType.INT),
            ],
        )
        print(f"Created collection {COLLECTION_NAME}.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
