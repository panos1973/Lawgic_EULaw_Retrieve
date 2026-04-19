"""Add a new language (text + named vector) to already-ingested docs.

Per docs/handoff/04_LANGUAGE_STRATEGY.md, the "add language" flow is
DELIBERATELY cheap: fetch XHTML -> parse -> embed. No LLM metadata
extraction (metadata stays English). No knowledge graph work (CELEX-based,
language-independent). Expected cost ~$100 per language for Tier A.

Critical: must NOT call Stage 2. Only fetch, parse, embed.

Steps:
    1. Enumerate CELEX with status='embedded' AND language='en' from
       EULawIngestionStatus.
    2. For each CELEX: fetch XHTML with Accept-Language: <target>.
    3. Parse using the SAME logic/ids as English so chunk_ids match.
    4. Embed text_<lang> via Voyage.
    5. Patch vector_<lang> + text_<lang> onto the existing Weaviate object.
    6. Mark EULawIngestionStatus (celex, target_lang, 'embedded').
"""

from __future__ import annotations

from pathlib import Path

from python.shared.embedder import add_named_vector, compose_embedding_input, embed_batch
from python.shared.status import list_embedded, mark
from python.shared.utils import deterministic_uuid, emit, sha256_text

from .fetcher import fetch_item_xhtml, save_xhtml
from .parser import parse_legislation_xhtml


def add_language(language_code: str, *, collection_name: str = "EULaws") -> dict:
    """Main entry point for the Electron 'Add language' flow."""
    if language_code == "en":
        raise ValueError("English is the primary metadata language; cannot re-add.")

    celex_list = list_embedded(language="en")
    emit("add_language_started", language=language_code, celex_count=len(celex_list))

    added = 0
    missing = 0
    failed = 0

    for celex in celex_list:
        try:
            xhtml = fetch_item_xhtml(_item_uri_for(celex), language_code=language_code)
            if xhtml is None:
                mark(celex, language_code, "missing_source",
                     document_type="legislation")
                missing += 1
                continue

            save_xhtml(celex, language_code, xhtml)
            chunks = parse_legislation_xhtml(
                xhtml, celex=celex,
                document_subtype="regulation",
                title="",
            )
            if not chunks:
                failed += 1
                continue

            for chunk in chunks:
                chunk[f"text_{language_code}"] = chunk.pop("text_en")
            inputs = [compose_embedding_input(c, language_code) for c in chunks]
            vectors = embed_batch(inputs)
            for chunk, vec in zip(chunks, vectors):
                add_named_vector(
                    collection_name=collection_name,
                    uuid_str=deterministic_uuid(celex, chunk["chunk_id"]),
                    language=language_code,
                    text=chunk[f"text_{language_code}"],
                    vector=vec,
                )

            mark(celex, language_code, "embedded",
                 document_type="legislation",
                 text_hash=sha256_text(xhtml))
            added += 1
            emit("add_language_doc_ok", celex=celex, language=language_code,
                 chunks=len(chunks))
        except Exception as e:  # noqa: BLE001
            mark(celex, language_code, "failed_embed",
                 document_type="legislation", error_message=str(e))
            failed += 1
            emit("add_language_doc_failed", celex=celex,
                 language=language_code, error=str(e))

    summary = {"added": added, "missing": missing, "failed": failed,
               "language": language_code}
    emit("add_language_completed", **summary)
    return summary


def _item_uri_for(celex: str) -> str:
    """EUR-Lex item URI convention for CELEX fetches. Placeholder — the real
    URI usually comes from the SPARQL result; in language_adder we don't have
    the SPARQL round-trip. Two options:
        A) store item_uri in EULawIngestionStatus at first fetch,
        B) derive from CELEX via eur-lex content negotiation.
    For MVP we rely on CELLAR content-negotiation URLs.
    """
    return f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}"
