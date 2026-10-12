-- ============================================================
-- Migration 001: AI foundation (semantic search + recommendations)
-- Target: ai-semantic-search Neon branch ONLY.
-- Idempotent: safe to re-run. Reversible by deleting the branch.
-- ============================================================

-- ---- Section A: extensions --------------------------------
CREATE EXTENSION IF NOT EXISTS vector;     -- pgvector: embedding storage + similarity
CREATE EXTENSION IF NOT EXISTS pg_trgm;    -- typo-tolerant fuzzy keyword fallback
CREATE EXTENSION IF NOT EXISTS unaccent;   -- diacritic-insensitive (Turkish) matching

-- ---- Section A: properties embedding columns --------------
ALTER TABLE properties ADD COLUMN IF NOT EXISTS embedding           vector(1536);   -- OpenAI text-embedding-3-small
ALTER TABLE properties ADD COLUMN IF NOT EXISTS embedding_text      text;           -- exact source string we embedded
ALTER TABLE properties ADD COLUMN IF NOT EXISTS embedding_synced_at timestamptz;    -- NULL = needs (re)embedding
ALTER TABLE properties ADD COLUMN IF NOT EXISTS updated_at          timestamptz DEFAULT now();

-- keep updated_at fresh so we can detect which rows changed and need re-embedding
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_properties_updated_at ON properties;
CREATE TRIGGER trg_properties_updated_at
    BEFORE UPDATE ON properties
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- NOTE: ivfflat index is intentionally created AFTER the embedding backfill,
-- not here -- an index over 0/22 rows is useless and would need rebuilding.

-- ---- Section B: recommendation engine ---------------------
-- behavioral events (today only favorites are captured; add views/contacts/clicks)
CREATE TABLE IF NOT EXISTS user_events (
    id          serial PRIMARY KEY,
    user_id     integer REFERENCES users(id),
    property_id integer REFERENCES properties(id),
    event_type  varchar(20) NOT NULL,   -- 'view' | 'favorite' | 'contact' | 'search_click'
    created_at  timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_user_events_user     ON user_events(user_id);
CREATE INDEX IF NOT EXISTS idx_user_events_property ON user_events(property_id);
CREATE INDEX IF NOT EXISTS idx_user_events_type     ON user_events(event_type);

-- derived per-user taste vector (avg of embeddings of items the user engaged with)
ALTER TABLE users ADD COLUMN IF NOT EXISTS taste_embedding  vector(1536);
ALTER TABLE users ADD COLUMN IF NOT EXISTS taste_updated_at timestamptz;

-- ---- Section C: search logging (feeds failed-search Pareto + future ranking)
CREATE TABLE IF NOT EXISTS search_logs (
    id           serial PRIMARY KEY,
    user_id      integer REFERENCES users(id),
    query_text   text,
    filters_json jsonb,
    result_count integer,
    created_at   timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_search_logs_created ON search_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_search_logs_zero    ON search_logs(result_count) WHERE result_count = 0;
