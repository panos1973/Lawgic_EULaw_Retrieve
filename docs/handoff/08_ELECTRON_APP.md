# Electron App

## UI layout

```
┌──────────────────────────────────────────────────────────────┐
│  Lawgic EU Law Retrieve                       [Settings ⚙]   │
├──────────────────────────────────────────────────────────────┤
│  Language:  [▾ English     ▾ Greek     + Add language ]      │
│  Scope:     (●) Priority domains    ( ) All in-force         │
│                                                              │
│  Status                                                      │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ English:  ✓ 10,234 embedded  |  last run: 2026-04-12   │  │
│  │ Greek:    ✓ 10,234 embedded  |  last run: 2026-04-12   │  │
│  │                                                        │  │
│  │ New in CELLAR since last run:  23 documents            │  │
│  │ Failed needing retry:          2                       │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  Domain breakdown:                                           │
│    Data protection    (1,245)  ████████████░░                │
│    Employment         (856)    ████████░░░░░░                │
│    Competition        (634)    ██████░░░░░░░░                │
│    Tax                (547)    █████░░░░░░░░░                │
│    ... (10 more)                                             │
│                                                              │
│  [ Run incremental update for English + Greek ]              │
│  [ Add new language: ▾ German ]                              │
│                                                              │
│  Recent activity:                                            │
│    12:34  ✓ Embedded CELEX 32024R1157 (article 1-4)         │
│    12:33  ✓ Embedded CELEX 32024R1156 (article 1-7)         │
│    12:32  ⚠ Retry queued: 32024L0892 (JSON invalid)         │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

## Settings panel

```
Settings
├── API Keys
│   ├── DashScope (Alibaba):       [________________]
│   ├── Google AI Studio:          [________________]
│   └── Voyage AI:                 [________________]
├── Endpoints
│   ├── Weaviate cluster:          [lawgicfeb26.weaviate.network]
│   ├── Postgres DATABASE_URL:     [________________]
│   └── DashScope Base URL:        [https://dashscope-intl.aliyuncs.com/compatible-mode/v1]
├── Models
│   ├── Extraction:                [▾ qwen3.5-flash]
│   ├── Reasoning:                 [▾ qwen3.6-plus]
│   └── Fallback:                  [▾ gemini-2.5-flash]
└── Advanced
    ├── LLM concurrency (QPS):     [3]  (increase if paid tier)
    ├── Courtesy delay (s):        [1]  (between CELLAR SPARQL calls)
    └── Tier scope:                [▾ Priority domains (MVP)]
```

Keys persisted to OS keychain or user's config dir (NOT committed to repo). Same pattern as shipping app.

## IPC handlers (electron/main.js)

Spawn Python subprocess for each operation:

| Action | Python command |
|---|---|
| Refresh status | `python pipeline.py status --json` (reads `EULawIngestionStatus`, returns aggregates) |
| Incremental update | `python pipeline.py incremental --languages en,el --scope priority` |
| Add new language | `python pipeline.py add-language --language de` |
| Estimate cost | `python scripts/estimate_cost.py --scope priority --language de` |
| Run cache verification | `python scripts/verify_qwen_cache.py` (one-off) |
| Run extraction eval | `python scripts/eval_extraction.py --docs 20 --models qwen3.5-flash,qwen3.6-plus,gemini-2.5-flash` |

All Python processes:
- Emit JSON progress events on stdout (parsed by Electron for UI updates)
- Handle SIGTERM gracefully (user can cancel mid-run)
- Write detailed logs to `~/.lawgic_eulaw/logs/`

## "Add new language" flow — detailed

User clicks "Add new language" → selects "German" → confirmation dialog:

```
Add German language to EU Laws + Court Decisions?

This will:
  • Download German XHTML for 10,234 documents
  • Parse and re-embed (English metadata stays; text + vectors only)
  • Add vector_de to each chunk in Weaviate

Estimated cost: ~$97 in Voyage embeddings
Estimated time: ~1 hour

No LLM metadata extraction will run (already done in English).
Knowledge graph unchanged (CELEX-based, language-independent).

[ Cancel ]  [ Start ]
```

On Start → Python executes `language_adder.py --language de`:
1. Query `EULawIngestionStatus` for all CELEX with `status='embedded'` AND `language='en'`.
2. For each: fetch XHTML with `Accept-Language: de`, parse, embed with Voyage, upsert `vector_de` + `text_de` on existing chunk object in Weaviate.
3. After each successful chunk: insert row into `EULawIngestionStatus` with `(celex, language='de', status='embedded')`.
4. Graceful failure handling: missing-German version → `status='missing_source'`, skipped in future runs.
5. Live progress bar in UI, ETA shown.

## "Incremental update" flow — detailed

Runs on demand or via weekly cron (see `09_IMPLEMENTATION_PLAN.md`).

1. **Pre-flight check:** query `EULawIngestionStatus`, derive watermark as `MIN(cellar_recorded_at) WHERE status != 'embedded'`.
2. **Poll CELLAR Atom feed:** fetch entries newer than watermark.
3. **For each new CELEX:**
   - Check `EULawIngestionStatus` — skip if already `status='embedded'` with matching `text_hash`.
   - Fetch XHTML for every enabled language.
   - Parse, Stage 2 LLM extraction (English only), Stage 3 Voyage embed per language, Weaviate upsert.
   - Mark status `embedded` per (celex, language).
4. **Refresh amendment graph:** SPARQL query for new edges involving any CELEX in the incremental set → upsert to `eu_law_edges`.
5. **Repeal detection:** separate SPARQL query checking if any currently-embedded CELEX was repealed by a new one. If yes, mark targets `status='superseded'`.
6. **Emit summary to UI:** "23 new documents embedded, 1 repealed, 0 failed."

## Cron scheduling (optional, recommended)

User can enable weekly auto-run in Settings. Electron app registers a scheduled task via OS-native scheduler (cron on Linux/macOS, Task Scheduler on Windows). Task runs `python pipeline.py incremental --all-languages`. Results emailed or Slack-webhooked per user's notification preferences.

## Error handling surfaced in UI

Every failure goes to the UI with actionable info:

- **JSON invalid (Qwen):** auto-retries once, then queues for Gemini fallback. UI: `⚠ Qwen returned invalid JSON; routed to Gemini fallback batch.`
- **Timeout:** auto-retries with exponential backoff. UI: `⚠ DashScope timeout; retrying in 4s.`
- **Missing XHTML for language:** marks `status='missing_source'` silently, logged to activity feed.
- **Rate limit (429):** backoff + fallback. UI: `⚠ Rate limit hit; slowing down and routing to Gemini.`
- **Hallucinated CELEX:** auto-reject + retry with stricter prompt. UI: `⚠ LLM produced invalid CELEX reference; retrying with validator hint.`
- **Weaviate write failure:** hard fail, don't advance status. UI: `✗ Weaviate upsert failed for 32016R0679; not marked embedded. Check cluster.`

## Chunk inspector panel (existing feature in shipping app, reuse)

Click any embedded CELEX → modal shows:
- Document metadata (CELEX, title, date, in_force)
- Per-language text tabs
- Per-chunk metadata (legal_domain, topic_tags, obligations, cross_references)
- Knowledge graph: amendments TO this doc, amendments FROM this doc, cases interpreting it
- Cost incurred for this doc (Voyage + LLM)

Useful for manual spot-checking during early ingestion.

## Developer-hidden features

Not exposed in UI but runnable via Python CLI:
- Force re-extract metadata for a CELEX
- Force re-embed a specific language
- Dump the entire knowledge graph as GraphML for visualization
- Replay a specific day's incremental run from logs
