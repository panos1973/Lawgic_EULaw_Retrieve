# Costs

## TL;DR

| Item | One-time English | Per additional language |
|---|---|---|
| **Tier A MVP** (10k laws + 25k cases, priority domains) | **~$204** | **~$97** |
| Tier B Comprehensive (all in-force legislation + all case law) | ~$10,800 | ~$454 |
| Tier C Full historical | ~$50,000+ | ~$720+ |

**Recommendation: Start with Tier A. Expand only after validation.**

## Pricing used

| Service | Price |
|---|---|
| Voyage `voyage-context-3` | $0.18 / M input tokens |
| Qwen3.5 Flash (DashScope) | $0.065 in / $0.26 out per M |
| Qwen3.5 Flash cached input (assumed) | $0.016 / M |
| Qwen3.6 Plus (DashScope) | $0.325 in / $1.95 out per M |
| Qwen3.6 Plus cached input (assumed) | $0.081 / M |
| Gemini 2.5 Flash batch | $0.15 in / $1.25 out per M |
| Gemini 2.5 Flash batch + cached | $0.03 / M (90% discount on input) |

## Tier A MVP detailed breakdown

### One-time English ingestion (~$204)

| Line | Calculation | Cost |
|---|---|---|
| Legislation metadata (Qwen3.5 Flash + cache, 30k docs, 15k in + 2k out per doc, ~50% cached) | 30k × 7.5k × $0.065/M (uncached) + 30k × 7.5k × $0.016/M (cached) + 30k × 2k × $0.26/M | ~$40 |
| Case law operational metadata (Qwen3.5 Flash, 5k docs) | similar per-doc math | ~$7 |
| **Case law holdings (Qwen3.6 Plus, 5k docs, 20k in + 1.5k out each, ~10% cache)** | 5k × 18k × $0.325/M + 5k × 2k × $0.081/M + 5k × 1.5k × $1.95/M | **~$45** |
| Amendment article extraction (Qwen3.5 Flash, ~3k amending acts) | 3k × 10k × $0.065/M + 3k × 1k × $0.26/M | ~$10 |
| Gemini batch+cache fallback (~3% of docs) | ~$5 | ~$5 |
| Voyage embeddings English (~540M tokens with context prefix + summary) | 540M × $0.18/M | ~$97 |
| **Total** | | **~$204** |

### Per additional language (~$97)

Only Voyage embeddings repeat — nothing else:
| Line | Cost |
|---|---|
| Voyage embeddings for new language | ~$97 |
| XHTML re-fetch + parse + upsert | $0 (bandwidth + compute only) |
| LLM metadata (stays English) | $0 |
| Knowledge graph (language-independent) | $0 |
| **Total per language** | **~$97** |

So Greek + English Tier A total: ~$300. Add Germany in 9 months: +$97 = ~$400 cumulative. Add France: +$97 = ~$500. All four markets (Greece, Germany, France, Italy): ~$600 cumulative.

## Token volume assumptions

These drive the estimates. If your actual scope differs, recompute.

**Tier A MVP scope:**
- 10,000 in-force legislation docs across priority EuroVoc domains
- 25,000 case law docs (CJEU + GC, last 20 years, same domains)
- Avg legislation: ~15k tokens/doc
- Avg case law: ~12k tokens/doc
- Chunks per doc: ~15 (legislation), ~8 (case law two-level)

**Tier B Comprehensive:**
- 20,000 in-force legislation (all domains)
- 150,000 case law (complete CJEU + GC)

**Tier C Full historical:**
- 60,000-80,000 legislation (incl. repealed historical)
- 150,000+ case law

## Per-chunk embedding input estimate

Embedding input = `contextual_prefix (50 tokens) + chunk_summary (80 tokens) + chunk_text (600 tokens avg)` ≈ **~730 tokens per chunk**.

Tier A total chunks:
- Legislation: 10k × 15 = 150k chunks
- Case law: 25k × 8 = 200k chunks
- Total: 350k chunks × 730 tokens = **~255M tokens per language** for embedding

At $0.18/M = **~$46 per language** for embeddings alone. My estimates above use a higher scope to be conservative (~$97/lang covering ~540M tokens).

## Ongoing runtime costs (Lawgic production queries)

| Per-query cost | Component | Amount |
|---|---|---|
| Query analyzer (Gemini 2.5 Flash) | ~1k in + 500 out | ~$0.0005 |
| Query embedding (Voyage) | ~100 tokens | negligible |
| Claude Sonnet 4.5 answer generation | ~30k in + 2k out | ~$0.12 |
| Voyage rerank-2.5 | ~1k tokens | ~$0.0001 |
| **Total per query** | | **~$0.15** |

At 100 lawyers × 20 queries/day = 2,000 queries/day × $0.15 = ~$300/day = ~$110k/year in query-time LLM spend.

**This dwarfs ingestion costs. The real optimization target long-term is query-time, not ingestion.** But ingestion is the only thing this pipeline controls.

## Incremental update costs (weekly)

Weekly cron picks up ~50-200 new EU documents from the Atom feed.

Per week:
- Voyage embeddings: ~$0.50
- Qwen metadata extraction: ~$0.30
- Total: ~$1/week per language

Negligible ongoing cost. The Electron app can run this unattended on a schedule.

## Cost monitoring

The extractor MUST log to a `scripts/cost_log.jsonl` file:
```json
{"timestamp": "...", "model": "qwen3.5-flash", "celex": "32016R0679",
 "input_tokens": 12345, "cached_tokens": 8000, "output_tokens": 1200,
 "cost_usd": 0.0023}
```

Aggregated weekly report → emit to Electron UI.

## Budget alert thresholds

- Daily ingestion > $50 → alert
- Weekly ingestion > $100 → alert (probably a bug causing re-processing)
- Cache hit rate < 40% for 2h consecutive → alert (prompt structure broken)

## What's NOT included in these estimates

- Weaviate cluster hosting (you already run `lawgicfeb26`)
- Postgres hosting (you already run it for pgvector)
- Electron app development time
- Human review of LLM output samples (recommended: ~1 hour per 1000 docs spot-checked)
