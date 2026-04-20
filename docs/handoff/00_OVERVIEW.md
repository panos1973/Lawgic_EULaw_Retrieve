# Lawgic_EULaw_Retrieve — Handoff Overview

> **Purpose of this folder:** comprehensive handoff from the planning conversation with Claude Code. If you are a new Claude Code session spawned to continue this work, read all files in this folder in numerical order before touching any code. Every architectural decision has already been made and is documented here — you are NOT starting from scratch.

## The project in one paragraph

Build a new standalone product called **`Lawgic_EULaw_Retrieve`** — an Electron desktop app + Python pipeline that fetches, enriches, embeds, and tracks European Union legislation and case law for use by the existing **Lawgic** legal AI platform (lawgic.gr, panos1973/lawgic_corp). The app is modeled directly on the existing shipping regulations fetcher at `panos1973/geneseas_localrules_embed`, stripped of shipping-specific concerns and generalized to cover all EU legal domains (data protection, employment, competition, tax, IP, environmental, consumer, company law, criminal, etc.). Output flows into Weaviate collections consumed by Lawgic's existing retrieval stack.

## The two source repos to understand

| Repo | Role | What to copy / reuse |
|---|---|---|
| `panos1973/geneseas_localrules_embed` | Electron app architecture template | The complete 3-stage pipeline (fetch / extract / embed), region dispatcher pattern, Qwen DashScope integration, EU SPARQL fetcher stub in `python/eu/`, settings panel UI. |
| `panos1973/lawgic_corp` | Target consumer of the embeddings | Weaviate cluster name (`lawgicfeb26`), retriever patterns (hybrid BM25+vector with adaptive alpha, amendment-chain XML tags, VoyageAI rerank). New EU collections go into the same cluster. |

## The target repo

`panos1973/Lawgic_EULaw_Retrieve` — should exist on GitHub as a public repo, but may be empty. Development branch: `claude/embed-shipping-regulations-tsB0y` (will be created from `main` on first push).

## Decisions that are LOCKED (do not re-litigate)

1. **Separate repo, not a fork-in-place.** Clean Lawgic-brand product, no shipping references. See `01_ARCHITECTURE.md`.
2. **Weaviate collections are separated by document type, not by language.** `EULaws` and `EUCourtDecisions` are two distinct collections; both use named vectors per language. See `04_LANGUAGE_STRATEGY.md`.
3. **Postgres stores the knowledge graph, not Weaviate.** See `01_ARCHITECTURE.md` and `03_SCHEMAS.md`.
4. **English is the primary metadata language.** Chunk text is stored in multiple languages; LLM-extracted metadata is English-only and shared across languages. See `04_LANGUAGE_STRATEGY.md`.
5. **Model stack: Qwen3.5 Flash (default) + Qwen3.6 Plus (case law holdings + reasoning tasks) + Gemini 2.5 Flash batch+cache (fallback only). No Claude.** See `05_MODEL_STACK.md`.
6. **Alibaba DashScope OpenAI-compat endpoint for Qwen**, same integration pattern as the shipping app. See `05_MODEL_STACK.md`.
7. **Ingestion state lives in Weaviate, not on disk.** Computer-agnostic, resumable from any machine. See `03_SCHEMAS.md`.
8. **Contextual retrieval (Anthropic pattern) is a requirement**, not optional. ~50-token context prefix prepended before embedding. See `07_RETRIEVAL.md`.

## Decisions that need empirical validation

See `10_OPEN_QUESTIONS.md` for the full list. Headlines:
- Alibaba DashScope caching on Singapore endpoint for `qwen3.5-flash` and `qwen3.6-plus` — we skipped the test, will validate on first real batch.
- Cross-lingual retrieval quality via multilingual embeddings — 100-query eval per language.
- Qwen3.6 Plus quality on case-law holdings vs Sonnet 4.5 — 20-doc eval.
- CDM ontology predicate list — must be parsed programmatically (not trusted from memory).

## What "done" looks like for Tier A MVP

- `EULaws` collection populated with ~10,000 in-force EU legislation docs across priority EuroVoc domains
- `EUCourtDecisions` collection populated with ~25,000 recent CJEU + General Court decisions
- `EULawAmendments` Postgres table populated from CELLAR SPARQL + LLM article-level extraction
- `EULawIngestionStatus` Weaviate collection tracking every document's state
- Electron app with language selector, incremental update button, per-language status panel
- English language complete; Greek vectors as secondary named vector per chunk
- Lawgic's existing Lawbot / Case Study retrievers successfully querying the new collections (may need one-line collection name config changes, no retriever rewrites)

Expected total cost one-time English ingestion: **~$200**. Per additional language: **~$100**.

## Reading order for a new Claude Code session

1. `00_OVERVIEW.md` (this file)
2. `01_ARCHITECTURE.md`
3. `02_DATA_SOURCES.md`
4. `03_SCHEMAS.md`
5. `04_LANGUAGE_STRATEGY.md`
6. `05_MODEL_STACK.md`
7. `06_COSTS.md`
8. `07_RETRIEVAL.md`
9. `08_ELECTRON_APP.md`
10. `09_IMPLEMENTATION_PLAN.md`
11. `10_OPEN_QUESTIONS.md`

After reading: start with `09_IMPLEMENTATION_PLAN.md` Phase 1 actions.
