"""Create the EULaws Weaviate collection on the lawgicfeb26 cluster.

Schema is locked in docs/handoff/03_SCHEMAS.md section 1 (35 fields total).
Named vectors per language, all HNSW + 8-bit RQ + DOT distance.

English vector is mandatory. Other language slots (vector_el, vector_de,
vector_fr, vector_it) are configured in the schema but only populated
when that language's ingestion runs.

Idempotent: if the collection exists, this script is a no-op (does NOT
drop-and-recreate — too dangerous against a production cluster).
"""

from __future__ import annotations

import os

import weaviate
from weaviate.classes.config import Configure, DataType, Property, VectorDistances


COLLECTION_NAME = "EULaws"


def _named_vector(name: str):
    return Configure.NamedVectors.none(
        name=name,
        vector_index_config=Configure.VectorIndex.hnsw(
            quantizer=Configure.VectorIndex.Quantizer.rq(bits=8),
            distance_metric=VectorDistances.DOT,
        ),
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
            vectorizer_config=[
                _named_vector("vector_en"),
                _named_vector("vector_el"),
                _named_vector("vector_de"),
                _named_vector("vector_fr"),
                _named_vector("vector_it"),
            ],
            properties=[
                # Identification
                Property(name="celex", data_type=DataType.TEXT),
                Property(name="eli_uri", data_type=DataType.TEXT),
                Property(name="chunk_id", data_type=DataType.TEXT),
                Property(name="chunk_index", data_type=DataType.INT),
                Property(name="content_hash", data_type=DataType.TEXT),
                # Text per language
                Property(name="text_en", data_type=DataType.TEXT),
                Property(name="text_el", data_type=DataType.TEXT),
                Property(name="text_de", data_type=DataType.TEXT),
                Property(name="text_fr", data_type=DataType.TEXT),
                Property(name="text_it", data_type=DataType.TEXT),
                # Summaries (English only)
                Property(name="document_summary", data_type=DataType.TEXT),
                Property(name="chunk_summary", data_type=DataType.TEXT),
                Property(name="contextual_prefix", data_type=DataType.TEXT),
                # Document metadata
                Property(name="document_subtype", data_type=DataType.TEXT),
                Property(name="document_date", data_type=DataType.DATE),
                Property(name="date_in_force", data_type=DataType.DATE),
                Property(name="in_force", data_type=DataType.BOOL),
                Property(name="superseded_by", data_type=DataType.TEXT),
                Property(name="source_citation", data_type=DataType.TEXT),
                Property(name="eurovoc_concepts", data_type=DataType.TEXT_ARRAY),
                Property(name="eurovoc_ids", data_type=DataType.TEXT_ARRAY),
                # LLM metadata (English, controlled vocab)
                Property(name="legal_domain", data_type=DataType.TEXT),
                Property(name="topic_tags", data_type=DataType.TEXT_ARRAY),
                Property(name="obligations", data_type=DataType.OBJECT_ARRAY,
                         nested_properties=[
                             Property(name="actor", data_type=DataType.TEXT),
                             Property(name="action", data_type=DataType.TEXT),
                             Property(name="deadline", data_type=DataType.TEXT),
                             Property(name="condition", data_type=DataType.TEXT),
                         ]),
                Property(name="applies_to", data_type=DataType.TEXT_ARRAY),
                Property(name="definitions", data_type=DataType.OBJECT,
                         nested_properties=[
                             Property(name="term", data_type=DataType.TEXT),
                             Property(name="definition", data_type=DataType.TEXT),
                         ]),
                Property(name="cross_references", data_type=DataType.TEXT_ARRAY),
                Property(name="penalty_type", data_type=DataType.TEXT_ARRAY),
                Property(name="effective_dates", data_type=DataType.DATE_ARRAY),
                Property(name="international_conventions", data_type=DataType.TEXT_ARRAY),
                # Ingestion bookkeeping
                Property(name="language_list", data_type=DataType.TEXT_ARRAY),
                Property(name="fetched_at", data_type=DataType.DATE),
                Property(name="extracted_at", data_type=DataType.DATE),
                Property(name="word_count", data_type=DataType.INT),
                Property(name="char_count", data_type=DataType.INT),
            ],
        )
        print(f"Created collection {COLLECTION_NAME}.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
