"""Parse the live CDM ontology OWL file and emit authoritative predicate names.

Per docs/handoff/02_DATA_SOURCES.md, the predicate names in config/cdm_predicates.json
are provisional (sourced from web search, not the live ontology). SPARQL queries
fail SILENTLY on misspelled predicates (zero results, no error). This module
exists so we can verify predicates programmatically before committing to production.

Usage (called from scripts/parse_cdm_ontology.py):
    predicates = fetch_and_parse_cdm()
    save_to_config(predicates, "config/cdm_predicates.json")
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


CDM_ONTOLOGY_URL = "http://publications.europa.eu/ontology/cdm"


def fetch_and_parse_cdm() -> dict[str, list[str]]:
    """Walk the CDM OWL graph via rdflib; extract predicates grouped by domain.

    Groups returned:
        - legislation  (domain includes cdm:resource_legal)
        - case_law     (domain includes cdm:case-law)
        - expression   (cdm:expression_*)
        - manifestation (cdm:manifestation_*)
        - item         (cdm:item_*)
        - work         (cdm:work_*)
    """
    import rdflib  # local import — heavy dep

    g = rdflib.Graph()
    g.parse(CDM_ONTOLOGY_URL, format="xml")

    cdm_ns = "http://publications.europa.eu/ontology/cdm#"
    rdf_property = rdflib.URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
    owl_property_types = [
        rdflib.URIRef("http://www.w3.org/2002/07/owl#ObjectProperty"),
        rdflib.URIRef("http://www.w3.org/2002/07/owl#DatatypeProperty"),
    ]

    all_predicates: list[str] = []
    for pt in owl_property_types:
        for s in g.subjects(rdf_property, pt):
            if str(s).startswith(cdm_ns):
                all_predicates.append(str(s).replace(cdm_ns, "cdm:"))

    groups: dict[str, list[str]] = {
        "legislation": [],
        "case_law": [],
        "expression": [],
        "manifestation": [],
        "item": [],
        "work": [],
        "other": [],
    }
    for p in sorted(set(all_predicates)):
        name = p.replace("cdm:", "")
        if name.startswith("resource_legal"):
            groups["legislation"].append(p)
        elif name.startswith("case-law"):
            groups["case_law"].append(p)
        elif name.startswith("expression"):
            groups["expression"].append(p)
        elif name.startswith("manifestation"):
            groups["manifestation"].append(p)
        elif name.startswith("item"):
            groups["item"].append(p)
        elif name.startswith("work"):
            groups["work"].append(p)
        else:
            groups["other"].append(p)
    return groups


def save_to_config(predicates: dict[str, Any], path: str | Path) -> None:
    import datetime as dt
    import json

    out = {
        "_verified": True,
        "_last_parsed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "_source": CDM_ONTOLOGY_URL,
        "all_predicates_by_domain": predicates,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
