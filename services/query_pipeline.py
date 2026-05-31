"""The 4-stage semantic search pipeline (router-free, so no import cycles).

  Stage 1  normalize        place aliases (GPT handles TR->EN translation natively)
  Stage 2  extract          GPT -> validated hard-filter dict
  Stage 3  filter           SQL candidate set (+ constraint relaxation if too few)
  Stage 4  rerank           pgvector cosine on the candidate set

Graceful degradation: if AI is disabled/unavailable, Stage 2 yields no hard
filters and Stage 4 is skipped (rows come back in default order); the caller's
keyword path still works. Nothing here raises to the request.
"""
import json
import threading
from typing import List, Optional

import psycopg2.extras as _extras
from db.connection import get_db_connection
from services import ai_config, openai_client, constraint_extractor
from services import currency as currency_svc
from services.place_aliases import normalize_places


# Converts each listing's price_normalized (stored in its own currency) to USD inside
# one SQL CASE expression, so a budget can be compared across mixed GBP/TRY/EUR/USD rows.
_PRICE_USD_CASE = (
    "price_normalized * CASE UPPER(COALESCE(currency_code, currency, 'USD')) "
    "WHEN 'USD' THEN %s WHEN 'GBP' THEN %s WHEN 'EUR' THEN %s "
    "WHEN 'TRY' THEN %s ELSE %s END"
)


def _usd_rate_args(rates: dict) -> list:
    return [rates.get("USD", 1.0), rates.get("GBP", 1.27),
            rates.get("EUR", 1.08), rates.get("TRY", 0.031), 1.0]


# --------------------------------------------------------------- Stage 3 SQL

def build_candidate_sql(filters: dict):
    conditions = ["status = 'active'"]
    params: list = []
    if filters.get("listing_type"):
        conditions.append("LOWER(listing_type) = %s")
        params.append(filters["listing_type"])
    if filters.get("property_type"):
        conditions.append("property_type = %s")
        params.append(filters["property_type"])
    # Currency-aware price: convert both the row price and the budget to USD so a
    # "max 700 USD" means the same across GBP/TRY/EUR/USD listings (not a raw compare).
    if filters.get("min_price") is not None or filters.get("max_price") is not None:
        rates = currency_svc.get_usd_rates()
        rate_args = _usd_rate_args(rates)
        qcur = filters.get("currency") or "USD"
        if filters.get("min_price") is not None:
            conditions.append(f"({_PRICE_USD_CASE}) >= %s")
            params.extend(rate_args + [currency_svc.to_usd(filters["min_price"], qcur)])
        if filters.get("max_price") is not None:
            conditions.append(f"({_PRICE_USD_CASE}) <= %s")
            params.extend(rate_args + [currency_svc.to_usd(filters["max_price"], qcur)])
    if filters.get("min_beds") is not None:
        conditions.append("beds >= %s")
        params.append(filters["min_beds"])
    if filters.get("max_beds") is not None:
        conditions.append("beds <= %s")
        params.append(filters["max_beds"])
    # Location is free-text and lives in different columns across our flat schema
    # (a place asked for as a "district" may sit in city/location on matching rows).
    # Match the SAME place token across columns, case-insensitively, so we don't
    # silently drop valid listings. Still strict: exact value (no wildcards) for the
    # city/district columns; only `location` gets a contains-match.
    if filters.get("city"):
        conditions.append("(city ILIKE %s OR district ILIKE %s)")
        params.extend([filters["city"], filters["city"]])
    if filters.get("district"):
        conditions.append("(district ILIKE %s OR city ILIKE %s OR location ILIKE %s)")
        params.extend([filters["district"], filters["district"], f"%{filters['district']}%"])
    sql = (
        "SELECT id FROM properties WHERE "
        + " AND ".join(conditions)
        + f" LIMIT {ai_config.CANDIDATE_LIMIT}"
    )
    return sql, params


def semantic_candidate_ids(query_text: str, limit: int = 100) -> Optional[list]:
    """Vector recall: nearest active listings to the free-text query (place-normalized).

    Returns ordered ids, or None if AI is unavailable / query can't be embedded, so
    callers can fall back to keyword ILIKE. Empty list means no embedded listings.
    """
    if not ai_config.ai_enabled():
        return None
    vec = openai_client.embed_query(normalize_places(query_text or ""))
    if vec is None:
        return None
    conn = get_db_connection()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id FROM properties
            WHERE status = 'active' AND embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (openai_client.to_vector_literal(vec), limit),
        )
        return [r[0] for r in cur.fetchall()]
    except Exception as e:
        print(f"[query_pipeline] semantic_candidate_ids failed: {e}")
        return None
    finally:
        conn.close()


def _fetch_candidate_ids(filters: dict, cur) -> list:
    sql, params = build_candidate_sql(filters)
    cur.execute(sql, tuple(params))
    return [r[0] for r in cur.fetchall()]


def _relax(filters: dict) -> Optional[dict]:
    """Drop the least-critical constraint, in order, for a retry. None when exhausted."""
    order = ["property_type", "district", "max_price", "min_price", "city",
             "min_beds", "max_beds", "listing_type"]
    relaxed = dict(filters)
    for key in order:
        if relaxed.get(key) is not None:
            relaxed[key] = None
            return relaxed
    return None


# --------------------------------------------------------------- Stage 4 rerank

def build_hybrid_order_sql(qvec_literal: str, query_text: str):
    """Build the hybrid `ORDER BY` fragment (+ its params) used to rank results.

    Blends, with vector similarity DELIBERATELY dominant (so semantic search is
    not diluted): cosine similarity to the query embedding, full-text keyword
    overlap (ts_rank on name+description), avg_rating, and a mild recency boost.
    Weights live in ai_config (HYBRID_W_*). Rows with a NULL embedding produce a
    NULL score and sink via NULLS LAST — same as the old pure-cosine behavior.

    Returns (sql, params) where sql begins with " ORDER BY ..."; append both to a
    query whose remaining params come BEFORE the ORDER BY clause.
    """
    expr = (
        f"({ai_config.HYBRID_W_VECTOR} * (1 - (embedding <=> %s::vector)) "
        f"+ {ai_config.HYBRID_W_LEXICAL} * ts_rank("
        "to_tsvector('simple', coalesce(name,'') || ' ' || coalesce(description,'')), "
        "plainto_tsquery('simple', %s)) "
        f"+ {ai_config.HYBRID_W_RATING} * (COALESCE(avg_rating, 0) / 5.0) "
        f"+ {ai_config.HYBRID_W_RECENCY} * (1.0 / (1 + "
        "EXTRACT(EPOCH FROM (now()::timestamp - COALESCE(created_at, now()::timestamp))) / 86400.0)))"
    )
    return f" ORDER BY {expr} DESC NULLS LAST", [qvec_literal, query_text]


def rerank_ids(query_vec: List[float], candidate_ids: list, cur, top_k: int,
               query_text: str = "") -> list:
    """Order candidate ids by the hybrid score (vector-dominant; NULL embeddings last)."""
    if not candidate_ids:
        return []
    lit = openai_client.to_vector_literal(query_vec)
    order_sql, order_params = build_hybrid_order_sql(lit, query_text or "")
    cur.execute(
        f"SELECT id FROM properties WHERE id = ANY(%s){order_sql} LIMIT %s",
        [candidate_ids, *order_params, top_k],
    )
    return [r[0] for r in cur.fetchall()]


# --------------------------------------------------------------- logging

def log_search(query_text: str, filters: dict, result_count: int, user_id=None):
    """Fire-and-forget: logging must never add latency to the user's search response."""
    def _do():
        conn = get_db_connection()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO search_logs (user_id, query_text, filters_json, result_count) "
                "VALUES (%s, %s, %s, %s)",
                (user_id, query_text, json.dumps(filters, default=str), result_count),
            )
            conn.commit()
            cur.close()
        except Exception as e:
            print(f"[query_pipeline] log_search failed: {e}")
            if conn:
                conn.rollback()
        finally:
            conn.close()

    threading.Thread(target=_do, daemon=True).start()


# --------------------------------------------------------------- entrypoints

# Concrete hard-filter keys (a query that set any of these is "specific", so the
# relevance floor is skipped — we honor the user's filters + the relaxation path).
_HARD_FILTER_KEYS = ("listing_type", "property_type", "min_price", "max_price",
                     "min_beds", "max_beds", "city", "district")


def has_hard_filters(filters: dict) -> bool:
    """True if the query carried any concrete (non-semantic) constraint."""
    return any((filters or {}).get(k) not in (None, "") for k in _HARD_FILTER_KEYS)


def is_off_topic(query: str, has_filters: bool) -> bool:
    """Relevance gate: True only when a PURELY semantic query (no hard filters) is
    judged unanswerable by our catalog ('castle', 'spaceship').

    A cosine floor can't do this — short legit queries ('pool', 'sea view') score as
    low as nonsense — so we ask the LLM to judge intent instead. Fail-OPEN: any
    uncertainty (gate off, filters present, model unavailable) returns False, i.e.
    keep results, so we never wrongly hide listings.
    """
    if not ai_config.RELEVANCE_GATE or has_filters:
        return False
    return openai_client.is_answerable(query) is False


def summarize_for_rerank(r: dict) -> str:
    """One compact line per listing for the LLM reranker: title + key specs."""
    name = (r.get("name") or "Listing").strip()[:70]
    meta = []
    for key in ("property_type", "listing_type", "room_count"):
        if r.get(key):
            meta.append(str(r[key]))
    loc = ", ".join(b for b in [r.get("district"), r.get("city")] if b)
    if loc:
        meta.append(loc)
    if r.get("net_m2"):
        meta.append(f"{r['net_m2']}m2")
    if r.get("price_normalized"):
        meta.append(f"{r['price_normalized']} {r.get('currency_code') or r.get('currency') or ''}".strip())
    return name + (" — " + " | ".join(meta) if meta else "")


def llm_rerank_rows(query: str, rows: list) -> list:
    """Stage 5: reorder the top-N hybrid hits with one GPT call (fails soft to input).

    Only the top LLM_RERANK_TOP_N are handed to the model; the tail keeps its hybrid
    order. Returns a new list; on any failure returns `rows` unchanged.
    """
    if not (ai_config.ai_enabled() and ai_config.LLM_RERANK) or len(rows) < 2:
        return rows
    n = ai_config.LLM_RERANK_TOP_N
    head = rows[:n]
    items = [{"id": r["id"], "text": summarize_for_rerank(r)} for r in head]
    new_order = openai_client.rerank_results(query, items)
    if not new_order:
        return rows
    by_id = {r["id"]: r for r in head}
    return [by_id[i] for i in new_order if i in by_id] + rows[n:]


def semantic_search(query: str, top_k: int = None, user_id=None,
                    min_results: int = None) -> dict:
    """Full pipeline. Returns {'results', 'filters', 'mode', 'relaxed', 'dropped'}.

    `mode` is 'semantic' when vector rerank ran, else 'filter_only' (graceful fallback).
    `filters` is the set of hard filters ACTUALLY applied (post-relaxation), so callers
    never claim a constraint held when it was dropped to find results. `dropped` lists
    constraints we had to relax; `relaxed` is True when any were dropped.

    `min_results` controls how hard we pad: the loop relaxes constraints until at least
    this many candidates exist. Defaults to ai_config.MIN_RESULTS; the chat assistant
    passes a small value so it only broadens when nothing at all matched.
    """
    top_k = top_k or ai_config.DEFAULT_TOP_K
    min_results = ai_config.MIN_RESULTS if min_results is None else min_results
    normalized = normalize_places(query or "")

    # Stage 2 (no-op without a key -> filters = {semantic_query})
    filters = constraint_extractor.extract(normalized) if ai_config.ai_enabled() \
        else {"semantic_query": normalized}

    conn = get_db_connection()
    if not conn:
        return {"results": [], "filters": filters, "mode": "error",
                "relaxed": False, "dropped": []}

    try:
        cur = conn.cursor()

        # Stage 3 + relaxation
        ids = _fetch_candidate_ids(filters, cur)
        working = dict(filters)
        while len(ids) < min_results:
            relaxed = _relax(working)
            if relaxed is None:
                break
            working = relaxed
            ids = _fetch_candidate_ids(working, cur)

        # Which hard constraints did we have to give up to find results?
        dropped = [k for k, v in filters.items()
                   if k != "semantic_query" and v not in (None, "")
                   and working.get(k) in (None, "")]

        # Stage 4: vector rerank (only if we can embed the query)
        mode = "filter_only"
        ordered_ids = ids[:top_k]
        query_vec = openai_client.embed_query(filters.get("semantic_query", normalized)) \
            if ai_config.ai_enabled() else None
        if query_vec is not None and ids:
            reranked = rerank_ids(query_vec, ids, cur, top_k,
                                  filters.get("semantic_query", normalized))
            if reranked:
                ordered_ids = reranked
                mode = "semantic"

        # Relevance gate: a filter-less query our catalog can't answer ("castle",
        # "spaceship") returns empty instead of nearest-neighbor junk.
        if mode == "semantic" and is_off_topic(query, has_hard_filters(filters)):
            ordered_ids = []

        results = _fetch_rows_in_order(ordered_ids, cur)
        # Stage 5: LLM precision rerank of the top hits (only when vector search ran).
        if mode == "semantic":
            results = llm_rerank_rows(query, results)
        cur.close()
    except Exception as e:
        print(f"[query_pipeline] semantic_search failed: {e}")
        conn.close()
        return {"results": [], "filters": filters, "mode": "error",
                "relaxed": False, "dropped": []}
    finally:
        if not conn.closed:
            conn.close()

    log_search(query, working, len(results), user_id)
    return {"results": results, "filters": working, "mode": mode,
            "relaxed": bool(dropped), "dropped": dropped}


def _fetch_rows_in_order(ids: list, cur) -> list:
    if not ids:
        return []
    cur2 = cur.connection.cursor(cursor_factory=_extras.RealDictCursor)
    cur2.execute("SELECT * FROM properties WHERE id = ANY(%s)", (ids,))
    by_id = {row["id"]: dict(row) for row in cur2.fetchall()}
    cur2.close()
    return [by_id[i] for i in ids if i in by_id]
