# Schemas

**Four Weaviate collections.** Postgres knowledge graph dropped (per user decision, 2026-04 — "better to have everything in a single place"). All amendments now live in a Weaviate collection with vectors + text, queryable semantically and structurally.

All schemas locked — do not add or remove fields without reason.

**Infrastructure (same for all 4 collections):**
- HNSW + 8-bit Rotational Quantization (`rescore_limit=200`), DOT distance
- Named vectors per language: `vector_en`, `vector_el`, `vector_de`, `vector_fr`, `vector_it` (EULaws / EUCourtDecisions / EUAmendments only; EULawIngestionStatus has no vectors)
- Voyage `voyage-context-3`, 1024 dimensions
- BM25: `b=0.3`, `k1=1.5` (long legal text tuning)
- Stopwords: English preset + English legal-function words + 102 Greek function words
- Sharding: `virtual_per_physical=128, desired_count=1`, replication factor 1
- See `python/shared/weaviate_config.py` for the exact shared config block.
- Per-property `Tokenization` + `index_filterable/searchable/range_filters` flags chosen per field — see the collection creator scripts for authoritative values.

## 1. `EULaws` Weaviate collection

**Purpose:** EU regulations, directives, decisions, consolidated texts. One row per chunk (typically one article per chunk, or article paragraph-group for very long articles).

**Vectorization:** Named vectors per language. `vector_en` required; `vector_el`, `vector_de`, etc. added progressively per market launch.

**Weaviate config:**
- Collection name: `EULaws`
- Vectorizer: `none` (we provide embeddings via Voyage)
- Named vectors: `vector_en`, `vector_el`, `vector_de`, `vector_fr`, `vector_it` (each: HNSW + 8-bit RQ quantization, DOT_PRODUCT distance)
- Embedding model: Voyage `voyage-context-3`, 1024 dimensions
- Deterministic UUID: `uuid5(celex + "::" + chunk_id)` where `chunk_id` = `art_{N}` or `recital_{N_group}` or `annex_{N}`

### Core identification fields

| # | Field | Type | Source | Notes |
|---|---|---|---|---|
| 1 | `celex` | TEXT | CELLAR | Primary identifier |
| 2 | `eli_uri` | TEXT | CELLAR | European Legislation Identifier |
| 3 | `chunk_id` | TEXT | Parser | `art_17`, `recital_1_5`, `annex_II` |
| 4 | `chunk_index` | INT | Parser | Position within document for ordering |
| 5 | `content_hash` | TEXT | Computed | SHA-256 of text for dedup/change detection |

### Text content (all languages)

| # | Field | Type | Source | Notes |
|---|---|---|---|---|
| 6 | `text_en` | TEXT | CELLAR | Primary — always present |
| 7 | `text_el` | TEXT | CELLAR | Greek — present if available |
| 8 | `text_de` | TEXT | CELLAR | German — added when DE launched |
| 9 | `text_fr` | TEXT | CELLAR | French — added when FR launched |
| 10 | `text_it` | TEXT | CELLAR | Italian — added when IT launched |

### Summaries (English only, LLM-generated)

| # | Field | Type | Source | Notes |
|---|---|---|---|---|
| 11 | `document_summary` | TEXT | LLM (Qwen3.5F) | 3-5 sentences, same value across all chunks of one doc |
| 12 | `chunk_summary` | TEXT | LLM (Qwen3.5F) | **1-2 sentences MAX per chunk** |
| 13 | `contextual_prefix` | TEXT | Parser + LLM | ~50-token scene-setter prepended to chunk text at embedding time. See `07_RETRIEVAL.md`. |

### Document-level metadata (language-independent)

| # | Field | Type | Source | Notes |
|---|---|---|---|---|
| 14 | `document_subtype` | TEXT | CELLAR | `regulation`, `directive`, `decision`, `implementing_regulation`, `delegated_regulation`, `consolidated` |
| 15 | `document_date` | DATE | CELLAR | `cdm:work_date_document` |
| 16 | `date_in_force` | DATE | CELLAR | When it entered into force |
| 17 | `in_force` | BOOL | CELLAR | Currently in force |
| 18 | `superseded_by` | TEXT | Computed | CELEX of repealing act, null if not repealed |
| 19 | `source_citation` | TEXT | CELLAR | Official Journal reference |
| 20 | `eurovoc_concepts` | TEXT_ARRAY | CELLAR | Concept labels |
| 21 | `eurovoc_ids` | TEXT_ARRAY | CELLAR | Concept IDs |

### LLM-extracted metadata (English, controlled vocabulary)

All of these are Gemini-enrichment targets — must use the controlled vocabulary in `config/controlled_vocab.json`.

| # | Field | Type | Source | Notes |
|---|---|---|---|---|
| 22 | `legal_domain` | TEXT | LLM | One of: `data_protection`, `employment`, `competition`, `tax`, `IP`, `environmental`, `consumer`, `company`, `financial`, `commercial`, `criminal`, `asylum` |
| 23 | `topic_tags` | TEXT_ARRAY | LLM | 3-8 per chunk from controlled vocab |
| 24 | `obligations` | OBJECT_ARRAY | LLM | `{actor, action, deadline, condition}` |
| 25 | `applies_to` | TEXT_ARRAY | LLM | Controlled: `controller`, `processor`, `employer`, `importer`, `consumer`, `public-authority`, `SME`, etc. |
| 26 | `definitions` | OBJECT | LLM | `{term: definition}` map |
| 27 | `cross_references` | TEXT_ARRAY | LLM + CELLAR | CELEX numbers cited by this chunk (ARTICLE-LEVEL, not just doc-level) |
| 28 | `penalty_type` | TEXT_ARRAY | LLM | `administrative-fine`, `criminal-sanction`, etc. |
| 29 | `effective_dates` | DATE_ARRAY | LLM | Dates mentioned in chunk as effectiveness markers |
| 30 | `international_conventions` | TEXT_ARRAY | LLM | For edge cases linking to non-EU instruments |

### Ingestion bookkeeping

| # | Field | Type | Source | Notes |
|---|---|---|---|---|
| 31 | `language_list` | TEXT_ARRAY | Pipeline | Languages with populated `text_X` and `vector_X`: e.g., `["en", "el"]` |
| 32 | `fetched_at` | DATE | Pipeline | When this chunk was last fetched |
| 33 | `extracted_at` | DATE | Pipeline | When LLM metadata was last refreshed |
| 34 | `word_count` | INT | Computed | English text word count |
| 35 | `char_count` | INT | Computed | English text char count |

**Total: 35 fields.**

---

## 2. `EUCourtDecisions` Weaviate collection

**Purpose:** CJEU judgments + General Court judgments + AG opinions. Two-level chunking (see `07_RETRIEVAL.md`).

**Shared base fields:** 1-21, 27-29, 31-35 from `EULaws` (same semantics).

**Replaced fields:**
- Drop `document_subtype` values → replace with: `judgment`, `order`, `ag_opinion`.
- Drop `date_in_force` → replace with `date_of_judgment`.
- Drop `in_force` (cases don't expire) → replace with `is_overturned` (bool).
- Drop `superseded_by` → replace with `overturned_by` (celex).

**Case-law-specific fields (in addition to shared):**

| # | Field | Type | Source | Notes |
|---|---|---|---|---|
| 36 | `ecli` | TEXT | CELLAR | `ECLI:EU:C:2009:405` |
| 37 | `court_level` | TEXT | CELLAR | `CJ` (Court of Justice, supreme) or `GC` (General Court) |
| 38 | `procedure_type` | TEXT | CELLAR | `preliminary-reference`, `direct-action`, `appeal`, `infringement`, `opinion` |
| 39 | `parties` | TEXT | CELLAR/LLM | `Commission v Greece`, `Intertanko and Others`, etc. |
| 40 | `language_of_case` | TEXT | CELLAR | ISO 639-1 code of the authentic original version (French is common) |
| 41 | `chunk_type` | TEXT | Parser | `holding` or `reasoning` (two-level chunking) |
| 42 | `case_summary` | TEXT | LLM (Qwen3.5F for ops; **Qwen3.6P for holdings**) | Facts + decision, 3-5 sentences |
| 43 | `legal_principle` | TEXT | **Qwen3.6P (reasoning on)** | The rule of law established — the takeaway in plain English |
| 44 | `holding` | TEXT | **Qwen3.6P (reasoning on)** | The operative part restated clearly |
| 45 | `regulations_interpreted` | OBJECT_ARRAY | **Qwen3.6P** + CELLAR | `{celex, article, strength}` where `strength ∈ {applies, distinguishes, establishes, overrides, clarifies}` |
| 46 | `authority_weight` | TEXT | Computed | `binding` (CJ/GC judgments), `persuasive` (AG opinions, orders in some cases) |
| 47 | `judges` | TEXT_ARRAY | CELLAR | Panel members if available |
| 48 | `advocate_general` | TEXT | CELLAR | For cases with AG opinions |

**Total: ~48 fields (with shared ones).**

**Embedding weighting difference:** holding chunks weight `case_summary + legal_principle + holding + contextual_prefix` in the embedding input. Reasoning chunks weight `chunk_summary + text + contextual_prefix` like legislation.

---

## 3. `EULawIngestionStatus` Weaviate collection

**Purpose:** The single source of truth for "what has been ingested". Enables resumability from any machine. No vectors — metadata-only collection (BM25 default params for any rare text search).

**Uniqueness key:** `uuid5(celex + "::" + language + "::" + collection_kind)` where `collection_kind ∈ {'law', 'case', 'amendment'}`.

| # | Field | Type | Notes |
|---|---|---|---|
| 1 | `celex` | TEXT | |
| 2 | `language` | TEXT | ISO 639-1: `en`, `el`, `de`, `fr`, `it` |
| 3 | `collection_kind` | TEXT | `law` / `case` / `amendment` — which content collection this state row tracks |
| 4 | `document_type` | TEXT | `legislation` or `case_law` |
| 5 | `cellar_recorded_at` | DATE | From Atom feed — monotonic. Used to derive watermark. |
| 6 | `text_hash` | TEXT | SHA-256 of fetched XHTML. Detects re-fetch needed. |
| 7 | `status` | TEXT | Enum: `discovered`, `fetched`, `enriched`, `embedded`, `failed_fetch`, `failed_enrich`, `failed_embed`, `failed_integrity`, `superseded`, `missing_source` |
| 8 | `last_updated_at` | DATE | Touched on every state transition |
| 9 | `superseded_by` | TEXT | Nullable; CELEX of repealing act |
| 10 | `retry_count` | INT | Default 0, max 3 for failed states |
| 11 | `error_message` | TEXT | Nullable; only populated on failed states |

**Total: 11 fields.** Deliberately minimal.

**Derived watermark query (run each incremental run):**
```
cutoff = SELECT MIN(cellar_recorded_at) 
         WHERE status != 'embedded' OR status IS NULL
```
Then query CELLAR Atom feed for events newer than `cutoff`.

**Integrity check (run after Stage 3 per doc):**
```
expected_chunks_from_parse == COUNT(*) FROM EULaws 
                              WHERE celex=X AND language=Y
```
Mismatch → mark `status='failed_integrity'` and alert. Catches silent partial upserts.

---


## 4. `EUAmendments` Weaviate collection

**Purpose:** Atomic amendment instructions. One row per "Article X of CELEX A is replaced/deleted/added/modified/renumbered" change. Replaces the Postgres `eu_law_edges` table from earlier drafts — everything now in Weaviate, per user decision (2026-04).

**Vectorization:** Named vectors per language (same slots as `EULaws`). The embedded text is the natural-language amendment description, e.g.:

> "CELEX 32024R1157 replaces Article 17(3)(c) of CELEX 32016R0679. Previous text: '…'. New text: '…'. Effective from 2024-07-01."

**Uniqueness UUID:** `uuid5(amending_celex + "::" + target_celex + "::" + article_hierarchy + "::" + change_type)`. Re-runs overwrite the same amendment instruction.

### Identity

| # | Field | Type | Source | Notes |
|---|---|---|---|---|
| 1 | `chunk_id` | TEXT | Pipeline | `amend_{target_celex}_{article_hierarchy}` |
| 2 | `chunk_index` | INT | Pipeline | N-th amendment inside the amending act |
| 3 | `content_hash` | TEXT | Computed | SHA-256 of description |
| 4 | `celex` | TEXT | Pipeline | Mirror of `amending_celex`, for retriever compatibility |

### Source (the amending act)

| # | Field | Type | Notes |
|---|---|---|---|
| 5 | `amending_celex` | TEXT | CELEX of the act doing the amending (e.g. `32024R1157`) |
| 6 | `amending_article` | TEXT | Which article within the amending act contains this instruction |
| 7 | `amending_title` | TEXT | Denormalized for display without a Weaviate cross-reference |
| 8 | `amending_document_subtype` | TEXT | regulation / directive / decision / corrigendum / etc. |

### Target (the act being changed)

| # | Field | Type | Notes |
|---|---|---|---|
| 9 | `target_celex` | TEXT | CELEX of the act being modified |
| 10 | `target_article` | TEXT | Top-level article number (e.g. "17") |
| 11 | `article_hierarchy` | TEXT | Precise path inside the article (e.g. "Article 17(3)(c)") |
| 12 | `target_title` | TEXT | Denormalized title of target act |
| 13 | `target_document_subtype` | TEXT | Subtype of the target |
| 14 | `consolidated_celex` | TEXT | Nullable; CELEX of the published consolidated version (if any) |

### Change semantics

| # | Field | Type | Notes |
|---|---|---|---|
| 15 | `change_type` | TEXT | `replace` / `delete` / `add` / `modify` / `renumber` / `consolidate` / `correct` / `implement` |
| 16 | `impact_level` | TEXT | `major` / `minor` / `clarification` / `renumber` — LLM-classified |
| 17 | `repeals_entirely` | BOOL | True when the amendment deletes the target article outright |
| 18 | `effective_date` | DATE | When the amendment takes effect |
| 19 | `amendment_number` | INT | 1-based position among amendments in the same amending act |

### Text per language (embedded via named vectors)

| # | Field | Type | Notes |
|---|---|---|---|
| 20 | `text_en` | TEXT | Full amendment description, English |
| 21 | `text_el` | TEXT | Greek, added when that language is ingested |
| 22 | `text_de` | TEXT | Reserved |
| 23 | `text_fr` | TEXT | Reserved |
| 24 | `text_it` | TEXT | Reserved |

### Raw before/after (English only)

| # | Field | Type | Notes |
|---|---|---|---|
| 25 | `old_text` | TEXT | Nullable (null for `add` change_type) |
| 26 | `new_text` | TEXT | Nullable (null for `delete` change_type) |

### Summaries (REQUIRED on every chunk — same pattern as EULaws)

| # | Field | Type | Notes |
|---|---|---|---|
| 27 | `document_summary` | TEXT | Summary of the whole AMENDING ACT. Same value across all amendments in that act. |
| 28 | `chunk_summary` | TEXT | 1-2 sentence summary of THIS specific amendment. |
| 29 | `contextual_prefix` | TEXT | ~50-token prefix prepended at embed time |

### Inherited metadata

| # | Field | Type | Notes |
|---|---|---|---|
| 30 | `legal_domain` | TEXT | Inherited from target act (GDPR → `data_protection`) |
| 31 | `topic_tags` | TEXT_ARRAY | From controlled vocab |
| 32 | `cross_references` | TEXT_ARRAY | Other CELEX mentioned inside the amendment body |

### Provenance

| # | Field | Type | Notes |
|---|---|---|---|
| 33 | `data_source` | TEXT | `cellar_sparql` (doc-level, conf 1.0) / `llm_extraction` (article-level, conf 0.85-0.95) / `manual` |
| 34 | `confidence` | NUMBER | 0.0–1.0 |

### Bookkeeping (38 fields total)

| # | Field | Type | Notes |
|---|---|---|---|
| 35 | `language_list` | TEXT_ARRAY | Languages present on this row |
| 36 | `fetched_at` | DATE | |
| 37 | `extracted_at` | DATE | |
| 38 | `word_count` | INT | |

### Population strategy

- **Pass 1 — CELLAR SPARQL** (fast, confidence=1.0). Document-level edges from `cdm:resource_legal_amends_resource_legal`, `cdm:resource_legal_repeals_resource_legal`, `cdm:resource_legal_based_on_resource_legal`. Runs when user clicks the "EU Amendments" Run button in the app.
- **Pass 2 — LLM article-level** (confidence=0.85-0.95). Runs INSIDE the Stage 2 metadata extraction of `incremental-laws` when the current CELEX is an amending act. The LLM produces a structured list of amendments (target_celex, article_hierarchy, change_type, old_text, new_text, effective_date, impact_level, chunk_summary) and `amendment_extractor.record_llm_amendments(...)` upserts them.
- **Deduplication** via deterministic Weaviate UUID. `data.update` overwrites on re-insert; higher-confidence row wins because Pass 2 runs after Pass 1 and the LLM output is richer.

### Graph-walk queries (application-layer, no Postgres)

Amendment chain for CELEX X (depth 1):
```python
coll = client.collections.get("EUAmendments")
changes = coll.query.fetch_objects(
    filters=Filter.by_property("target_celex").equal("32016R0679"),
    sort=Sort.by_property("effective_date", ascending=False),
    limit=100,
).objects
```

Depth-N chain: application-layer loop, N sequential queries. For typical N ≤ 3 this is fast enough. If deeper walks become hot, we add a materialized cache.
