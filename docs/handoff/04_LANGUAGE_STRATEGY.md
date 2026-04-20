# Language Strategy

## The decision in one sentence

**One Weaviate collection per document type, with multiple named vectors per chunk (one per embedded language) and English-only metadata.** This is locked.

## Why this beats the alternatives

| Approach | Pros | Cons | Verdict |
|---|---|---|---|
| English-only embeddings, multilingual retrieval via voyage-multilingual | Cheapest, simplest | Uncertain accuracy for exact-term + citation queries in Greek/German | Rejected — too risky for legal work |
| Separate collection per language (`EULaws_EN`, `EULaws_EL`, `EULaws_DE`) | Clean language isolation | Metadata duplicated 5x, cross-language retrieval broken, graph joins awkward | Rejected |
| **Named vectors per language in ONE collection** | Single vector space for graph joins, metadata stored once, incremental per-market rollout | Slightly more complex chunk objects | **Chosen** |

Requires **Weaviate 1.24+** for named-vectors support. Verify cluster version before implementing.

## How named vectors work

Each chunk object in `EULaws` (or `EUCourtDecisions`) has:
- **Text fields per language:** `text_en`, `text_el`, `text_de`, `text_fr`, `text_it` — stored once each.
- **Named vectors per language:** `vector_en`, `vector_el`, `vector_de`, `vector_fr`, `vector_it` — each a separate HNSW+RQ index.
- **Metadata fields:** stored ONCE (English), language-independent. `legal_domain`, `obligations`, `cross_references`, all graph edges, etc.

Example Weaviate schema fragment:
```python
from weaviate.classes.config import Configure, Property, DataType, VectorDistances

client.collections.create(
    name="EULaws",
    vectorizer_config=[
        Configure.NamedVectors.none(
            name="vector_en",
            vector_index_config=Configure.VectorIndex.hnsw(
                quantizer=Configure.VectorIndex.Quantizer.rq(bits=8),
                distance_metric=VectorDistances.DOT,
            ),
        ),
        Configure.NamedVectors.none(
            name="vector_el",
            vector_index_config=Configure.VectorIndex.hnsw(
                quantizer=Configure.VectorIndex.Quantizer.rq(bits=8),
                distance_metric=VectorDistances.DOT,
            ),
        ),
        # vector_de, vector_fr, vector_it added when those markets launch
    ],
    properties=[
        Property(name="text_en", data_type=DataType.TEXT),
        Property(name="text_el", data_type=DataType.TEXT),
        # ... see 03_SCHEMAS.md for full list
    ],
)
```

Upsert pattern:
```python
collection.data.insert(
    uuid=uuid5(f"{celex}::{chunk_id}"),
    properties={"text_en": ..., "text_el": ..., "legal_domain": ..., ...},
    vector={
        "vector_en": voyage_embed(text_en, model="voyage-context-3"),
        "vector_el": voyage_embed(text_el, model="voyage-context-3"),
    },
)
```

Query pattern (detect query language, search matching vector):
```python
# Greek query from Athens
result = collection.query.near_vector(
    near_vector=voyage_embed(query_el, model="voyage-context-3"),
    target_vector="vector_el",    # <-- this routes to the right index
    filters=Filter.by_property("in_force").equal(True),
    limit=10,
)
```

## Per-market rollout — pay as you grow

**Launch order:** English + Greek (today, Greek market).  
**Next:** Germany (9 months), France, Italy.

**What happens when you add a language (e.g., German in 9 months):**

| Pipeline step | Re-done? | Cost |
|---|---|---|
| SPARQL query CELLAR (get CELEX list) | **No** — already have the list | $0 |
| XHTML download in German | Yes, but trivial — HTTP GET with `Accept-Language: de` | ~30 min for 35k docs |
| Parse into chunks | Yes — same article structure across languages | ~10 min |
| LLM metadata extraction | **No** — metadata stays English | $0 |
| Summaries (doc + chunk) | **No** — stays English | $0 |
| Knowledge graph | **No** — CELEX-based, language-independent | $0 |
| Voyage embeddings for German text | **Yes — the main spend** | ~$97 |
| Weaviate upsert as `vector_de` on existing chunks | Yes | ~15 min |
| **Total incremental cost** | | **~$100 + 1 hour of compute** |

Expensive one-time work (SPARQL, LLM metadata, graph) never repeats per language.

## Implementation in `python/eu/language_adder.py`

Dedicated module for the "add new language" flow. Crucial: it must NOT call Stage 2 (LLM metadata extraction) — only fetch, parse, embed.

Pseudocode:
```python
def add_language(language_code: str, scope: str = "priority_domains"):
    # 1. Enumerate CELEX list from existing EULawIngestionStatus rows (English embedded)
    celex_list = status.list_embedded(language="en")
    
    for celex in celex_list:
        # 2. Fetch XHTML in target language
        xhtml = fetch_item(celex, accept_language=language_code)
        if xhtml is None:
            status.mark(celex, language_code, status="missing_source")
            continue
        
        # 3. Parse (same logic, same chunk IDs as English)
        chunks = parse_xhtml(xhtml, celex)
        
        # 4. Embed with Voyage
        for chunk in chunks:
            embedding = voyage_embed(chunk.text, model="voyage-context-3")
            # 5. Upsert named vector onto existing chunk object
            weaviate_update_named_vector(
                uuid=uuid5(f"{celex}::{chunk.id}"),
                vector_name=f"vector_{language_code}",
                vector=embedding,
                text_property=f"text_{language_code}",
                text_value=chunk.text,
            )
        
        # 6. Update status
        status.mark(celex, language_code, status="embedded")
```

## Language-of-case handling for judgments

CJEU decisions have a "language of the case" (the party's language). The authentic version is in that language; other language versions are translations. Store this in `EUCourtDecisions.language_of_case`.

At retrieval, when a lawyer needs to cite with full precision, surface the language-of-case version alongside the Greek/English versions. Lawgic's answer generation can note: *"The authentic version of this judgment is in French; the Greek translation may have minor terminological differences."*

## Missing language fallback

Some pre-Cyprus-accession (2004) and pre-Greek-accession (1981) acts lack Greek versions. Some pre-1973 acts lack English versions. Handle gracefully:

- If `text_X` is missing for language X, skip vector generation for that language on that chunk.
- At query time, if target language vector is missing on a chunk, fall back to `vector_en`.
- On `EULawIngestionStatus`, mark `status='missing_source'` for that (celex, language) pair so we don't retry forever.

## What Lawgic's existing retrievers need to change

Minimal. In `lawgic_corp/src/lib/retrievers/weaviate_law_retriever.tsx`:

```typescript
// Before (Greek only):
const collection = client.collections.get("GreekLaws");
const result = await collection.query.hybrid(query, { ... });

// After (EU + Greek):
const euCollection = client.collections.get("EULaws");
const targetVector = detectLanguage(query) === "el" ? "vector_el" : "vector_en";
const result = await euCollection.query.hybrid(query, {
  targetVector: targetVector,
  ...
});
```

One file, ~20 lines of changes. Same pattern for `weaviate_court_retriever.tsx`.

## Future-proofing

When adding a new market, the only config change is:
1. Add language code to `config/languages.json`.
2. Add named vector slot to Weaviate schema (via `client.collections.get(...).config.add_named_vector(...)` — no migration).
3. Trigger `language_adder.py` with the new code.

No code changes. No retriever rewrites. No collection migrations.
