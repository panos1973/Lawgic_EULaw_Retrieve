# Lawgic EU Law Retrieve

Electron desktop app + Python pipeline that fetches, enriches, embeds, and
tracks European Union legislation and case law for use by the
[Lawgic](https://lawgic.gr) legal AI platform.

**Source of truth for all design decisions:** [`docs/handoff/`](docs/handoff/)
(11 numbered files, read them in order).

## Quick status

- **Phase 1 (scaffold):** in progress — branch `claude/setup-electron-eu-law-GyG5W`
- **Phase 2 (first English ingestion):** not started
- **Phase 3 (knowledge graph):** not started

## Architecture in one paragraph

A CELLAR SPARQL + Atom-feed fetcher pulls EU documents; a parser splits them
into chunks (article-level for legislation, two-level for case law) with an
Anthropic-style contextual prefix; Qwen3.5 Flash (default) and Qwen3.6 Plus
(case-law reasoning, amendments) enrich each chunk with English metadata
via DashScope OpenAI-compat; Voyage `voyage-context-3` embeds the result;
a Weaviate cluster (user-configured) stores chunks in **four** collections:
`EULaws`, `EUCourtDecisions`, `EUAmendments` (atomic amendments with text +
vectors), and `EULawIngestionStatus` (per-document state). **No Postgres** —
everything in Weaviate.

## Repo layout

```
Lawgic_EULaw_Retrieve/
├── electron/                    # Electron shell
│   ├── main.js
│   ├── preload.js
│   └── renderer/
│       ├── index.html
│       ├── styles.css
│       └── renderer.js
├── config/                      # JSON configs (checked into git, non-secret)
│   ├── languages.json
│   ├── priority_domains.json    # EuroVoc concepts for MVP scope
│   ├── controlled_vocab.json    # legal_domain / topic_tags / applies_to / ...
│   ├── cdm_predicates.json      # provisional — run scripts/parse_cdm_ontology.py
│   └── endpoints.json
├── python/
│   ├── pipeline.py              # Thin CLI dispatcher
│   ├── eu/
│   │   ├── fetcher.py           # CELLAR SPARQL + Atom + XHTML download
│   │   ├── parser.py            # XHTML → chunks (article / two-level)
│   │   ├── extractor.py         # LLM metadata (DashScope Qwen + Gemini fallback)
│   │   ├── amendment_extractor.py # SPARQL + LLM → EUAmendments Weaviate upsert
│   │   ├── language_adder.py    # "Add language" flow (text + named vector only)
│   │   └── model_router.py      # task → model mapping (05_MODEL_STACK.md)
│   ├── shared/
│   │   ├── embedder.py          # Voyage + Weaviate upsert with named vectors
│   │   ├── status.py            # EULawIngestionStatus R/W
│   │   ├── cdm_ontology.py      # rdflib parser for CDM OWL
│   │   ├── weaviate_config.py   # Shared HNSW / BM25 / stopwords / sharding
│   │   └── utils.py             # config loader, emit(), sha256, uuid5
│   ├── create_eulaws_collection.py
│   ├── create_eucourt_collection.py
│   ├── create_euamendments_collection.py
│   └── create_eustatus_collection.py
├── scripts/
│   ├── parse_cdm_ontology.py    # one-off: rewrite config/cdm_predicates.json
│   ├── verify_qwen_cache.py     # one-off: probe DashScope caching
│   ├── verify_eurovoc_ids.py    # one-off: verify config/priority_domains.json
│   ├── estimate_cost.py         # dry-run cost projection
│   └── eval_extraction.py       # 20-doc quality eval
├── docs/handoff/                # The 11 architecture documents
└── package.json
```

## Installation (development)

```bash
# 1. Python env
cd python
python3.11 -m venv ../.venv
source ../.venv/bin/activate
pip install -r requirements.txt

# 2. Node + Electron
cd ..
npm install

# 3. Start the app
npm start
```

## First-run checklist

Before any ingestion (per `docs/handoff/09_IMPLEMENTATION_PLAN.md` Phase 1):

- [ ] `python scripts/parse_cdm_ontology.py` — rewrites `config/cdm_predicates.json` with verified predicates
- [ ] `python scripts/verify_eurovoc_ids.py` — confirms priority-domain EuroVoc IDs resolve
- [ ] Open the app, fill in Settings (DashScope, Voyage, Weaviate)
- [ ] `python python/create_eulaws_collection.py`
- [ ] `python python/create_eucourt_collection.py`
- [ ] `python python/create_euamendments_collection.py`
- [ ] `python python/create_eustatus_collection.py`
- [ ] `python scripts/verify_qwen_cache.py` — confirm caching works on chosen endpoint

## Locked decisions

See `docs/handoff/00_OVERVIEW.md` for the full list. Short version:
- Separate Weaviate collections per document type, **not** per language
- Named vectors per language within collections (Weaviate 1.24+)
- English is the primary metadata language
- State tracking lives in `EULawIngestionStatus`, not on disk
- **Everything in Weaviate** (revised 2026-04): amendments moved from a Postgres `eu_law_edges` table into a `EUAmendments` Weaviate collection with vectors + text
- Model stack: Qwen3.5 Flash + Qwen3.6 Plus + Gemini fallback. No Claude.
- Contextual retrieval prefix (Anthropic pattern) is mandatory

## Licensing

EU source data is public domain under Commission Decision 2011/833/EU.
This repo is Lawgic-internal; not yet licensed for external use.
