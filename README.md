# Lawgic_EULaw_Retrieve Handoff — Read This First

> **For a new Claude Code session:** this folder contains the complete decision record from the planning conversation that preceded implementation. Read everything before touching code. Nothing here is provisional — all architectural choices are locked.

## How to use these docs in a new Claude Code session

1. **Grant the new session access to `panos1973/Lawgic_EULaw_Retrieve`** in your harness config.
2. **In the very first message to the new Claude Code**, paste this:

> I'm continuing a project to build `Lawgic_EULaw_Retrieve`. The complete planning and architecture has been written up as a handoff document in `panos1973/lawgic_corp` on branch `claude/embed-shipping-regulations-tsB0y`, folder `docs/lawgic_eulaw_handoff/`. Please read all 11 files in that folder in numerical order (00 through 10), then confirm your understanding before writing any code. After confirming, start with Phase 1 Task 1 from `09_IMPLEMENTATION_PLAN.md`.

3. Claude will read the docs and resume exactly where this conversation left off. No context lost.

## File index

| # | File | Purpose |
|---|---|---|
| 00 | `00_OVERVIEW.md` | Project context, source/target repos, locked decisions |
| 01 | `01_ARCHITECTURE.md` | High-level shape, collection responsibilities, why Postgres for graph |
| 02 | `02_DATA_SOURCES.md` | CELLAR SPARQL, Atom feed, CDM ontology warnings, priority domains |
| 03 | `03_SCHEMAS.md` | Full schemas: `EULaws`, `EUCourtDecisions`, `EULawIngestionStatus`, `eu_law_edges` |
| 04 | `04_LANGUAGE_STRATEGY.md` | Named vectors per language, per-market rollout economics |
| 05 | `05_MODEL_STACK.md` | Qwen3.5 Flash + Qwen3.6 Plus + Gemini fallback, DashScope integration |
| 06 | `06_COSTS.md` | Tier A/B/C estimates, per-language costs, query-time costs |
| 07 | `07_RETRIEVAL.md` | Contextual retrieval, summaries, controlled vocab, chunking strategies |
| 08 | `08_ELECTRON_APP.md` | UI layout, IPC handlers, add-language flow, incremental flow |
| 09 | `09_IMPLEMENTATION_PLAN.md` | 7 phases, 3-week timeline, milestones |
| 10 | `10_OPEN_QUESTIONS.md` | Things requiring empirical validation, decision rules, launch checklist |

## Locked decisions (never re-litigate)

These were debated and decided. Do not re-open unless a genuine blocker appears:

1. Separate repo `Lawgic_EULaw_Retrieve`, not a fork-in-place
2. Collections separated by document type (`EULaws` vs `EUCourtDecisions`), not by language
3. Named vectors per language within collections (Weaviate 1.24+)
4. English-only LLM metadata, shared across languages
5. Postgres for knowledge graph, not Weaviate
6. Ingestion state in Weaviate collection, not on disk
7. Model stack: Qwen3.5 Flash + Qwen3.6 Plus + Gemini fallback — no Claude
8. Alibaba DashScope OpenAI-compat endpoint, Singapore
9. Contextual retrieval prefix (Anthropic pattern) is mandatory, not optional
10. Tier A MVP scope: priority EuroVoc domains only, ~10k laws + 25k cases

## Things to validate empirically (deferred from planning)

See `10_OPEN_QUESTIONS.md` for the full list. Key ones:
- DashScope caching on Singapore for Qwen3.5/3.6 (validate on first batch)
- Qwen3.6 Plus quality on case law holdings (20-doc eval)
- Cross-lingual retrieval quality (100-query eval per language)
- CDM predicate names (parse live ontology, don't trust planning doc verbatim)

## Source repos you'll need to read/reference

- **`panos1973/geneseas_localrules_embed`** — copy Electron shell, Qwen integration, 3-stage pipeline. Specifically reuse `python/pipeline.py:714-748` for DashScope calls.
- **`panos1973/lawgic_corp`** — this repo. Contains Lawgic's existing retrievers (`src/lib/retrievers/`) that will consume the new EU collections with minimal changes.

## First concrete actions for the new session

After reading the 11 docs:

1. Run `scripts/parse_cdm_ontology.py` (to write) — get authoritative CDM predicate list
2. Scaffold `Lawgic_EULaw_Retrieve` repo structure per `09_IMPLEMENTATION_PLAN.md` Phase 1
3. Create Weaviate collections on `lawgicfeb26` cluster using `python/create_*_collection.py` scripts
4. Run Postgres migration `001_eu_law_edges.sql`
5. Ingest ~500 data_protection docs end-to-end to prove the pipeline
6. Verify caching works (log `cached_tokens` from DashScope response)
7. Expand to full Tier A scope only after Phase 2 success

## One last thing

**Don't forget to rotate the DashScope API key** that was pasted in the original planning chat (`sk-c97de837...`). Log into the DashScope console, delete it, create a fresh one for production use.

Good luck. Everything you need to resume is in these 11 files.
