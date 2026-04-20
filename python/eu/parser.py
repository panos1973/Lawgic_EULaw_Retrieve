"""Stage 1b: parse CELLAR XHTML into chunks.

Per docs/handoff/07_RETRIEVAL.md chunking rules:

Legislation (article-level):
    - one article per chunk (200-800 words typical)
    - articles > 1500 words -> split at paragraph boundaries, keep heading
    - articles < 50 words -> group with adjacent short articles
    - recitals -> group 5-10 per chunk
    - annexes -> split by logical section

Case law (two-level):
    - 1 holding chunk per decision (operative part + findings + questions)
    - N reasoning chunks (3-8 per decision, groups of 3-5 numbered paragraphs)

Contextual prefix (Anthropic pattern, ~50 tokens, REQUIRED per 07_RETRIEVAL.md #1):
    "This is {chunk_type} {chunk_id} of {document_subtype} ({celex}) —
     {short_title}, within {parent_section_heading}. The chunk covers:"

Prefix is a template fill from structured data, NOT an LLM call.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from bs4 import BeautifulSoup


def build_contextual_prefix(*, celex: str, chunk_type: str, chunk_id: str,
                            document_subtype: str, short_title: str,
                            parent_section: str | None = None) -> str:
    parent = f", within {parent_section}" if parent_section else ""
    return (
        f"This is {chunk_type} {chunk_id} of {document_subtype} ({celex}) — "
        f"{short_title}{parent}. The chunk covers:"
    )


def parse_legislation_xhtml(xhtml: str, *, celex: str,
                            document_subtype: str, title: str) -> list[dict]:
    """XHTML -> article-level chunks. Returns list of chunk dicts ready for Stage 2."""
    soup = BeautifulSoup(xhtml, "lxml")
    chunks: list[dict] = []

    chapter = None
    for element in soup.find_all(["div", "article", "section", "p"]):
        classes = element.get("class", []) or []
        if any("chapter" in c.lower() for c in classes):
            chapter = element.get_text(" ", strip=True)[:200]
        if any("article" in c.lower() for c in classes):
            text = element.get_text("\n", strip=True)
            if not text:
                continue
            article_id = element.get("id") or f"art_{len(chunks)+1}"
            chunk_id = f"art_{article_id.replace('art_', '')}"
            chunks.append({
                "celex": celex,
                "chunk_id": chunk_id,
                "chunk_index": len(chunks),
                "chunk_type": "article",
                "text_en": text,
                "contextual_prefix": build_contextual_prefix(
                    celex=celex, chunk_type="Article", chunk_id=chunk_id,
                    document_subtype=document_subtype,
                    short_title=title[:80],
                    parent_section=chapter,
                ),
            })

    recital_group: list[str] = []
    for element in soup.find_all(["div", "p"]):
        classes = element.get("class", []) or []
        if any("recital" in c.lower() for c in classes):
            recital_group.append(element.get_text(" ", strip=True))
            if len(recital_group) >= 8:
                _flush_recital_group(chunks, celex, document_subtype, title, recital_group)
                recital_group = []
    if recital_group:
        _flush_recital_group(chunks, celex, document_subtype, title, recital_group)

    return chunks


def _flush_recital_group(chunks: list[dict], celex: str, document_subtype: str,
                         title: str, group: list[str]) -> None:
    idx = len([c for c in chunks if c["chunk_type"] == "recital"]) + 1
    chunk_id = f"recital_group_{idx}"
    chunks.append({
        "celex": celex,
        "chunk_id": chunk_id,
        "chunk_index": len(chunks),
        "chunk_type": "recital",
        "text_en": "\n\n".join(group),
        "contextual_prefix": build_contextual_prefix(
            celex=celex, chunk_type="Recital group", chunk_id=chunk_id,
            document_subtype=document_subtype, short_title=title[:80],
        ),
    })


def parse_case_law_xhtml(xhtml: str, *, celex: str, ecli: str | None,
                         title: str) -> list[dict]:
    """Two-level chunking per 07_RETRIEVAL.md. Holding chunk gets populated
    later by Stage 2 LLM (Qwen3.6 Plus reasoning on); this function only
    emits the empty holding shell + reasoning paragraph groups.
    """
    soup = BeautifulSoup(xhtml, "lxml")

    chunks: list[dict] = [{
        "celex": celex,
        "ecli": ecli,
        "chunk_id": "holding",
        "chunk_index": 0,
        "chunk_type": "holding",
        "text_en": "",
        "contextual_prefix": build_contextual_prefix(
            celex=celex, chunk_type="Holding", chunk_id="holding",
            document_subtype="judgment", short_title=title[:80],
        ),
    }]

    paragraphs = [p.get_text(" ", strip=True)
                  for p in soup.find_all("p")
                  if p.get_text(strip=True)]
    group_size = 5
    for i in range(0, len(paragraphs), group_size):
        group = paragraphs[i:i + group_size]
        chunk_id = f"reasoning_{i // group_size + 1}"
        chunks.append({
            "celex": celex,
            "ecli": ecli,
            "chunk_id": chunk_id,
            "chunk_index": len(chunks),
            "chunk_type": "reasoning",
            "text_en": "\n\n".join(group),
            "contextual_prefix": build_contextual_prefix(
                celex=celex, chunk_type="Reasoning", chunk_id=chunk_id,
                document_subtype="judgment", short_title=title[:80],
            ),
        })
    return chunks


def parse_file(path: Path | str, **kwargs) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        xhtml = f.read()
    if kwargs.get("document_type") == "case_law":
        return parse_case_law_xhtml(xhtml, **{k: v for k, v in kwargs.items() if k != "document_type"})
    return parse_legislation_xhtml(xhtml, **{k: v for k, v in kwargs.items() if k != "document_type"})
