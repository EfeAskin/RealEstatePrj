# Semantic Search & Recommendation Engine — Implementation Guide (this project)

Adapted from the reference TRNC guide to **our actual schema and data**. The reference
assumed a normalized `listings`/`properties`/`districts` design with ENUMs; ours is a
single **flat `properties`** table with free-text columns. All SQL below is rewritten
accordingly, and every component maps to a real file in this repo.

> Status: built and running in **graceful-degradation mode** (keyword search) until
> `OPENAI_API_KEY` is added to `.env`. The database (Neon branch `ai-semantic-search`)
> is already migrated; the code is already wired.

---

## 1. Architecture — four-stage pipeline

```
query → (1) normalize     place aliases (TR/EN, North Cyprus + Turkey)
      → (2) extract        GPT → validated JSON hard-filter object
      → (3) filter         SQL candidate set on properties (+ relaxation)
      → (4) rerank         pgvector HNSW cosine on the candidates → top-K
```

| Stage | Responsibility | File | Runs at |
|---|---|---|---|
| 1 | TR→EN place normalization | `services/place_aliases.py` | query time |
| 2 | NL → validated filter dict (GPT) | `services/constraint_extractor.py` | query time |
| 3 | Hard-filter candidate set (+relax) | `services/query_pipeline.py` | query time |
| 4 | Vector rerank | `services/query_pipeline.py` / `routers/property_filter.py` | query time |
| — | Build & store listing vectors | `scripts/backfill_embeddings.py` | index time (async) |

**Graceful degradation** (all implemented): GPT fails → skip hard filters, still rerank;
embeddings fail → keyword/keyword-order results; 0 rows → relax least-critical constraint
and retry; nothing ever 500s.

---

## 2. Database mapping (our flat schema)

Semantic content embedded per property (`services/document_builder.py`):
`name`, `property_type`, `listing_type`, `room_count`/`beds`/`baths`, `net_m2`/`gross_m2`,
`city`/`district`/`country`, `heating`, `building_age`, `description`, and the **bilingual
feature names** from `property_features → features` (e.g. `Balcony`, `Deniz Manzarası`).

AI columns/tables (Neon branch, migrations `001`+`002`):
- `properties.embedding vector(1536)`, `embedding_text`, `embedding_status`, `embedding_synced_at`, `updated_at`
- `properties_embedding_hnsw` — HNSW cosine index (`m=16, ef_construction=64`)
- `users.taste_embedding`, `user_preferences`, `user_events` (+`session_id`), `search_logs`

---

## 3. Stage 1 — place normalization (our data is bilingual + two countries)

Unlike the reference (TRNC only), our data spans **North Cyprus and mainland Turkey** with
mixed spellings. `services/place_aliases.py` canonicalizes Turkish/variant spellings to the
English forms stored in our `city`/`district` columns: `Girne→Kyrenia`, `Lefkoşa→Nicosia`,
`Gazimağusa→Famagusta`, `Muğla→Mugla`, `Kaş→Kas`, etc. Because OpenAI embeddings are
multilingual and GPT handles Turkish natively, we **skip a separate translation model** —
aliasing + multilingual models cover it.

## 4. Stage 2 — GPT constraint extraction

`services/constraint_extractor.py` builds a system prompt injecting **our real values**
(`listing_type: rent|sale`, `property_type: Apartment|Villa|Penthouse`, and the live
distinct city/district list pulled from the DB and cached). GPT returns JSON; we **never
trust it directly** — `validate_filters()` re-checks every field (type, range, whitelist)
and drops anything invalid. On any failure we proceed with `{semantic_query}` only.

## 5. Stage 3 — candidate filtering + relaxation

`build_candidate_sql()` produces a parameterized query against `properties`:
`status='active'` always, plus `LOWER(listing_type)`, `price_normalized` range, `beds`
range, `city`, `district`, `property_type`. `LIMIT 200`. If fewer than `MIN_RESULTS` (10)
rows return, `_relax()` drops the least-critical constraint in order
(`property_type → district → max_price → min_price → city → beds → listing_type`) and retries.

## 6. Stage 4 — vector rerank

Candidates are reordered by `ORDER BY embedding <=> %s::vector` (cosine, HNSW-backed,
NULL embeddings last). Two entry points:
- **Main search page** (`/search`): reranks the already-filtered rows in place — zero UI
  change, silent fallback to keyword order.
- **Full pipeline** (`GET /api/ai-search`): runs all four stages and returns JSON
  (`mode: semantic|filter_only`), for the assistant / future UI.

Query embeddings are cached in-process; **listing embeddings are never generated at query
time** (that kills latency) — only in the async backfill.

---

## 7. Recommendation engine (`services/recommendations.py`)

Cold-start aware (we have only a handful of favorites):
- **New item** → `similar_properties(id)`: vector nearest-neighbours. No user data needed.
- **New user** → `recommend_for_user(uid)` Path 1: build a synthetic query document from
  `user_preferences` (onboarding), embed it, vector-search, post-filter by price/beds.
- **New system** → Path 2 popularity baseline: order by favorite count + `avg_rating`.
- **Behavioral (later)** → `update_taste_embedding(uid)` averages embeddings of
  favorited/viewed properties into `users.taste_embedding`.

Scoring formula for when behavioral data accrues:
`0.40·cosine + 0.30·favorite + 0.15·view(recency) + 0.10·feature_match + 0.05·rating`.

Endpoints: `GET /api/recommendations`, `GET /api/properties/{id}/similar`.

---

## 8. Implementation checklist

**Foundation — DONE**
- [x] pgvector/pg_trgm/unaccent on Neon branch
- [x] `embedding` column + HNSW index + `embedding_status`
- [x] `user_preferences`, `user_events`, `search_logs`
- [x] Extended TR+Turkey place-alias table
- [x] Provider isolated in `services/openai_client.py` (key-gated)

**Indexing — DONE (code), pending key to run**
- [x] Composite document builder
- [x] Batch backfill script (`scripts/backfill_embeddings.py`)
- [ ] **Run backfill once `OPENAI_API_KEY` is set**
- [x] Re-embed detection via `updated_at > embedding_synced_at`

**Search — DONE (code)**
- [x] Place normalization, GPT extraction + validation + fallback
- [x] Stage 3 filter builder + relaxation
- [x] Stage 4 rerank (both `/search` and `/api/ai-search`)
- [x] `search_logs` logging (feeds Pareto/fishbone)
- [x] Offline tests + rolled-back pgvector validation

**Recommendations — DONE (code)**
- [x] Similar listings, content-based, popularity baseline, taste vector
- [ ] Onboarding UI to populate `user_preferences` (frontend task)
- [ ] Instrument `user_events` view inserts (≥5s / >50% scroll) in frontend

**Validation & report**
- [x] Pipeline logs failures and search results
- [ ] Verify top-5 quality on 3–4 test queries (after backfill)
- [x] Architecture + deviations documented (this file + `docs/schema_comparison.md`)

---

## 9. Deviations from the reference guide (document these in the final report)
1. **Flat schema, not normalized** — embedding lives on `properties`, not `listings`; geo
   is free-text `city/district`, not `cities/districts/locations`.
2. **HNSW from the start** (reference's choice) instead of ivfflat — no training data needed.
3. **No separate translation model** — bilingual data + multilingual OpenAI models + place
   aliases make Stage 1 a lookup, not an API call.
4. **Two countries** (North Cyprus + Turkey) — place-alias table extended beyond TRNC.
5. **Main `/search` reranks in place**; the full GPT pipeline lives on `/api/ai-search` to
   avoid destabilizing the existing UI.
