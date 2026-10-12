# AI Semantic Search — How It Works

A reading guide to the AI search/recommendation layer in CypInvEst. Covers the
data model, the indexing (offline) path, the query (online) pipeline, and how
everything degrades gracefully when OpenAI is off.

---

## 1. The big idea

Classic keyword search (`WHERE description ILIKE '%sea view%'`) only matches
exact substrings. It can't tell that **"3 bedrooms in Kyrenia"** and
**"3+1 daire Girne"** mean the same thing, and it can't rank by *meaning*.

This system layers **semantic search** on top of the existing keyword filter:

1. Every property is turned into a descriptive sentence and converted to a
   1536-dimension **embedding vector** (a point in "meaning space"). Stored once,
   offline.
2. At query time, the user's free-text question is converted to a vector the same
   way, and we find the listings whose vectors are **closest** (cosine distance)
   — i.e. closest in meaning, not in spelling.
3. GPT also parses the question into **hard filters** (price, beds, city, sale/rent)
   so semantic recall is combined with exact constraints.

Crucially, **the whole thing is optional**. If `OPENAI_API_KEY` is missing or the
SDK won't import, every AI function returns `None`/`[]` and the search falls back
to plain keyword `ILIKE`. Nothing in the AI layer ever raises into a request.

---

## 2. Where the code lives

| File | Role |
|------|------|
| `app/services/ai_config.py` | Central config + `ai_enabled()` master switch. Imports no SDK, always safe. |
| `app/services/openai_client.py` | **The only file that talks to OpenAI.** Embeddings, GPT extraction, relevance gate, LLM rerank. Every function fails soft. |
| `app/services/place_aliases.py` | Stage 1 — Turkish→English place normalization (girne→Kyrenia). Plain dict, no API. |
| `app/services/constraint_extractor.py` | Stage 2 — GPT turns the query into a validated hard-filter dict. |
| `app/services/query_pipeline.py` | Stages 3–5 — SQL candidate filter, constraint relaxation, vector rerank, relevance gate, LLM rerank. The orchestrator. |
| `app/services/document_builder.py` | Index-time — builds the text string that gets embedded per property. |
| `app/services/currency.py` | Live, cached FX rates so price filters work across mixed GBP/TRY/EUR/USD. |
| `app/services/recommendations.py` | "Similar listings" + "recommended for you" (content-based). |
| `app/routers/property_filter.py` | Wires the pipeline into the existing `/search` HTML page. |
| `app/routers/ai_search.py` | Exposes the pipeline as JSON: `/api/ai-search`, `/api/recommendations`, `/api/properties/{id}/similar`. |
| `scripts/backfill_embeddings.py` | Offline job that generates/refreshes the vectors. |
| `scripts/migrations/00{1,2}_*.sql` | Schema: `pgvector` extension, `embedding vector(1536)` column, HNSW index. |

---

## 3. The data model (Postgres + pgvector)

On the Neon AI branch, the flat `properties` table was extended (migration `001`):

```sql
CREATE EXTENSION IF NOT EXISTS vector;     -- pgvector
ALTER TABLE properties
  ADD COLUMN embedding           vector(1536),  -- the meaning vector
  ADD COLUMN embedding_text      text,          -- exact source string we embedded
  ADD COLUMN embedding_synced_at timestamptz;   -- NULL = needs (re)embedding
-- plus embedding_status ('done'/'failed') used by the backfill job
```

The vector index is **HNSW** with cosine ops (migration `002`):

```sql
CREATE INDEX properties_embedding_hnsw
    ON properties USING hnsw (embedding vector_cosine_ops);
```

HNSW (Hierarchical Navigable Small World) is an approximate-nearest-neighbour
index — it makes `ORDER BY embedding <=> query` fast even over many rows. The
`<=>` operator is pgvector's **cosine distance** (0 = identical meaning).

> Why 1536? That's the output dimension of OpenAI `text-embedding-3-small`. The
> column width and the model **must** match, or inserts fail.

---

## 4. Indexing path (offline — done once, refreshed on change)

Run by `scripts/backfill_embeddings.py` (needs `OPENAI_API_KEY`):

```
properties row ──► document_builder.build_document() ──► one descriptive sentence
                                                              │
                                              openai_client.embed_texts() (batched 100)
                                                              │
                                          UPDATE properties SET embedding = …::vector
```

**The key trick is in `document_builder.py`:** we do **not** embed only the
free-text `description`. We fold the structured columns *and* the (bilingual)
feature names into one sentence, e.g.:

> *"Sea-view apartment. Apartment for sale. Location: Karakum, Kyrenia, North
> Cyprus. 3+1, 3 bedrooms, 2 bathrooms. 120 m2 net. Features: Balcony, Deniz
> Manzarası. ..."*

That's why a 3-bedroom query matches a `room_count = '3+1'` row even though the
words differ — the bedroom count is spelled out in the embedded text.

The job is **idempotent and resumable**: a row "needs embedding" when its
`embedding IS NULL`, status isn't `done`, or `updated_at > embedding_synced_at`
(i.e. it changed since last embedded). `--all` forces a full re-embed.

---

## 5. Query path (online — the 4/5-stage pipeline)

This is the heart of it. Source: `app/services/query_pipeline.py` (the JSON
`semantic_search()` entrypoint) and `app/routers/property_filter.py` (the same logic
inlined into the `/search` HTML page). The stages:

```
 user free-text query: "cheap 2+1 flat with sea view in Girne under 150k USD"
        │
 [1] normalize_places()      girne → Kyrenia   (cheap, deterministic, no API)
        │
 [2] constraint_extractor.extract()   GPT → {listing_type, property_type,
        │                                    min/max_price, beds, city, district,
        │                                    currency, semantic_query}
        │                              ...then validate_filters() re-checks EVERY
        │                              field against live DB values (GPT is never trusted)
        │
 [3] build_candidate_sql()    SELECT id FROM properties
        │                     WHERE status='active' AND <hard filters>  LIMIT 200
        │                     ── if < MIN_RESULTS rows, _relax() drops the
        │                        least-critical filter and retries
        │
 [4] vector rerank            embed the query → ORDER BY hybrid score over the
        │                     candidate set (cosine DOMINANT + lexical + rating + recency)
        │
 [4.5] relevance gate         is_off_topic()? ("castle", "spaceship") → return EMPTY
        │
 [5] llm_rerank_rows()        GPT reorders the top-N for precision (optional, fails soft)
        │
     final ordered listings
```

### Stage 1 — Place normalization (`place_aliases.py`)
A plain dict maps Turkish/variant spellings to the canonical English forms stored
in our data: `girne→Kyrenia`, `lefkoşa→Nicosia`, `gazimağusa→Famagusta`, etc.
Deterministic string replace — no API call, no latency.

### Stage 2 — Constraint extraction (`constraint_extractor.py`)
GPT (`gpt-4o-mini`, `temperature=0`, JSON mode) parses the query into a structured
filter dict. The system prompt is **built dynamically** from the live distinct
`city` / `district` / `property_type` values in the DB (cached 5 min), so GPT can
only pick real values.

**GPT output is never trusted directly.** `validate_filters()` re-checks every
field: `listing_type` must be `rent`/`sale`; city/district must exist in the DB;
prices must be `0 ≤ x ≤ 500M`; beds `0–20`; currency in the allowed set. Anything
invalid becomes `null`. On any failure the function returns just
`{semantic_query: ...}` (no hard filters) so search still works.

Extractions are cached per normalized query to cut latency and cost on repeats.

### Stage 3 — Candidate filter + relaxation (`query_pipeline.py`)
The validated filters become a real SQL `WHERE` clause (`build_candidate_sql`),
capped at `CANDIDATE_LIMIT` (200). Two subtleties:

- **Currency-aware price.** Prices are stored in mixed currencies. A single SQL
  `CASE` expression converts each row's `price_normalized` to USD using live
  cached FX rates (`currency.py`), so "under 150k USD" means the same across a
  GBP, TRY, EUR or USD listing.
- **Flat-schema geography.** A place asked for as a "district" might live in the
  `city` or `location` column on otherwise-matching rows, so each place token is
  matched across columns (`district ILIKE … OR city ILIKE … OR location ILIKE …`).

If the filtered set has fewer than `MIN_RESULTS` (10) rows, `_relax()` drops the
**least-critical** constraint (order: property_type → district → max_price →
min_price → city → beds → listing_type) and retries, until enough rows exist or
constraints are exhausted. The pipeline reports which constraints it `dropped`, so
the UI can honestly say *"I couldn't find any under that budget, but here are the
closest matches."*

### Stage 4 — Hybrid vector rerank (`build_hybrid_order_sql`)
The query is embedded and the candidate set is ordered by a **blended score**,
with vector similarity deliberately dominant so semantic relevance isn't diluted
(weights in `ai_config.py`):

```
score = 0.70 · cosine_similarity(embedding, query_vec)   -- meaning  (DOMINANT)
      + 0.15 · ts_rank(name + description, query)         -- keyword overlap
      + 0.10 · avg_rating / 5                             -- quality
      + 0.05 · recency_boost(created_at)                  -- freshness
ORDER BY score DESC NULLS LAST
```

Rows with no embedding score `NULL` and sink to the bottom (`NULLS LAST`) — same
behaviour as the old pure-cosine ranking. In `/search` this `ORDER BY` is
**embedded into the one main SQL query** (no separate rerank round-trip) and is
only used when there's a free-text query, AI is on, and the user didn't pick an
explicit sort (price high/low, oldest).

### Stage 4.5 — Relevance gate (`is_off_topic` / `is_answerable`)
Vector search **always** returns the nearest rows — even for nonsense. Ask for a
"castle with a private beach" and you'd get the nearest apartments back, which
looks broken. A cosine *threshold* can't fix this: legit short queries ("pool",
"sea view") score as low as nonsense.

So for a **purely semantic query (no hard filters)** we ask GPT a yes/no question:
*could our residential catalog plausibly satisfy this?* If no, return **empty**
instead of junk. It's **fail-open**: any uncertainty (gate disabled, filters
present, model unavailable) keeps the results — we never wrongly hide listings.
A place/type GPT parsed out of the query does **not** bypass the gate, so
"fortress in Famagusta" can't smuggle an off-topic query past it via a city filter.

### Stage 5 — LLM precision rerank (`llm_rerank_rows`)
Optional final pass (toggle `LLM_RERANK`). The top-N hybrid hits (compact
"title + key specs" summaries) are handed to GPT, which returns them reordered
most→least relevant — a cross-encoder-style precision boost. It's **grounded**:
GPT only reorders ids we gave it, it can't invent listings. Costs one extra GPT
call; fails soft to the hybrid order.

---

## 6. Recommendations (`recommendations.py`)

Built on the same embeddings, three cold-start strategies:

- **Similar listings** (`/api/properties/{id}/similar`) — pure vector
  nearest-neighbour to one property's embedding. Needs no user data, so it works
  for brand-new items.
- **Recommended for you** (`/api/recommendations`) — if the user has
  `user_preferences`, build a synthetic query string from them, embed it, and do a
  vector search (with their price/beds as hard filters).
- **Popularity baseline** — true cold start (no prefs): order by favourite count +
  `avg_rating`.

There's also `update_taste_embedding()`: averages the embeddings of properties a
user favourited/viewed into a per-user `taste_embedding` vector — behavioural recs,
ready for when engagement data accumulates.

---

## 7. Graceful degradation — the safety net

`ai_config.ai_enabled()` returns `True` only when the key is present **and** the
`openai` SDK imports. Every call site checks it. When AI is off:

- Stage 2 yields no hard filters → keyword `ILIKE` path in `/search` runs instead.
- Stage 4 vector rerank is skipped → rows come back in default order (newest first).
- Recommendations fall back to the popularity baseline.

And independently, every `openai_client` function wraps its API call in
`try/except` returning `None`/`[]` on failure. **No AI failure ever breaks a
search or raises into a request.**

---

## 8. Configuration knobs (`ai_config.py` / `.env`)

| Setting | Default | What it does |
|---------|---------|--------------|
| `OPENAI_API_KEY` | — | Master switch. Absent = keyword-only mode. |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Must produce 1536-dim vectors. |
| `CHAT_MODEL` | `gpt-4o-mini` | Constraint extractor, relevance gate, rerank. |
| `CANDIDATE_LIMIT` | 200 | Max rows considered before vector rerank. |
| `MIN_RESULTS` | 10 | Below this, Stage 3 relaxes constraints. |
| `DEFAULT_TOP_K` | 20 | Results returned. |
| `HYBRID_W_VECTOR/LEXICAL/RATING/RECENCY` | 0.70 / 0.15 / 0.10 / 0.05 | Stage 4 ranking weights. |
| `LLM_RERANK` | on | Toggle the Stage 5 GPT precision rerank. |
| `RELEVANCE_GATE` | on | Toggle the off-topic rejection. |

---

## 9. How to run / test it

```powershell
# 1. Apply the AI schema (once, against the Neon AI branch DATABASE_URL)
./venv/Scripts/python.exe scripts/run_migration.py scripts/migrations/001_ai_foundation.sql
./venv/Scripts/python.exe scripts/run_migration.py scripts/migrations/002_adopt_reference_best_practices.sql

# 2. Generate the embeddings (needs OPENAI_API_KEY)
./venv/Scripts/python.exe scripts/backfill_embeddings.py          # --all to force re-embed

# 3. Validate pgvector end-to-end WITHOUT OpenAI (rolled back, writes nothing)
./venv/Scripts/python.exe scripts/validate_pgvector.py

# 4. Offline AI logic tests (no DB / network / key needed)
./venv/Scripts/python.exe tests/test_ai_offline.py

# 5. Try it live
#   HTML:  GET /search?q=cheap 2+1 with sea view in Girne under 150k USD
#   JSON:  GET /api/ai-search?q=...
#          GET /api/properties/123/similar
#          GET /api/recommendations   (login required)
```

---

## 10. One-paragraph summary

Each property is described as a sentence (structured fields + bilingual features),
embedded once into a 1536-dim pgvector column with an HNSW cosine index. At query
time the free-text question is place-normalized, parsed by GPT into validated hard
filters (currency-aware price, beds, city, sale/rent), used to build a SQL
candidate set that auto-relaxes if too narrow, then ranked by a hybrid score where
vector cosine similarity dominates over keyword overlap, rating and recency. A GPT
relevance gate drops genuinely off-topic queries, and an optional GPT rerank
sharpens the top results. Every AI step fails soft, so with no API key the whole
thing quietly becomes ordinary keyword search.
