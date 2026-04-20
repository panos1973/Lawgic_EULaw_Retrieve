-- Postgres knowledge graph for EU legal amendments + case-law interpretations.
-- Per docs/handoff/03_SCHEMAS.md section 4.
--
-- Runs in Lawgic's existing Postgres (same instance as the pgvector
-- uploaded-file embeddings). No new infrastructure.
--
-- Pass 1: CELLAR SPARQL -> confidence=1.0, data_source='cellar_sparql'
-- Pass 2: LLM extraction during Stage 2 -> confidence=0.85-0.95,
--         data_source='llm_extraction'
--
-- The ON CONFLICT rule in python/eu/amendment_extractor.py preserves the
-- higher-confidence row's data_source when duplicate edges are inserted.

CREATE TABLE IF NOT EXISTS eu_law_edges (
  id                         BIGSERIAL PRIMARY KEY,
  source_celex               TEXT NOT NULL,
  source_article             TEXT,
  target_celex               TEXT NOT NULL,
  target_article             TEXT,
  relation_type              TEXT NOT NULL CHECK (relation_type IN (
      'amends', 'repeals', 'replaces', 'adds', 'modifies', 'renumbers',
      'consolidates', 'based_on', 'corrects', 'implements',
      'interprets', 'cites'
  )),
  interpretation_strength    TEXT CHECK (interpretation_strength IN (
      'applies', 'distinguishes', 'establishes', 'overrides', 'clarifies'
  )),
  effective_date             DATE,
  confidence                 NUMERIC(3,2) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  data_source                TEXT NOT NULL CHECK (data_source IN (
      'cellar_sparql', 'llm_extraction', 'manual'
  )),
  extracted_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  source_doc_type            TEXT,
  UNIQUE (source_celex, source_article, target_celex, target_article, relation_type)
);

CREATE INDEX IF NOT EXISTS eu_law_edges_source_idx
    ON eu_law_edges (source_celex, source_article);
CREATE INDEX IF NOT EXISTS eu_law_edges_target_idx
    ON eu_law_edges (target_celex, target_article);
CREATE INDEX IF NOT EXISTS eu_law_edges_relation_idx
    ON eu_law_edges (relation_type);
CREATE INDEX IF NOT EXISTS eu_law_edges_effective_idx
    ON eu_law_edges (effective_date);

-- Example graph-walk queries (reference only; do not run on migration).
--
-- Amendment chain back from a CELEX:
-- WITH RECURSIVE chain AS (
--   SELECT source_celex, target_celex, 1 AS depth
--   FROM eu_law_edges
--   WHERE target_celex = $1
--     AND relation_type IN ('amends', 'repeals', 'replaces')
--   UNION
--   SELECT e.source_celex, e.target_celex, c.depth + 1
--   FROM eu_law_edges e JOIN chain c ON e.target_celex = c.source_celex
--   WHERE c.depth < 5
--     AND e.relation_type IN ('amends', 'repeals', 'replaces')
-- )
-- SELECT * FROM chain;
--
-- Cases interpreting an article:
-- SELECT source_celex, source_doc_type, effective_date, interpretation_strength
-- FROM eu_law_edges
-- WHERE relation_type = 'interprets'
--   AND target_celex = $1 AND target_article = $2
-- ORDER BY effective_date DESC;
