"""Stage 1: fetch CELEX list from CELLAR SPARQL + download XHTML per language.

Per docs/handoff/02_DATA_SOURCES.md, CELLAR is the EU Publications Office's
semantic knowledge graph. No API keys, no registration. Public domain content.

Rate-limit rules (from endpoints.json):
    - <= 5 concurrent SPARQL connections
    - 1 second courtesy delay between pages
    - Never paginate beyond max_pages without explicit override

Three query types:
    1. Legislation   -> REG / DIR / DEC resource types
    2. Case law      -> JUDG / ORDER / OPIN_AG resource types
    3. Amendments    -> amends/repeals/based_on/etc. edges

Incremental updates use the Pillar IV Atom feed (monotonic publication
events), NOT date-based SPARQL (work_date_document is the legal date and
is NOT monotonic).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Iterable, Literal

import requests
from SPARQLWrapper import SPARQLWrapper, JSON

from python.shared.utils import DATA_DIR, ensure_dir, emit, load_config, sha256_text


DocumentType = Literal["legislation", "case_law"]


def _sparql() -> SPARQLWrapper:
    endpoints = load_config("endpoints")
    s = SPARQLWrapper(endpoints["cellar_sparql"])
    s.setReturnFormat(JSON)
    s.agent = "Lawgic_EULaw_Retrieve/0.1 (https://lawgic.gr)"
    return s


def _eurovoc_values_block() -> str:
    """Build the VALUES (?eurovoc) { ... } block from priority_domains.json."""
    pd = load_config("priority_domains")
    uris = [f"<{d['uri']}>" for d in pd["tier_1"] + pd["tier_2"]]
    return "VALUES (?eurovoc) { (" + ") (".join(uris) + ") }"


def _resource_type_filter(doc_type: DocumentType) -> str:
    preds = load_config("cdm_predicates")["resource_types"]
    if doc_type == "legislation":
        keys = ["regulation", "regulation_implementing", "regulation_delegated",
                "directive", "directive_implementing", "decision"]
    else:
        keys = ["judgment", "order", "ag_opinion"]
    uris = [f"<{preds[k]}>" for k in keys]
    return "FILTER(?type IN (" + ", ".join(uris) + "))"


def build_legislation_query(language_code: str = "ENG", limit: int = 500) -> str:
    """Legislation SPARQL query. See docs/handoff/02_DATA_SOURCES.md Fetch #1."""
    preds = load_config("cdm_predicates")
    lang_uri = preds["languages"][{"ENG": "en", "ELL": "el"}.get(language_code, "en")]
    return f"""
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

SELECT DISTINCT ?celex ?title ?date ?type ?inForce ?item
WHERE {{
  {_eurovoc_values_block()}
  ?work {preds['legislation']['eurovoc_concept']} ?eurovoc .
  ?work {preds['legislation']['resource_type']} ?type .
  {_resource_type_filter('legislation')}
  ?work {preds['legislation']['identifier_celex']} ?celex .
  OPTIONAL {{ ?work {preds['legislation']['date_document']} ?date . }}
  OPTIONAL {{ ?work {preds['legislation']['in_force']} ?inForce . }}
  ?expr {preds['expression']['belongs_to_work']} ?work ;
        {preds['expression']['uses_language']} <{lang_uri}> ;
        {preds['expression']['title']} ?title .
  ?manif {preds['manifestation']['manifests_expression']} ?expr ;
         {preds['manifestation']['type']} "xhtml" .
  ?item {preds['item']['belongs_to_manifestation']} ?manif .
  FILTER NOT EXISTS {{ ?work {preds['legislation']['do_not_index']} "true"^^xsd:boolean }}
  FILTER NOT EXISTS {{ ?work {preds['legislation']['resource_type']} <{preds['resource_types']['corrigendum']}> }}
}}
ORDER BY DESC(?date)
LIMIT {limit}
"""


def build_case_law_query(language_code: str = "ENG", limit: int = 500) -> str:
    """Case law SPARQL query. Includes ECLI, court, procedure type."""
    preds = load_config("cdm_predicates")
    lang_uri = preds["languages"][{"ENG": "en", "ELL": "el"}.get(language_code, "en")]
    return f"""
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

SELECT DISTINCT ?celex ?ecli ?title ?date ?type ?court ?procType ?item
WHERE {{
  {_eurovoc_values_block()}
  ?work {preds['legislation']['eurovoc_concept']} ?eurovoc .
  ?work {preds['legislation']['resource_type']} ?type .
  {_resource_type_filter('case_law')}
  ?work {preds['legislation']['identifier_celex']} ?celex .
  OPTIONAL {{ ?work {preds['case_law']['ecli']} ?ecli . }}
  OPTIONAL {{ ?work {preds['case_law']['delivered_by_court']} ?court . }}
  OPTIONAL {{ ?work {preds['case_law']['has_type_procedure']} ?procType . }}
  OPTIONAL {{ ?work {preds['legislation']['date_document']} ?date . }}
  ?expr {preds['expression']['belongs_to_work']} ?work ;
        {preds['expression']['uses_language']} <{lang_uri}> ;
        {preds['expression']['title']} ?title .
  ?manif {preds['manifestation']['manifests_expression']} ?expr ;
         {preds['manifestation']['type']} "xhtml" .
  ?item {preds['item']['belongs_to_manifestation']} ?manif .
}}
ORDER BY DESC(?date)
LIMIT {limit}
"""


def build_amendments_query(limit: int = 2000) -> str:
    """Amendment/repeal/based_on/corrigendum edges at document level.

    Produces confidence=1.0 edges for eu_law_edges Pass 1.
    LLM extraction during Stage 2 produces article-level edges (Pass 2).
    """
    preds = load_config("cdm_predicates")
    return f"""
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>

SELECT DISTINCT ?source_celex ?target_celex ?relationship ?date
WHERE {{
  {_eurovoc_values_block()}
  ?source {preds['legislation']['eurovoc_concept']} ?eurovoc .
  ?source {preds['legislation']['identifier_celex']} ?source_celex .
  {{
    ?source {preds['relationships']['amends']} ?target .
    BIND("amends" AS ?relationship)
  }} UNION {{
    ?source {preds['relationships']['repeals']} ?target .
    BIND("repeals" AS ?relationship)
  }} UNION {{
    ?source {preds['relationships']['based_on']} ?target .
    BIND("based_on" AS ?relationship)
  }}
  ?target {preds['legislation']['identifier_celex']} ?target_celex .
  OPTIONAL {{ ?source {preds['legislation']['date_document']} ?date . }}
}}
ORDER BY DESC(?date)
LIMIT {limit}
"""


def run_sparql(query: str) -> list[dict]:
    s = _sparql()
    s.setQuery(query)
    results = s.query().convert()
    return results["results"]["bindings"]


def fetch_item_xhtml(item_uri: str, language_code: str = "en",
                     timeout: int = 60) -> str | None:
    """GET a CELLAR item URI with Accept-Language. 24 languages share one URI."""
    resp = requests.get(
        item_uri,
        headers={
            "Accept": "application/xhtml+xml,application/xml;q=0.9,text/html;q=0.8",
            "Accept-Language": language_code,
            "User-Agent": "Lawgic_EULaw_Retrieve/0.1 (https://lawgic.gr)",
        },
        timeout=timeout,
    )
    if resp.status_code == 200:
        return resp.text
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return None


def save_xhtml(celex: str, language: str, xhtml: str) -> Path:
    out_dir = ensure_dir(DATA_DIR / "eu" / "xhtml" / language)
    out_path = out_dir / f"{celex}.xhtml"
    out_path.write_text(xhtml, encoding="utf-8")
    return out_path


def run_legislation_fetch(*, domain: str | None = None,
                          language: str = "en",
                          limit: int = 500) -> Iterable[dict]:
    """End-to-end: SPARQL -> XHTML download. Emits one event per doc."""
    endpoints = load_config("endpoints")
    delay = endpoints["courtesy"]["sparql_courtesy_delay_seconds"]

    emit("fetch_started", document_type="legislation", language=language,
         domain=domain, limit=limit)
    rows = run_sparql(build_legislation_query(
        language_code="ENG" if language == "en" else "ELL",
        limit=limit,
    ))
    emit("fetch_sparql_done", row_count=len(rows))

    for row in rows:
        celex = row["celex"]["value"]
        item_uri = row["item"]["value"]
        title = row.get("title", {}).get("value", "")
        try:
            xhtml = fetch_item_xhtml(item_uri, language_code=language)
            if xhtml is None:
                emit("fetch_missing_source", celex=celex, language=language)
                continue
            path = save_xhtml(celex, language, xhtml)
            yield {
                "celex": celex,
                "title": title,
                "item_uri": item_uri,
                "xhtml_path": str(path),
                "text_hash": sha256_text(xhtml),
                "language": language,
            }
            emit("fetch_ok", celex=celex, language=language, chars=len(xhtml))
        except Exception as e:  # noqa: BLE001
            emit("fetch_failed", celex=celex, language=language, error=str(e))
        time.sleep(delay)
