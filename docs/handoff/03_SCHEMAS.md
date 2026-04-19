# Schemas

Three Weaviate collections + one Postgres table. All schemas locked — do not add or remove fields without reason.

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

**Uniqueness key:** `uuid5(celex + "::" + language)` — same CELEX in two languages = two status rows.

| # | Field | Type | Notes |
|---|---|---|---|
| 1 | `celex` | TEXT | |
| 2 | `language` | TEXT | ISO 639-1: `en`, `el`, `de`, `fr`, `it` |
| 3 | `document_type` | TEXT | `legislation` or `case_law` |
| 4 | `cellar_recorded_at` | DATE | From Atom feed — monotonic. Used to derive watermark. |
| 5 | `text_hash` | TEXT | SHA-256 of fetched XHTML. Detects re-fetch needed. |
| 6 | `status` | TEXT | Enum: `discovered`, `fetched`, `enriched`, `embedded`, `failed_fetch`, `failed_enrich`, `failed_embed`, `failed_integrity`, `superseded` |
| 7 | `last_updated_at` | DATE | Touched on every state transition |
| 8 | `superseded_by` | TEXT | Nullable; CELEX of repealing act |
| 9 | `retry_count` | INT | Default 0, max 3 for failed states |
| 10 | `error_message` | TEXT | Nullable; only populated on failed states |

**Total: 10 fields.** Deliberately minimal.

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

## 4. `eu_law_edges` Postgres table

**Purpose:** Knowledge graph. Amendments, repeals, citations, interpretations. NOT in Weaviate — lives in the same Postgres instance as Lawgic's existing `pgvector` uploaded-file embeddings.

```sql
CREATE TABLE eu_law_edges (
  id                         BIGSERIAL PRIMARY KEY,
  source_celex               TEXT NOT NULL,
  source_article             TEXT,                    -- nullable for doc-level edges
  target_celex               TEXT NOT NULL,
  target_article             TEXT,                    -- nullable for doc-level edges
  relation_type              TEXT NOT NULL CHECK (relation_type IN (
      'amends', 'repeals', 'replaces', 'adds', 'modifies', 'renumbers',
      'consolidates', 'based_on', 'corrects', 'implements',
      'interprets', 'cites'
  )),
  interpretation_strength    TEXT CHECK (interpretation_strength IN (
      'applies', 'distinguishes', 'establishes', 'overrides', 'clarifies'
  )),                                                 -- populated for case-law edges only
  effective_date             DATE,
  confidence                 NUMERIC(3,2) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  data_source                TEXT NOT NULL CHECK (data_source IN (
      'cellar_sparql', 'llm_extraction', 'manual'
  )),
  extracted_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  source_doc_type            TEXT,                    -- legislation | case_law
  UNIQUE (source_celex, source_article, target_celex, target_article, relation_type)
);

CREATE INDEX eu_law_edges_source_idx ON eu_law_edges (source_celex, source_article);
CREATE INDEX eu_law_edges_target_idx ON eu_law_edges (target_celex, target_article);
CREATE INDEX eu_law_edges_relation_idx ON eu_law_edges (relation_type);
CREATE INDEX eu_law_edges_effective_idx ON eu_law_edges (effective_date);
```

**Population strategy:**
- **Pass 1 (fast, high confidence):** CELLAR SPARQL dump using the predicates from `02_DATA_SOURCES.md`. Produces confidence=1.0 edges at document level. `data_source='cellar_sparql'`.
- **Pass 2 (LLM, medium confidence):** Runs during Stage 2 metadata extraction. Extracts article-level citations from the amending act's text (formulaic — "Article X is replaced by..."), classifies interpretation strength for case-law edges. `data_source='llm_extraction'`, `confidence=0.85-0.95`.
- **Deduplication:** `INSERT ... ON CONFLICT (source_celex, source_article, target_celex, target_article, relation_type) DO UPDATE SET confidence = GREATEST(excluded.confidence, eu_law_edges.confidence), data_source = CASE WHEN excluded.confidence > eu_law_edges.confidence THEN excluded.data_source ELSE eu_law_edges.data_source END`

**Graph walk examples (recursive CTE):**
```sql
-- Amendment chain: what laws led to the current state of CELEX X?
WITH RECURSIVE chain AS (
  SELECT source_celex, target_celex, 1 AS depth
  FROM eu_law_edges
  WHERE target_celex = $1 AND relation_type IN ('amends', 'repeals', 'replaces')
  UNION
  SELECT e.source_celex, e.target_celex, c.depth + 1
  FROM eu_law_edges e JOIN chain c ON e.target_celex = c.source_celex
  WHERE c.depth < 5 AND e.relation_type IN ('amends', 'repeals', 'replaces')
)
SELECT * FROM chain;

-- All cases interpreting a specific article
SELECT source_celex, source_doc_type, effective_date, interpretation_strength
FROM eu_law_edges
WHERE relation_type = 'interprets' 
  AND target_celex = $1 AND target_article = $2
ORDER BY effective_date DESC;
```
