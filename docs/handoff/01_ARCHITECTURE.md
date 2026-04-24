# Architecture

## High-level shape

```
┌────────────────────────────────────────────────────────────────┐
│                 Lawgic_EULaw_Retrieve (Electron)               │
│  Three ingestion panels: EU Laws / EU Court Decisions /        │
│  EU Amendments. Each with its own Run / Stop / Status.         │
│  Settings panel stores creds in OS userData.                   │
└───────────────────────────────┬────────────────────────────────┘
                                │
                  ┌─────────────┴──────────────┐
                  │                            │
        ┌─────────▼────────┐        ┌──────────▼─────────┐
        │  Python pipeline │        │  Status collection │
        │   Stage 1 fetch  │        │   (read at session │
        │   Stage 2 LLM    │        │    start → derive  │
        │   Stage 3 embed  │        │    Atom watermark) │
        └─────────┬────────┘        └────────────────────┘
                  │
   ┌──────────────┼───────────────┐
   │              │               │
┌──▼────┐   ┌─────▼──────┐  ┌─────▼─────┐
│CELLAR │   │ DashScope  │  │ Voyage AI │
│SPARQL │   │ Qwen 3.5F  │  │ voyage-   │
│+ Atom │   │ Qwen 3.6P  │  │ context-3 │
│ feed  │   │ (+Gemini   │  │           │
│       │   │  fallback) │  │           │
└───────┘   └────────────┘  └─────┬─────┘
                                  │
                  ┌───────────────▼────────────────┐
                  │         Weaviate               │
                  │  User-configured cluster       │
                  │    • EULaws                    │
                  │    • EUCourtDecisions          │
                  │    • EUAmendments              │
                  │    • EULawIngestionStatus      │
                  └────────────────────────────────┘
```

## Weaviate collections (all in the user-configured cluster — no Postgres)

| Collection | Has vectors? | Purpose | Row count at full scope |
|---|---|---|---|
| `EULaws` | Yes — named vectors per language | Regulations, directives, decisions (chunks) | ~450k chunks (Tier A MVP) |
| `EUCourtDecisions` | Yes — named vectors per language | CJ + GC + AG opinions (chunks, two-level) | ~150k chunks (Tier A MVP) |
| `EUAmendments` | Yes — named vectors per language | Atomic amendments: one row per "Article X of CELEX A replaced/deleted/added by CELEX B" change | ~50k–200k rows |
| `EULawIngestionStatus` | No | Per-document processing state — single source of truth for what's been ingested | ~35k rows |

**Postgres is no longer part of the stack.** An earlier draft had a `eu_law_edges` table for the knowledge graph; per the 2026-04 decision ("better to have everything in a single place"), amendments now live in the `EUAmendments` Weaviate collection with both structured fields and named vectors. Graph walks become app-layer filter queries on `target_celex`; typical depth ≤ 3, fast enough.

Full schemas in `03_SCHEMAS.md`.

## Why separate collections for laws vs case law

Four reasons, all locked:

1. **Lawgic's existing Greek setup already does this.** Greek laws and court decisions are separate Weaviate collections with dedicated retrievers (`weaviate_court_retriever.tsx` includes `retrieveContraDecisions` logic that assumes a case-law-only collection). Mirroring the pattern means near-zero retriever code changes for EU.
2. **Schema mismatch is too large.** Case law fields: `ecli`, `court_level`, `parties`, `holding`, `legal_principle`, `procedure_type`, `regulations_interpreted`, `interpretation_strength`. Legislation fields: `document_subtype` (REG/DIR/DEC), `date_in_force`, `obligations`, `consolidated_from`, `in_force`. Mixing them means ~15 always-null fields per document.
3. **Chunking strategies are fundamentally different.** Legislation = one article per chunk. Case law = two-level (1 holding chunk per judgment that weights `case_summary + legal_principle + holding`, plus N reasoning-paragraph-group chunks). Different embedding inputs = different vector spaces.
4. **Volume skew would drown retrieval.** EUR-Lex has ~45k+ legislation docs vs ~100k+ case law docs. Mixing them means a vector search returns mostly case law by sheer volume.

Within `EUCourtDecisions`, CJ + GC + AG opinions are mixed, with `court_level` and `document_subtype` as filter fields. They share one schema and benefit from being in one vector space.

## Why state tracking lives in Weaviate, not on disk

The shipping app uses `data/eu/fetch_manifest.json` on local disk. This ties state to one machine. If the user runs the Electron app from Laptop A today and Laptop B next week, Laptop B has no way to know what's already been embedded — it would either re-ingest everything or miss gaps.

**Fix:** the `EULawIngestionStatus` Weaviate collection IS the state. Any machine with Weaviate credentials queries it at session start and picks up exactly where the previous run stopped. No disk file, no sync problem, no corruption risk.

The watermark for "next incremental run, fetch docs newer than X" is **derived** from this collection on demand:
```sql
SELECT MIN(cellar_recorded_at) 
FROM EULawIngestionStatus 
WHERE status != 'embedded' OR status IS NULL
```
No separate watermark collection — eliminates the race condition where watermark drifts out of sync with actual state.

## Why amendments are in Weaviate (not Postgres) — revised 2026-04

An earlier draft put the knowledge graph in Postgres (`eu_law_edges` table). Per user call "better to have everything in a single place", we moved to a Weaviate collection (`EUAmendments`) that stores both the structural edge AND the actual amendment TEXT, with semantic vectors per language.

Trade-offs accepted:
- **Graph walks become application-layer filter queries** on `target_celex`. For depth ≤ 3 (the common case in legal queries), this is fast enough.
- **Win:** amendments are now semantically searchable ("find amendments changing how consent is defined"), not just structurally queryable.
- **Win:** one credential set, one API, one backup story. No Postgres infrastructure burden.
- **Win:** the retriever stack (Lawgic's Weaviate-first layer) queries amendments with the same client as laws + cases.

## Repo structure target

```
Lawgic_EULaw_Retrieve/
├── electron/                      # Electron shell — copy from geneseas
│   ├── main.js                    # Main process, IPC handlers
│   ├── preload.js                 # Secure IPC bridge
│   └── renderer/
│       └── index.html             # UI: language selector, status panel, settings
├── config/
│   ├── priority_domains.json     # EuroVoc concept lists for MVP scope
│   ├── controlled_vocab.json     # legal_domain + topic_tags vocabularies
│   └── languages.json             # Supported languages + rollout order
├── python/
│   ├── pipeline.py                # Thin dispatcher only
│   ├── eu/
│   │   ├── __init__.py
│   │   ├── fetcher.py             # SPARQL + Atom feed + XHTML download
│   │   ├── parser.py              # XHTML → chunks (article / two-level)
│   │   ├── extractor.py           # LLM metadata extraction with model router
│   │   ├── amendment_extractor.py # CELLAR SPARQL + LLM → upsert to EUAmendments Weaviate
│   │   ├── language_adder.py      # "Add language" flow — Voyage embed only
│   │   └── model_router.py        # Task → model mapping
│   ├── shared/
│   │   ├── embedder.py            # Voyage + Weaviate upsert (named vectors)
│   │   ├── status.py              # Read/write EULawIngestionStatus
│   │   ├── cdm_ontology.py        # Parse CDM OWL file → authoritative predicates
│   │   ├── weaviate_config.py     # Shared HNSW / BM25 / stopwords / sharding config
│   │   └── utils.py               # Logging, emit, config loading
│   ├── create_eulaws_collection.py        # Weaviate schema: EULaws
│   ├── create_eucourt_collection.py       # Weaviate schema: EUCourtDecisions
│   ├── create_euamendments_collection.py  # Weaviate schema: EUAmendments
│   ├── create_eustatus_collection.py      # Weaviate schema: EULawIngestionStatus
│   └── requirements.txt
├── scripts/
│   ├── eval_extraction.py         # 20-doc eval across 3 models
│   ├── estimate_cost.py           # Token + cost estimator given CELEX list
│   ├── verify_qwen_cache.py       # Alibaba caching verification
│   └── parse_cdm_ontology.py      # rdflib script to extract predicates
├── docs/
│   └── handoff/                   # Copy these 11 files here
└── package.json
```

## What we're NOT copying from the shipping app

- US-specific fetchers (`python/us/`) — delete
- UK/AU fetchers (`python/uk/`, `python/au/`) — delete
- CFR titles config — delete
- Maritime-specific metadata fields (vessel_types, port_names, sea_areas, crew_rank, imo_convention_reference, etc.) — delete
- `ShippingAmendment` collection name — replaced by `EUAmendments` Weaviate collection (no Postgres)
- Maritime EuroVoc concept filters (4830, 5889, 2524, 2455) — replace with priority legal-domain concepts

## What we ARE copying verbatim

- Electron shell architecture (main.js, preload.js, renderer pattern)
- 3-stage pipeline concept (fetch / extract / embed)
- Qwen DashScope integration (see `05_MODEL_STACK.md` for exact bytes)
- Region dispatcher idea, narrowed to "language dispatcher"
- Voyage + Weaviate upsert code (region-agnostic, just moves to `shared/embedder.py`)
- Settings panel pattern (API key inputs, base URL, model override)
- Rate limiting pattern (`LLM_CONCURRENCY` env var, default 3 QPS)
