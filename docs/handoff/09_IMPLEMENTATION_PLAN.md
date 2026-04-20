# Implementation Plan

Five phases, sequenced to get a working end-to-end pipeline as fast as possible, then harden.

## Phase 1 — Repo scaffold + infrastructure (2-3 days)

**Goal:** empty but working repo structure, all config files in place, nothing in Weaviate yet.

Tasks:
1. Clone `panos1973/geneseas_localrules_embed` as the template for `panos1973/Lawgic_EULaw_Retrieve`.
2. Delete: `python/us/`, `python/uk/`, `python/au/`, `config/us/`, `config/uk/`, `config/au/`, CFR titles config, maritime collection creator scripts.
3. Keep: `electron/`, `python/shared/`, `python/eu/` (as skeleton), `python/pipeline.py` (thin dispatcher).
4. Create `config/regions.json` → reduce to single region "EU", but add `config/languages.json` for per-language routing.
5. Create `config/priority_domains.json` with the EuroVoc concept list from `02_DATA_SOURCES.md`.
6. Create `config/controlled_vocab.json` from `07_RETRIEVAL.md`.
7. Write `scripts/parse_cdm_ontology.py` using `rdflib` — parses CDM OWL, emits `config/cdm_predicates.json`. Run it once, commit the output. Verify against `eurlex` R package's list.
8. Copy shipping app's Qwen branch from `pipeline.py:714-748` verbatim into `python/eu/extractor.py`. Add task-aware `enable_thinking` parameter.
9. Write `python/eu/model_router.py` with the task → model dict from `05_MODEL_STACK.md`.
10. Write Postgres migration `python/migrations/001_eu_law_edges.sql` from `03_SCHEMAS.md`.
11. Write Weaviate collection creators:
    - `python/create_eulaws_collection.py`
    - `python/create_eucourt_collection.py`
    - `python/create_eustatus_collection.py`
12. Run collection creators in dev/staging Weaviate to verify schemas.
13. Run Postgres migration.

**Exit criteria:** empty collections created, schemas validated, priority_domains + controlled_vocab committed, CDM predicates parsed.

## Phase 2 — First batch of English legislation (3-5 days)

**Goal:** ingest ~500 in-force legislation docs from one domain (say, `data_protection`) end-to-end. Prove the pipeline works before scaling.

Tasks:
1. Write `python/eu/fetcher.py`:
   - SPARQL query for one EuroVoc domain, LIMIT 500
   - XHTML download with retry/backoff
   - Persists raw XHTML to `data/eu/xhtml/{celex}.xhtml`
2. Write `python/eu/parser.py`:
   - XHTML → article-level chunks with BeautifulSoup
   - Generate `contextual_prefix` template fill per chunk
   - Output chunks JSONL to `data/eu/chunks/{celex}.jsonl`
3. Write `python/eu/extractor.py` (Stage 2):
   - Per-doc loop: first chunk gets `document_summary` + `chunk_summary` + all metadata; subsequent chunks reuse doc_summary, get own `chunk_summary` + metadata
   - Model router picks Qwen3.5 Flash by default, Qwen3.6 Plus for case-law holdings
   - JSON validator + CELEX hallucination check + Gemini fallback queue
   - Log `cached_tokens` on every call → verify caching works empirically
   - Output enriched chunks JSONL
4. Write `python/shared/embedder.py` (Stage 3):
   - Voyage `voyage-context-3` batch embedding
   - Weaviate upsert with named vector `vector_en`
   - Deterministic UUID: `uuid5(celex + "::" + chunk_id)`
5. Write `python/shared/status.py`:
   - Read/write `EULawIngestionStatus` rows
   - Helpers: `mark_fetched`, `mark_enriched`, `mark_embedded`, `mark_failed`, `watermark_min_pending`
6. Run end-to-end: `pipeline.py fetch --eurovoc-domain data_protection --limit 500 && pipeline.py extract && pipeline.py embed`.

**Exit criteria:** 500 English chunks in `EULaws`, cache hit rate >60%, JSON validity >98%, integrity checks pass, hybrid retrieval returns sensible results on 10 test queries.

## Phase 3 — Knowledge graph + amendments (2-3 days)

**Goal:** populate `eu_law_edges` with CELLAR-sourced + LLM-extracted edges for the Phase 2 corpus.

Tasks:
1. Write `python/eu/amendment_extractor.py`:
   - Pass 1: SPARQL query for all amendment/repeal/interpretation edges involving the embedded CELEX set. Upsert to `eu_law_edges` with `confidence=1.0`, `data_source='cellar_sparql'`.
   - Pass 2: LLM extraction during Stage 2 already produces `cross_references` with article-level precision. Upsert those as `confidence=0.9`, `data_source='llm_extraction'`.
   - Test recursive CTE queries from `03_SCHEMAS.md` work against populated data.
2. Add repeal detection to incremental flow: separate SPARQL query checking if any embedded CELEX was repealed.

**Exit criteria:** ~2000 edges in Postgres, graph walk queries complete in <100ms, amendment chains for a sample CELEX look correct in manual inspection.

## Phase 4 — Case law pipeline (3-4 days)

**Goal:** ingest CJEU + GC judgments from the same domain.

Tasks:
1. Extend `fetcher.py` with case-law SPARQL query.
2. Extend `parser.py` with two-level chunking (holding + reasoning).
3. Extend `extractor.py` with Prompt B for case law (Qwen3.6 Plus for holdings).
4. Add case-law-specific fields to `EUCourtDecisions` upsert logic.
5. Populate `authority_weight` based on court_level + document_subtype.

**Exit criteria:** ~200 case law docs in `EUCourtDecisions`, holdings + legal_principle manually spot-checked and plausible, cross-links to `EULaws` via `regulations_interpreted` present and queryable.

## Phase 5 — Greek language + Electron UI (3-4 days)

**Goal:** add Greek as second language, Electron UI operational.

Tasks:
1. Write `python/eu/language_adder.py` per `04_LANGUAGE_STRATEGY.md`.
2. Run language_adder for Greek on the Phase 2-4 corpus.
3. Update `electron/main.js` with new IPC handlers per `08_ELECTRON_APP.md`.
4. Update `electron/renderer/index.html` with language selector, status panel, domain breakdown, activity feed.
5. Wire Settings panel for DashScope + Google AI Studio + Voyage keys.
6. Test "add language" flow end-to-end from Electron UI.

**Exit criteria:** Greek vectors present on all Phase 2-4 chunks, Electron app shows live status from Weaviate, incremental update button works.

## Phase 6 — Scale to Tier A MVP (2-3 days)

Run full Tier A ingestion across all priority domains:
- ~10k legislation docs
- ~25k case law docs
- English + Greek languages
- Full knowledge graph populated

Budget: ~$300 (see `06_COSTS.md`).  
Wall-clock: ~24-36 hours of elapsed pipeline time (respecting rate limits).

## Phase 7 — Lawgic integration (1-2 days)

Modify `lawgic_corp/src/lib/retrievers/weaviate_law_retriever.tsx` and related files:
- Add `target_vector` parameter for language routing.
- Swap collection name from Greek-only to `EULaws` / `EUCourtDecisions`.
- Verify Lawbot + Case Study + Contract Analysis all return sensible EU-law results on test queries.

**Exit criteria:** 10 Greek-language queries to Lawbot return relevant EU regulations + Greek laws together, cited correctly.

## Phase 8 — Evaluation + hardening (ongoing)

- 20-doc extraction eval harness (see `10_OPEN_QUESTIONS.md`)
- 100-query retrieval eval per language
- Monitoring dashboards (cost, cache hit rate, error rate)
- Document the entire pipeline for operations runbook

## Total timeline estimate

~3 weeks of focused development, 1 developer. Phases 1-5 are sequential and unavoidable. Phases 6-8 can overlap.

## Milestones to show stakeholders

- End of week 1: Phase 1-2 done, 500 docs embedded in one domain, queryable
- End of week 2: Phase 3-5 done, knowledge graph live, Greek language added, Electron UI functional
- End of week 3: Phase 6-7 done, Tier A complete, Lawgic serves EU queries in production

## What NOT to do in MVP

- Don't implement fancy features like semantic deduplication, cross-encoder rerank, HyDE. Defer to Phase 9+.
- Don't try to ingest Tier B or C scope. MVP = Tier A only.
- Don't add more than English + Greek languages on day one. German waits until Lawgic's German market actually launches.
- Don't build custom knowledge graph visualization — GraphML export is enough for internal use.
- Don't write a web admin panel. Electron is sufficient for the one-operator-one-machine reality of this workload.
