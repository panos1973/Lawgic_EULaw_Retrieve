"""Create the EUCourtDecisions Weaviate collection (CJ + GC judgments, orders, AG opinions).

Schema per docs/handoff/03_SCHEMAS.md §2. Two-level chunking: one holding
chunk per decision (embedded with case_summary + legal_principle + holding),
N reasoning chunks grouped as 3-5 paragraphs each.

Same infrastructure as EULaws (Vault-grade HNSW+RQ, tuned BM25, multilingual
stopwords, sharding, replication) with case-law-specific fields replacing
in_force/superseded_by with is_overturned/overturned_by.

Idempotent — no-op if the collection exists.
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


COLLECTION_NAME = "EUCourtDecisions"


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
            description="EU court decisions: Court of Justice (CJ) + General Court (GC) "
                        "judgments, orders, and AG opinions. Two-level chunking.",
            vectorizer_config=all_named_vectors(),
            inverted_index_config=inverted_index_config(),
            sharding_config=sharding_config(),
            replication_config=replication_config(),
            properties=[
                # Identity
                _keyword("celex"),
                _keyword("ecli", description="European Case Law Identifier, e.g. ECLI:EU:C:2009:405"),
                _keyword("eli_uri"),
                _keyword("chunk_id"),
                Property(name="chunk_index", data_type=DataType.INT, index_filterable=True),
                _keyword("content_hash"),

                # Text per language
                _text("text_en", tokenization=Tokenization.WORD),
                _text("text_el", tokenization=Tokenization.WORD),
                _text("text_de", tokenization=Tokenization.WORD),
                _text("text_fr", tokenization=Tokenization.WORD),
                _text("text_it", tokenization=Tokenization.WORD),

                # Summaries
                _text("document_summary",
                      description="3-5 sentence summary of the entire decision; stated holding required",
                      tokenization=Tokenization.TRIGRAM),
                _text("chunk_summary",
                      description="1-2 sentence summary of this specific chunk",
                      tokenization=Tokenization.TRIGRAM),
                _text("contextual_prefix",
                      description="~50-token prefix prepended at embed time",
                      tokenization=Tokenization.WORD, searchable=False),

                # Document metadata
                _filterable_text("document_subtype",
                                 description="judgment|order|ag_opinion"),
                _date("document_date"),
                _date("date_of_judgment"),
                Property(name="is_overturned", data_type=DataType.BOOL, index_filterable=True),
                _keyword("overturned_by", description="CELEX of overturning decision"),
                _text("source_citation", tokenization=Tokenization.WORD),
                Property(name="eurovoc_concepts", data_type=DataType.TEXT_ARRAY,
                         tokenization=Tokenization.WORD,
                         index_searchable=True, index_filterable=True),
                Property(name="eurovoc_ids", data_type=DataType.TEXT_ARRAY,
                         tokenization=Tokenization.FIELD, index_filterable=True),
                _text("title", tokenization=Tokenization.TRIGRAM),

                # Case-law-specific
                _filterable_text("court_level", description="CJ (Court of Justice) | GC (General Court)"),
                _filterable_text("procedure_type",
                                 description="preliminary-reference|direct-action|appeal|infringement|opinion"),
                _text("parties",
                      description="e.g. 'Commission v Greece'",
                      tokenization=Tokenization.TRIGRAM),
                _filterable_text("language_of_case",
                                 description="ISO 639-1 of authentic original (often 'fr')"),
                _filterable_text("chunk_type", description="holding | reasoning"),
                _text("case_summary",
                      description="Facts + decision, 3-5 sentences",
                      tokenization=Tokenization.TRIGRAM),
                _text("legal_principle",
                      description="The rule of law established, plain-English (Qwen3.6 Plus)",
                      tokenization=Tokenization.TRIGRAM),
                _text("holding",
                      description="Operative part restated clearly (Qwen3.6 Plus)",
                      tokenization=Tokenization.WORD),
                Property(name="regulations_interpreted", data_type=DataType.OBJECT_ARRAY,
                         nested_properties=[
                             Property(name="celex", data_type=DataType.TEXT,
                                      tokenization=Tokenization.FIELD),
                             Property(name="article", data_type=DataType.TEXT,
                                      tokenization=Tokenization.FIELD),
                             Property(name="strength", data_type=DataType.TEXT,
                                      tokenization=Tokenization.WORD),
                         ]),
                _filterable_text("authority_weight",
                                 description="binding (CJ/GC judgments) | persuasive (AG opinions)"),
                Property(name="judges", data_type=DataType.TEXT_ARRAY,
                         tokenization=Tokenization.WORD, index_filterable=True),
                _text("advocate_general", tokenization=Tokenization.WORD),

                # Shared LLM fields
                _filterable_text("legal_domain"),
                Property(name="topic_tags", data_type=DataType.TEXT_ARRAY,
                         tokenization=Tokenization.WORD,
                         index_searchable=True, index_filterable=True),
                Property(name="cross_references", data_type=DataType.TEXT_ARRAY,
                         tokenization=Tokenization.FIELD, index_filterable=True),
                Property(name="penalty_type", data_type=DataType.TEXT_ARRAY,
                         tokenization=Tokenization.WORD, index_filterable=True),
                Property(name="effective_dates", data_type=DataType.DATE_ARRAY,
                         index_filterable=True, index_range_filters=True),

                # Bookkeeping
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
