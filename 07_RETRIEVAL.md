# Retrieval Accuracy

Patterns ranked by impact on retrieval precision. Top of the list = implement first.

## 1. Contextual retrieval (Anthropic pattern) — REQUIRED, NOT OPTIONAL

**What:** prepend each chunk with a ~50-token context describing *where it sits in the document* before embedding.

**Example:**
```
contextual_prefix:
"This is Article 17 of Regulation (EU) 2016/679 (GDPR), within Chapter III 
(Rights of the Data Subject), which establishes the right to erasure 
('right to be forgotten'). The article covers:"

[followed by the actual article text]
```

**Why:** Anthropic's published benchmarks show **35-49% retrieval improvement** on legal corpora with this technique alone. It leverages structural metadata we already have from CELLAR + parse output — free context.

**Implementation:** generate the prefix during Stage 1 parsing (not Stage 2 LLM — it's a template fill from structured data). Template:
```
"This is {chunk_type} {chunk_id} of {document_subtype} ({celex}) — 
{document_title_short}, within {parent_section_heading}. The chunk covers:"
```

Store in `contextual_prefix` field. Embedding input becomes:
```
f"{contextual_prefix} {chunk_summary} {text}"
```

Do NOT display the contextual prefix to the user. It's an embedding hint only.

## 2. Document + chunk summaries (both levels)

**Document summary:** 3-5 sentences (legislation) or 4-6 sentences (case law, must state the holding). Generated ONCE per doc on the first chunk, copied to every chunk of that doc.

**Chunk summary:** 1-2 sentences MAX. Per chunk.

**Why both levels:** a broad question ("what EU regulations govern data processing?") matches at the document summary level; a specific question ("what does Article 17(3)(c) say about exemptions?") matches at the chunk summary level.

**Prompt pattern for the LLM:**
```
For each article chunk, generate:
- document_summary: only on the first chunk of this document; 3-5 sentences about what the entire regulation does
- chunk_summary: 1-2 sentences MAX about what this specific article requires. Plain English. No legal jargon.
```

Cache the document summary across chunks in memory — don't re-generate it per chunk. Only the first chunk's extraction call produces it; subsequent chunks copy it from a per-doc cache.

## 3. Controlled vocabulary for Gemini-enriched queries

Lawgic uses Gemini 2.5 Flash to enrich lawyer queries before RAG — adds legal_domain, topic_tags, temporal hints, court hints. For Gemini's enrichment to actually filter retrieval correctly, the values it outputs MUST match exactly what's stored in our metadata.

**File:** `config/controlled_vocab.json`

Structure:
```json
{
  "legal_domain": [
    "data_protection", "employment", "competition", "tax", "IP",
    "environmental", "consumer", "company", "financial", "commercial",
    "criminal", "asylum"
  ],
  "topic_tags": {
    "data_protection": [
      "processing_principles", "lawfulness", "consent", "data_subject_rights",
      "data_breach", "breach_notification", "DPIA", "DPO", "cross_border_transfer",
      "supervisory_authority", "certification", "children_data", "profiling", ...
    ],
    "employment": [ ... ],
    ...
  },
  "applies_to": [
    "controller", "processor", "employer", "employee", "importer", "exporter",
    "consumer", "public-authority", "SME", "large-enterprise", ...
  ]
}
```

**This file is referenced by:**
1. The extraction prompt (appended as a constraint: "use ONLY values from this list")
2. Gemini's query-enrichment prompt (same list, same tokens)
3. The retriever's filter-validator (reject filters that don't match vocab)

**Keep all three in sync.** One canonical source, three consumers.

## 4. Hybrid BM25 + vector search with adaptive alpha

Already proven in Lawgic's Greek retriever (`weaviate_law_retriever.tsx`). Mirror for EU:

- `alpha = 0.3` when query contains explicit law reference (`"Regulation (EU) 2016/679"`, `"Article 17"`, CELEX number) — exact-match beats semantic
- `alpha = 0.7` for conceptual queries ("right to be forgotten", "data portability") — vector beats keyword
- `alpha = 0.5` default

## 5. Voyage rerank-2.5 on top-20

Over-retrieve 3x the needed top-k, rerank with Voyage `rerank-2.5`, trim to budget. Non-negotiable — proven ~10-15% precision gain on legal text. Already in Lawgic's stack; reuse the same pattern.

## 6. Citation-graph boosting

If Regulation X appears as a `cross_references` target in 4+ of your retrieved top-20 chunks, it's probably relevant even if its own vector score is middling. Boost X's chunks into the top-10.

Implementation: after rerank, count `cross_references` appearances per CELEX across the result set. Boost score of any CELEX cited 3+ times by +0.15.

Requires the edges table (`eu_law_edges`) to be populated — another reason why knowledge graph is Tier 0 work.

## 7. Multi-hop query decomposition for complex questions

"Is GDPR Article 17 affected by the Data Act?" → decompose into:
1. "What does GDPR Article 17 say?" → vector search
2. "Does the Data Act (Regulation 2023/2854) cite/amend/interpret GDPR Article 17?" → knowledge graph walk
3. Merge results, highlight any direct relationships

Mirrors Lawgic's Case Study decomposition pattern (`src/lib/map-reduce.ts`).

## 8. Temporal + in-force filters by default

All retrieval queries should add by default:
```
filter: in_force = true AND superseded_by IS NULL
```

UNLESS the user explicitly asks for "historical", "what used to be the rule", or cites a specific past date. Then strip the filter.

Prevents surfacing repealed rules as current law — a legal-malpractice-level risk.

## 9. Recital down-weighting

EU legislation recitals are interpretive preamble ("Whereas... the legislator considered... however... therefore..."). They provide context for understanding operative articles but are NOT legally binding.

Store `chunk_type = 'recital'` vs `chunk_type = 'article'`. At retrieval time, down-weight recital chunks by 0.5x their vector score unless the query explicitly asks about legislative intent ("why was this law passed", "what was the rationale").

## 10. Cross-encoder reranking (optional, stretch goal)

After voyage rerank, run a cross-encoder on top-20. Adds ~100ms latency but measurable precision gain on ambiguous queries. Defer to Phase 4+.

## Chunking strategies

### Legislation — article-level

- One article = one chunk (typical 200-800 words).
- Articles > 1500 words → split at paragraph boundaries, keep article number + heading in every chunk.
- Articles < 50 words ("This Regulation shall enter into force...") → group with adjacent short articles.
- Recitals → group 5-10 recitals per chunk.
- Annexes → split by logical section (tables, forms, technical specs).

### Case law — two-level

**Level 1 — Holding chunk (one per decision):**
Combines operative part + key findings + questions referred. Fields generated by LLM with reasoning ON (Qwen3.6 Plus):
- `case_summary`, `legal_principle`, `holding`, `regulations_interpreted`

Embedding input weights `case_summary + legal_principle + holding + contextual_prefix` — optimized for "what did the court decide?" queries.

**Level 2 — Reasoning chunks (3-8 per decision):**
Detailed findings, split into logical groups of 3-5 numbered paragraphs dealing with the same sub-issue.

Embedding input weights `chunk_summary + text + contextual_prefix` — optimized for "what was the court's reasoning on point X?" queries.

Reasoning chunks inherit document-level fields (`case_summary`, `regulations_interpreted`, `court_level`, etc.) from the holding chunk.

## No overlap between chunks

Voyage `voyage-context-3` is contextualized — it embeds chunks with awareness of surrounding chunks within a context window. **Do NOT add text overlap between chunks.** Waste of tokens and storage.

Use context windows (~20k tokens) to group chunks from the same document for the embed API call. Voyage handles the context integration internally.

## Response to Lawgic's existing retrievers

The retrievers already in `lawgic_corp/src/lib/retrievers/` work well for Greek. Minimal changes needed:
- Add `target_vector` parameter based on query language (see `04_LANGUAGE_STRATEGY.md`)
- Change collection names: `GreekLaws` → `EULaws`, `GreekCourtDecisions` → `EUCourtDecisions`
- Keep amendment-chain XML-tag pattern (`<source_law_number>`/`<target_law_number>`) — works identically for EU once edges table is populated and rendered as XML on retrieval response

No structural rewrites. Just configuration + small additions.
