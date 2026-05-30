# Schema comparison: current project vs. reference ("best") DB

Generated during AI semantic-search / recommendation-engine planning.
Both databases are Postgres 18.4 with pgvector 0.8.1 available.

## Core architectural difference

The reference DB is a **normalized redesign**, not a superset of ours. Adopting it
wholesale would break the running app, so we adopted only safe, additive AI-relevant
pieces (see migration `002_adopt_reference_best_practices.sql`).

| Concern | Reference design | Our design | Decision |
|---|---|---|---|
| Property vs offering | `properties` (physical) + `listings` (price/status/**embedding**) | single flat `properties` | **Keep ours** — app reads flat columns everywhere |
| Categorical fields | Postgres ENUM types | `varchar` (free-text, Turkish) | **Keep ours** — enums would reject existing data |
| Geography | `cities→districts→locations` + lat/long | flat `country/city/district` text | **Keep ours** — app writes flat text |
| Delete | `deleted_at` + partial indexes | `status='passive'` string | **Keep ours** — app logic keys on status |
| Naming | `title/bedrooms/bathrooms` | `name/beds/baths/room_count` | **Keep ours** — renames break queries |
| Vector index | **HNSW** (m=16, ef_construction=64) | (was planning ivfflat) | **ADOPT HNSW** ✅ |
| Embedding lifecycle | `embedding_status` on listings | `embedding_synced_at` only | **ADOPT embedding_status** ✅ |
| User taste profile | `user_preferences` + `user_preference_features` | none | **ADOPT user_preferences** (flat-adapted) ✅ |
| Behavioral events | `property_views` (+ `session_id`) | `user_events` (generic) | **Keep user_events, ADD session_id** ✅ |
| Indexing | thorough indexes + FKs | almost none | **ADOPT key indexes** ✅ |

## Things the reference has that we intentionally did NOT add
- `transactions`, `appointments`, `platform_settings`, normalized `conversations/messages`
  — out of scope for AI search/recsys, and we already have chat tables.
- `user_preference_features` (preferred features many-to-many) — can add later if the
  recommender needs feature-level preference; deferred to keep this migration tight.
- Geographic lat/long (`locations`) — would enable distance/commute features
  (reference has `max_commute_minutes`); deferred, needs our flat geography geocoded first.

## Applied to the branch (migrations 001 + 002)
- pgvector / pg_trgm / unaccent extensions
- `properties.embedding vector(1536)`, `embedding_text`, `embedding_synced_at`,
  `embedding_status`, `updated_at` (+ auto-update trigger)
- `properties_embedding_hnsw` HNSW index
- `users.taste_embedding`, `taste_updated_at`
- `user_events` (+ `session_id`), `search_logs`, `user_preferences`
- indexes: properties(status), properties(agent_id), property_features(feature_id),
  user_favorites(property_id)

All additive. Main branch untouched; revert by deleting the branch.
