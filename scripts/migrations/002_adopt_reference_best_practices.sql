-- ============================================================
-- Migration 002: adopt SAFE semantic-search / recsys improvements
-- distilled from the reference ("best") schema.
-- ADDITIVE ONLY. No drops, no renames, no type changes.
-- Target: ai-semantic-search Neon branch ONLY. Idempotent.
--
-- Deliberately NOT adopted (would break the running app):
--   properties/listings split, ENUM types, normalized geography
--   (cities/districts/locations), deleted_at soft-delete, column
--   renames (title/bedrooms). Those are a redesign, not an addition.
-- ============================================================

-- A. Embedding lifecycle status (ref: listings.embedding_status).
--    Complements embedding_synced_at; lets the backfill retry failures.
ALTER TABLE properties
    ADD COLUMN IF NOT EXISTS embedding_status varchar(16) NOT NULL DEFAULT 'pending';
    -- values: pending | processing | done | failed

-- B. HNSW vector index (ref uses hnsw, not ivfflat).
--    HNSW needs no training data -> safe to build now on the empty column;
--    it grows incrementally as embeddings are backfilled. 1536 dims < 2000 limit.
CREATE INDEX IF NOT EXISTS properties_embedding_hnsw
    ON properties USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- C. Structured user-preference profile for recommendations
--    (ref: user_preferences), adapted to OUR flat geography & column names.
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id            integer PRIMARY KEY REFERENCES users(id),
    preferred_city     varchar,
    preferred_district varchar,
    min_price          integer,
    max_price          integer,
    min_beds           integer,
    max_beds           integer,
    property_type      text,
    furnished          varchar,
    updated_at         timestamptz DEFAULT now()
);

-- D. Anonymous-visitor tracking (ref: property_views.session_id).
ALTER TABLE user_events
    ADD COLUMN IF NOT EXISTS session_id varchar;

-- E. Indexes our schema lacks that the reference has (safe perf for search/recsys).
CREATE INDEX IF NOT EXISTS idx_properties_status        ON properties(status);
CREATE INDEX IF NOT EXISTS idx_properties_agent         ON properties(agent_id);
CREATE INDEX IF NOT EXISTS idx_property_features_feature ON property_features(feature_id);
CREATE INDEX IF NOT EXISTS idx_user_favorites_property  ON user_favorites(property_id);
