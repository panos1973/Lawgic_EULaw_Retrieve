# Open Questions — Empirical Validation Needed

Things the planning conversation deferred to real-world testing. Each one has a specific validation plan.

## 1. Does Alibaba DashScope caching work on Qwen3.5 Flash / Qwen3.6 Plus via Singapore endpoint?

**Status:** skipped during planning (sandbox couldn't reach DashScope). Validate on first real batch.

**How:** the extractor logs `cached_tokens` on every call. Within 100 calls you'll see definitively whether caching is active.

**Thresholds:**
- Cache hit rate >60% on legislation extraction (with proper prompt structure) = working correctly.
- Cache hit rate ~0% = caching not active on Singapore. Switch Base URL to Beijing (`https://dashscope.aliyuncs.com/compatible-mode/v1`) in Settings and re-verify.
- Hit rate 10-50% = prompt structure wrong (probably not keeping stable prefix first).

**Cost impact if caching doesn't work:** legislation extraction cost rises from ~$40 to ~$80 for Tier A. Still within budget.

## 2. Qwen3.6 Plus quality on case law holdings vs Sonnet 4.5

**Status:** assumed acceptable based on benchmark data, but EU legal text is not in Qwen's reported benchmarks.

**How:** `scripts/eval_extraction.py` runs 20 diverse CJEU judgments through Qwen3.6 Plus + Gemini 2.5 Flash (as reference baseline, not Sonnet since we're skipping Claude). Manual review of `holding`, `legal_principle`, `case_summary`.

**Decision rule:**
- Qwen3.6 Plus output is within ~10-15% semantic fidelity of Gemini → ship Qwen.
- Qwen output is materially worse → revise: use Gemini 2.5 Flash (not batch, interactive with caching) for holdings only. Extra ~$100 cost, quality insurance.

## 3. Cross-lingual retrieval quality for Greek/German queries

**Status:** architecturally planned (named vectors per language), but actual precision unknown.

**How:** build a 100-query golden eval set per target language:
- 100 Greek legal questions, each with expected answer chunk(s) labeled by CELEX + article
- Run retrieval, measure recall@5 and MRR
- Compare: retrieve via `vector_el` only vs `vector_en` only vs hybrid

**Decision rule per market:**
- If recall@5 via `vector_en` alone is within 5% of `vector_el`, we could defer native-language vectors for future markets (save ~$100/language).
- If gap is >10%, native-language vectors are mandatory before launching that market.

**Strong prior:** embed Greek vectors for the Greek market no matter what — your current users read Greek, their queries are in Greek, and legal terminology is language-anchored. Eval is for *future* markets (Germany, France, Italy), not for skipping Greek.

## 4. CDM ontology predicate accuracy

**Status:** predicates in `02_DATA_SOURCES.md` came from web search + prior knowledge, not from parsing the live OWL file.

**How:** `scripts/parse_cdm_ontology.py` using `rdflib`. Phase 1 Task 7.

**Decision rule:** any predicate that returns zero results on a test SPARQL query against CELLAR is either misspelled or doesn't exist. Replace with the actual name from the parsed ontology.

## 5. EuroVoc concept IDs for priority domains

**Status:** IDs in `02_DATA_SOURCES.md` (754 data_protection, 711 employment, etc.) are illustrative examples. Not verified against live EuroVoc.

**How:** query EuroVoc thesaurus at http://eurovoc.europa.eu/ for each English domain label. Record actual ID. Update `config/priority_domains.json`.

**Decision rule:** zero-result SPARQL with these IDs = wrong IDs. Replace.

## 6. Does cached input count toward DashScope rate limits?

**Status:** unknown. Matters for throughput planning.

**How:** during first batch, track queries-per-second achievable. If rate limits trigger despite most input being cached, assume cached tokens DO count toward QPS limit.

**Impact:** if cached tokens count, the 3 QPS default concurrency is fine. If they don't count, paid-tier users can safely push to 20+ QPS.

## 7. Voyage embedding quality on legal Greek

**Status:** `voyage-context-3` is advertised multilingual but Greek legal corpus is underrepresented in public benchmarks.

**How:** 20 pairs of (Greek query, expected Greek chunk). Embed both. Measure cosine similarity. Compare against same pairs translated to English.

**Decision rule:** if Greek same-language similarity is consistently lower than English same-language similarity, consider preprocessing Greek text (removing polytonic accents, normalizing), or investigate `voyage-multilingual-2` instead.

## 8. Postgres query performance on knowledge graph

**Status:** recursive CTE queries assumed fast based on index design, but not load-tested.

**How:** after Phase 3, run the recursive CTE examples from `03_SCHEMAS.md` with `EXPLAIN ANALYZE`. Target: <100ms for depth-5 walk from any CELEX.

**Decision rule:** if queries are >500ms, add materialized views for hot paths (e.g., "current-state graph": all edges filtered to the latest amendment state per target). Don't pre-optimize.

## 9. Should knowledge graph edges also be stored in Weaviate for unified querying?

**Status:** decided no (Postgres only). But if Lawgic's retriever layer finds it awkward to join across two databases, reconsider.

**How:** after Phase 7 integration, monitor retriever code complexity. If joining Weaviate chunks with Postgres edges requires application-layer workarounds that feel forced, consider duplicating edges as Weaviate cross-references.

**Default:** don't. Stay with Postgres. Only reconsider if real friction emerges.

## 10. Should we embed document summaries as separate chunks?

**Status:** decided no (document_summary is a field on every chunk, not its own chunk). But for very broad queries ("what EU data protection laws exist?"), a document-level-only embedding might retrieve better than chunk-level.

**How:** compare retrieval on 20 broad queries vs 20 specific queries. If broad queries systematically miss the right document, add a synthetic document-level chunk per doc (first chunk, text = document_summary).

**Default:** don't. Contextual retrieval + good summaries should handle both. Revisit if empirical gap emerges.

## 11. What happens to repealed law chunks — delete or retain?

**Status:** mark `status='superseded'` in `EULawIngestionStatus` and `superseded_by` on the chunk itself. Don't delete.

**Rationale:** lawyers need access to historical state ("what was the rule at the time of the incident in 2019?"). Retention is legally necessary.

**Retrieval filtering:** default query filter `in_force=true AND superseded_by IS NULL` excludes them. User can opt-in to historical via explicit flag.

**Validation:** monitor query logs for cases where a superseded law SHOULD have been returned (e.g., historical question) but was filtered out. Tune defaults.

## 12. How often should the weekly incremental cron run?

**Status:** assumed weekly. But CELLAR's new-document rate varies widely by week.

**How:** after first month of operation, look at incremental run sizes. If most runs find 0-5 new docs, weekly is fine. If some runs find hundreds (end-of-legislative-session bursts), consider daily or on-demand via Atom feed webhook.

**Default:** weekly. Upgrade to daily only if data shows need.

---

## Validation checklist before Tier A launch

Before considering the MVP done:

- [ ] Cache hit rate >60% verified on 100+ real extraction calls
- [ ] Qwen3.6 Plus holding quality eval passed (or Gemini fallback wired)
- [ ] CDM predicates parsed from live ontology, all SPARQL queries return non-empty results
- [ ] EuroVoc IDs verified against live thesaurus
- [ ] 20-doc extraction eval passed for all 3 models on JSON validity + field completeness
- [ ] Sample 10 random embedded docs, manually verify summaries + metadata are accurate (not hallucinated)
- [ ] Greek vector retrieval tested on 20 Greek queries, sensible top-5 results
- [ ] Knowledge graph recursive CTE performance <100ms on 10 test CELEX
- [ ] Integrity checks pass after full ingestion run (no partial upserts)
- [ ] Cost tracking dashboard shows realistic numbers (within 2x of estimates)
- [ ] Lawgic Lawbot returns useful EU-law results on 10 Greek test queries
- [ ] Electron app incremental update completes without manual intervention on a sample batch

If all boxes checked: Tier A is production-ready.
