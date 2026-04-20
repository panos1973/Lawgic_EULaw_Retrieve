# Architecture

## High-level shape

```
┌────────────────────────────────────────────────────────────────┐
│                 Lawgic_EULaw_Retrieve (Electron)               │
│  UI: language selector, status panel, "add language",          │
│      "incremental update", settings (API keys)                 │
└───────────────────────────────┬────────────────────────────────┘
                                │
                  ┌─────────────┴──────────────┐
                  │                            │
        ┌─────────▼────────┐        ┌──────────▼─────────┐
        │  Python pipeline │        │  Status + watermark│
        │   Stage 1 fetch  │        │   (read from       │
        │   Stage 2 LLM    │        │    Weaviate at     │
        │   Stage 3 embed  │        │    session start)  │
        └─────────┬────────┘        └────────────────────┘
                  │
   ┌──────────────┼───────────────┬────────────────┐
   │              │               │                │
┌──▼────┐   ┌─────▼──────┐  ┌─────▼─────┐   ┌──────▼──────┐
│CELLAR │   │ DashScope  │  │ Voyage AI │   │ Postgres    │
│SPARQL │   │ Qwen 3.5F  │  │ voyage-   │   │ pgvector    │
│+ Atom │   │ Qwen 3.6P  │  │ context-3 │   │ + edges     │
│ feed  │   │ (+Gemini   │  │           │   │ table       │
│       │   │  fallback) │  │           │   │             │
└───────┘   └────────────┘  └─────┬─────┘   └─────────────┘
                                  │
                          ┌───────▼────────┐
                          │    Weaviate    │
                          │  lawgicfeb26   │
                          │  cluster:      │
                          │  • EULaws      │
                          │  • EUCourt     │
                          │  • EULawInges  │
                          │    tionStatus  │
                          └────────────────┘
```

## Weaviate collections (all on lawgicfeb26 cluster)

| Collection | Has vectors? | Purpose | Row count at full scope |
|---|---|---|---|
| `EULaws` | Yes — named vectors per language | Regulations, directives, decisions (chunks) | ~450k chunks (Tier A MVP) |
| `EUCourtDecisions` | Yes — named vectors per language | CJ + GC + AG opinions (chunks, two-level) | ~150k chunks (Tier A MVP) |
| `EULawIngestionStatus` | No | Per-document processing state — the single source of truth for "what has been ingested" | ~35k rows |

## Postgres tables (same DB as Lawgic's existing pgvector)

| Table | Purpose |
|---|---|
| `eu_law_edges` | Knowledge graph: amendments, repeals, citations, interpretations. Sourced from CELLAR SPARQL (confidence=1.0) + LLM article-level extraction (confidence=0.85-0.95). |
| `eu_law_edges_effective_dates` (optional) | Per-edge effective-date annotations if we decide to store separately rather than inline. |

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

## Why Postgres for the knowledge graph, not Weaviate

1. Graph walks are recursive by nature. "Find all laws that amend X, plus all laws those amend, up to depth 5" is three lines of recursive CTE in Postgres. In Weaviate, it's an application-layer loop issuing N queries — slow and fragile.
2. Graph edges don't need vector similarity. A relation row has no text to embed. Storing them in Weaviate wastes HNSW index capacity.
3. Edge cardinality is high. ~50k EU acts × avg 4 edges × article-level expansion = 500k–1M edges. Postgres handles this trivially; Weaviate's sweet spot is vector objects.
4. Lawgic already runs Postgres (Drizzle ORM, pgvector for uploaded files). No new infrastructure.

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
│   │   ├── amendment_extractor.py # CELLAR SPARQL + LLM article-level edges
│   │   ├── language_adder.py      # "Add language" flow — Voyage embed only
│   │   └── model_router.py        # Task → model mapping
│   ├── shared/
│   │   ├── embedder.py            # Voyage + Weaviate upsert (named vectors)
│   │   ├── status.py              # Read/write EULawIngestionStatus
│   │   ├── cdm_ontology.py        # Parse CDM OWL file → authoritative predicates
│   │   └── utils.py               # Logging, emit, config loading
│   ├── create_eulaws_collection.py        # Weaviate schema: EULaws
│   ├── create_eucourt_collection.py       # Weaviate schema: EUCourtDecisions
│   ├── create_eustatus_collection.py      # Weaviate schema: EULawIngestionStatus
│   ├── migrations/
│   │   └── 001_eu_law_edges.sql  # Postgres knowledge graph table
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
- `ShippingAmendment` collection name — rename to `EULawAmendments` (in Postgres, not Weaviate)
- Maritime EuroVoc concept filters (4830, 5889, 2524, 2455) — replace with priority legal-domain concepts

## What we ARE copying verbatim

- Electron shell architecture (main.js, preload.js, renderer pattern)
- 3-stage pipeline concept (fetch / extract / embed)
- Qwen DashScope integration (see `05_MODEL_STACK.md` for exact bytes)
- Region dispatcher idea, narrowed to "language dispatcher"
- Voyage + Weaviate upsert code (region-agnostic, just moves to `shared/embedder.py`)
- Settings panel pattern (API key inputs, base URL, model override)
- Rate limiting pattern (`LLM_CONCURRENCY` env var, default 3 QPS)
