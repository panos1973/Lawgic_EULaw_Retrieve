# Data Sources

## Primary source: CELLAR

**CELLAR** = the EU Publications Office's semantic knowledge graph containing all EU legal documents, their metadata, and their relationships. Publicly accessible, no API keys, no registration required. All content is public domain under the EU open data policy.

- **SPARQL endpoint:** `https://publications.europa.eu/webapi/rdf/sparql`
- **Item download endpoint:** derived from SPARQL query results (each work/expression has a `?item` URI serving XHTML, HTML, PDF, etc.)
- **Atom notification feed:** `https://publications.europa.eu/webapi/notification/` — Pillar IV feed for real-time new-document events
- **Ontology:** Common Data Model (CDM) at `http://publications.europa.eu/ontology/cdm`
- **Supplementary ontology:** European Legislation Identifier (ELI) at `https://data.europa.eu/eli/ontology`

## How to fetch

Three query types, all needed:

### Fetch #1 — Legislation query
```sparql
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

SELECT DISTINCT ?celex ?title ?date ?type ?inForce ?item
WHERE {
  VALUES (?eurovoc) {
    # priority_domains.json config — see below
  }
  ?work cdm:work_is_about_concept_eurovoc ?eurovoc .
  ?work cdm:work_has_resource-type ?type .
  FILTER(?type IN (
    <http://publications.europa.eu/resource/authority/resource-type/REG>,
    <http://publications.europa.eu/resource/authority/resource-type/REG_IMPL>,
    <http://publications.europa.eu/resource/authority/resource-type/REG_DEL>,
    <http://publications.europa.eu/resource/authority/resource-type/DIR>,
    <http://publications.europa.eu/resource/authority/resource-type/DIR_IMPL>,
    <http://publications.europa.eu/resource/authority/resource-type/DEC>
  ))
  ?work cdm:resource_legal_id_celex ?celex .
  OPTIONAL { ?work cdm:work_date_document ?date . }
  OPTIONAL { ?work cdm:resource_legal_in-force ?inForce . }
  ?expr cdm:expression_belongs_to_work ?work ;
        cdm:expression_uses_language
          <http://publications.europa.eu/resource/authority/language/ENG> ;
        cdm:expression_title ?title .
  ?manif cdm:manifestation_manifests_expression ?expr ;
         cdm:manifestation_type "xhtml" .
  ?item cdm:item_belongs_to_manifestation ?manif .
  FILTER NOT EXISTS { ?work cdm:do_not_index "true"^^xsd:boolean }
  FILTER NOT EXISTS {
    ?work cdm:work_has_resource-type
      <http://publications.europa.eu/resource/authority/resource-type/CORRIGENDUM>
  }
}
ORDER BY DESC(?date)
LIMIT 500
```

### Fetch #2 — Case law query (both court levels)
Replace the resource-type FILTER with:
```sparql
FILTER(?type IN (
  <http://publications.europa.eu/resource/authority/resource-type/JUDG>,
  <http://publications.europa.eu/resource/authority/resource-type/ORDER>,
  <http://publications.europa.eu/resource/authority/resource-type/OPIN_AG>
))
```
Also add:
```sparql
OPTIONAL { ?work cdm:case-law_ecli ?ecli . }
OPTIONAL { ?work cdm:case-law_delivered_by_court ?court . }
OPTIONAL { ?work cdm:case-law_has_type_procedure ?procType . }
```

### Fetch #3 — Amendment relationships query
```sparql
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>

SELECT DISTINCT ?source_celex ?target_celex ?relationship ?date
WHERE {
  VALUES (?eurovoc) { ... priority domains ... }
  ?source cdm:work_is_about_concept_eurovoc ?eurovoc .
  ?source cdm:resource_legal_id_celex ?source_celex .
  {
    ?source cdm:resource_legal_amends_resource_legal ?target .
    BIND("amends" AS ?relationship)
  } UNION {
    ?source cdm:resource_legal_repeals_resource_legal ?target .
    BIND("repeals" AS ?relationship)
  }
  ?target cdm:resource_legal_id_celex ?target_celex .
  OPTIONAL { ?source cdm:work_date_document ?date . }
}
ORDER BY DESC(?date)
```

## CDM predicates — CRITICAL WARNING

**The predicate names above came from web searches, NOT from parsing the live CDM ontology. They are probably mostly correct but NOT guaranteed verbatim.** SPARQL queries fail silently on misspelled predicates (return zero results, no error).

**Before putting these queries into production:**
1. Run `scripts/parse_cdm_ontology.py` — uses `rdflib` to walk the ontology at `http://publications.europa.eu/ontology/cdm`, extracts all predicates with domain including `cdm:resource_legal` or `cdm:case-law`, persists to `config/cdm_predicates.json`.
2. Cross-reference against the [eurlex R package's tested SPARQL query library](https://michalovadek.github.io/eurlex/reference/elx_make_query.html).
3. Run each query once with a tiny LIMIT (5) against the live endpoint to confirm non-empty results.

Known likely-correct predicates to verify:
- `cdm:resource_legal_amends_resource_legal`
- `cdm:resource_legal_repeals_resource_legal`
- `cdm:resource_legal_based_on_resource_legal`
- `cdm:resource_legal_corrected_by_resource_legal`
- `cdm:consolidated_by`
- `cdm:case-law_interprets_resource_legal`
- `cdm:case-law_cites_resource_legal`
- `cdm:work_cites_work`
- `cdm:resource_legal_implements`
- `cdm:resource_legal_in_force`
- `cdm:work_date_document`
- `cdm:case-law_ecli`
- `cdm:case-law_delivered_by_court`

## Incremental updates via Pillar IV Atom feed

Do NOT use date-based SPARQL queries for incremental updates. `cdm:work_date_document` is the legal date, which is NOT monotonic (a law dated last month can appear today). Instead, use the CELLAR Atom feed which gives monotonic publication events.

**Watermark implementation:**
- Store the last Atom entry ID processed in `EULawIngestionStatus` implicitly (max `cellar_recorded_at` of embedded rows).
- On each incremental run, poll the Atom feed for entries newer than the watermark.
- For each new entry, extract the CELEX URI, process through the full pipeline.
- After successful embed, the `cellar_recorded_at` field on `EULawIngestionStatus` advances the watermark automatically.

## Priority EuroVoc domains for Tier A MVP

Replace the maritime concepts (4830, 5889, 2524, 2455) with legal-practice domains:

| EuroVoc ID | Domain | Priority |
|---|---|---|
| 754 | data protection | Tier 1 |
| 711 | employment | Tier 1 |
| 710 | competition (antitrust) | Tier 1 |
| 890 | tax law | Tier 1 |
| 3365 | intellectual property | Tier 1 |
| 4358 | environmental protection | Tier 2 |
| 878 | consumer protection | Tier 2 |
| 727 | company law | Tier 2 |
| 2495 | criminal law | Tier 2 |
| 2490 | asylum and immigration | Tier 2 |
| 2445 | financial services | Tier 2 |
| 2482 | commercial law | Tier 2 |

**IMPORTANT:** these EuroVoc IDs are illustrative. **Verify each one against the live EuroVoc thesaurus** at `http://eurovoc.europa.eu/` before trusting them. Wrong IDs return zero SPARQL results silently.

## XHTML download

After SPARQL returns `?item` URIs:
```
GET {item_uri}
Accept: application/xhtml+xml
Accept-Language: en  (or el, de, fr, it depending on target language)
```

EU Publications Office serves the same CELEX in all 24 official languages at the same item URI — language is selected via `Accept-Language` header. This is why adding a new language is cheap (no re-SPARQL, just re-HTTP-GET).

## Courtesy rate limiting

CELLAR is a public endpoint. The shipping app's EU config uses:
```json
{ "page_size": 500, "max_pages": 20, "courtesy_delay_seconds": 1 }
```
Keep these or be more conservative. Never parallelize SPARQL against CELLAR beyond ~5 concurrent connections.

## Content licensing

All EU data is **public domain** under the EU open data policy (Commission Decision 2011/833/EU). No licensing restrictions, no attribution requirements for machine-readable use. Safe to embed, re-distribute, commercialize.
