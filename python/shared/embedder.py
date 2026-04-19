"""Voyage voyage-context-3 embedding + Weaviate upsert with named vectors.

Region-agnostic — called by python/eu/ ingestion stages and by
python/eu/language_adder.py. Mirrors the pattern from the shipping app
but adapted to named vectors per language (see docs/handoff/04_LANGUAGE_STRATEGY.md).

Embedding input composition (per docs/handoff/07_RETRIEVAL.md):
    legislation article chunk:
        contextual_prefix + " " + chunk_summary + " " + text
    legislation recital chunk:
        contextual_prefix + " " + text  (no chunk_summary needed)
    case law holding chunk:
        contextual_prefix + " " + case_summary + " " + legal_principle + " " + holding
    case law reasoning chunk:
        contextual_prefix + " " + chunk_summary + " " + text
"""

from __future__ import annotations

import os
from typing import Iterable

import voyageai
import weaviate
from weaviate.classes.data import DataObject

from .utils import deterministic_uuid, log


VOYAGE_MODEL = "voyage-context-3"
VOYAGE_DIMENSIONS = 1024


def _weaviate_client() -> weaviate.WeaviateClient:
    host = os.environ["WEAVIATE_HOST"]
    api_key = os.environ["WEAVIATE_API_KEY"]
    return weaviate.connect_to_weaviate_cloud(
        cluster_url=host,
        auth_credentials=weaviate.auth.AuthApiKey(api_key),
    )


def _voyage_client() -> voyageai.Client:
    return voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])


def compose_embedding_input(chunk: dict, language: str) -> str:
    """Build the string that actually gets embedded. Order + components matter."""
    text_field = f"text_{language}"
    text = chunk.get(text_field) or chunk.get("text_en") or ""
    prefix = chunk.get("contextual_prefix", "")
    chunk_type = chunk.get("chunk_type", "article")

    if chunk_type == "holding":
        summary = chunk.get("case_summary", "")
        principle = chunk.get("legal_principle", "")
        holding = chunk.get("holding", "")
        return " ".join(x for x in (prefix, summary, principle, holding) if x)
    if chunk_type == "recital":
        return " ".join(x for x in (prefix, text) if x)

    summary = chunk.get("chunk_summary", "")
    return " ".join(x for x in (prefix, summary, text) if x)


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Voyage context-3 embedding. Batches of up to 128 inputs."""
    client = _voyage_client()
    result = client.embed(
        texts=texts,
        model=VOYAGE_MODEL,
        input_type="document",
    )
    return result.embeddings


def upsert_chunks(*, collection_name: str, chunks: Iterable[dict], language: str) -> int:
    """Upsert chunks into EULaws or EUCourtDecisions with vector_<language>.

    Expects each chunk dict to already include all metadata fields
    (document_summary, chunk_summary, contextual_prefix, legal_domain, etc.).
    Deterministic uuid5(celex + "::" + chunk_id) so re-runs overwrite.
    """
    chunks_list = list(chunks)
    if not chunks_list:
        return 0

    inputs = [compose_embedding_input(c, language) for c in chunks_list]
    vectors = embed_batch(inputs)
    vector_name = f"vector_{language}"

    client = _weaviate_client()
    try:
        coll = client.collections.get(collection_name)
        objs = []
        for c, v in zip(chunks_list, vectors):
            uid = deterministic_uuid(c["celex"], c["chunk_id"])
            objs.append(DataObject(
                uuid=uid,
                properties=c,
                vector={vector_name: v},
            ))
        coll.data.insert_many(objs)
        return len(objs)
    finally:
        client.close()


def add_named_vector(*, collection_name: str, uuid_str: str,
                     language: str, text: str, vector: list[float]) -> None:
    """Patch a new named vector + text field onto an existing chunk. Used by
    python/eu/language_adder.py to layer vector_de / vector_fr / etc. onto
    chunks that already have vector_en."""
    client = _weaviate_client()
    try:
        coll = client.collections.get(collection_name)
        coll.data.update(
            uuid=uuid_str,
            properties={f"text_{language}": text},
            vector={f"vector_{language}": vector},
        )
    finally:
        client.close()
