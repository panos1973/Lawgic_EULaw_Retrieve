"""Shared Weaviate schema building blocks.

Every EU collection (EULaws, EUCourtDecisions, EUAmendments, EULawIngestionStatus)
reuses these configs. Ported from the production DocumentVault setup with
extensions for EU-specific bilingual (English + Greek) content.

If you need to tune retrieval, tune it HERE — one place, applies everywhere.
"""

from __future__ import annotations

from weaviate.classes.config import (
    Configure,
    StopwordsPreset,
    VectorDistances,
)


# HNSW + 8-bit RQ — the Vault-grade tuning. 98-99% recall, 4x compression,
# no training phase. `rescore_limit=200` is the retry budget when the
# quantized vectors are too close to tell apart.
HNSW_WITH_RQ = Configure.VectorIndex.hnsw(
    distance_metric=VectorDistances.DOT,
    quantizer=Configure.VectorIndex.Quantizer.rq(rescore_limit=200),
    ef=200,
    ef_construction=256,
    max_connections=32,
    dynamic_ef_min=100,
    dynamic_ef_max=500,
    dynamic_ef_factor=8,
    flat_search_cutoff=10_000,
    cleanup_interval_seconds=300,
)


# BM25 tuned for long legal documents. Lower b (0.3) = less length penalty.
# Higher k1 (1.5) = meaningful term-repetition saturation.
# index_null_state=True enables filtering by IS NULL (used for
# superseded_by / overturned_by nullable fields).
GREEK_STOPWORDS = [
    # Articles (12)
    "ο", "η", "το", "οι", "τα", "τις", "τους", "των", "τον", "την", "του", "της",
    # Prepositions (33)
    "σε", "στο", "στη", "στον", "στην", "στα", "στους", "στις",
    "από", "για", "με", "μέσω", "κατά", "μεταξύ", "προς", "εκ", "εξ", "δια",
    "υπό", "επί", "παρά", "περί", "ως", "έως", "μέχρι", "μετά", "πριν",
    "χωρίς", "εντός", "εκτός", "λόγω", "βάσει", "δυνάμει",
    # Conjunctions (18)
    "και", "ή", "αλλά", "ούτε", "είτε", "μήτε", "ωστόσο", "όμως", "ενώ",
    "αν", "εάν", "εφόσον", "αφού", "ότι", "πως", "ώστε", "όπως", "δηλαδή",
    # Personal / demonstrative pronouns (7)
    "αυτός", "αυτή", "αυτό", "αυτοί", "αυτές", "αυτά", "αυτών",
    # Relative pronouns (7)
    "οποίος", "οποία", "οποίο", "οποίοι", "οποίες", "οποίων", "οποίους",
    # Other pronouns / determiners (4)
    "εκείνος", "εκείνη", "εκείνο", "κάθε",
    # High-frequency auxiliary verbs (6)
    "είναι", "έχει", "έχουν", "μπορεί", "πρέπει", "δύναται",
    # Common adverbs (13)
    "δεν", "μη", "μην", "δε", "όχι", "ναι",
    "πολύ", "πιο", "πλέον", "ήδη", "επίσης", "ακόμη", "ακόμα",
    # Legal boilerplate (2)
    "ανωτέρω", "κατωτέρω",
]

# English legal boilerplate — curated. Weaviate's StopwordsPreset.EN covers
# generic English; these add legal-text-specific function words that would
# otherwise dominate BM25 scores in an EU-law corpus.
ENGLISH_LEGAL_STOPWORDS = [
    "hereinafter", "hereto", "herein", "hereof", "hereby", "thereto",
    "whereas", "wherein", "whereby", "thereof", "thereafter", "therein",
    "thereby", "aforesaid", "aforementioned", "notwithstanding", "pursuant",
    "respectively", "accordingly", "thereunder", "hereunder",
]

STOPWORDS_MULTILINGUAL = ENGLISH_LEGAL_STOPWORDS + GREEK_STOPWORDS


def inverted_index_config():
    """Returns a fresh config. Call per-collection because `Configure` is mutable."""
    return Configure.inverted_index(
        bm25_b=0.3,
        bm25_k1=1.5,
        cleanup_interval_seconds=60,
        index_timestamps=True,
        index_property_length=True,
        index_null_state=True,
        stopwords_preset=StopwordsPreset.EN,
        stopwords_additions=STOPWORDS_MULTILINGUAL,
    )


def sharding_config():
    return Configure.sharding(
        virtual_per_physical=128,
        desired_count=1,
        desired_virtual_count=128,
    )


def replication_config():
    return Configure.replication(factor=1)


def named_vector(language_code: str):
    """Per-language named vector. Name convention: vector_<iso-639-1>."""
    return Configure.NamedVectors.none(
        name=f"vector_{language_code}",
        vector_index_config=HNSW_WITH_RQ,
    )


# Languages whose named-vector slot we reserve in every content collection.
# Slots are cheap when empty — only populated after the language is ingested.
RESERVED_LANGUAGES = ("en", "el", "de", "fr", "it")


def all_named_vectors():
    return [named_vector(lang) for lang in RESERVED_LANGUAGES]
