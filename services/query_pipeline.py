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
    if filters.get("city"):
        conditions.append("city = %s")
        params.append(filters["city"])
    if filters.get("district"):
        conditions.append("district = %s")
        params.append(filters["district"])
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

def rerank_ids(query_vec: List[float], candidate_ids: list, cur, top_k: int) -> list:
    """Order candidate ids by cosine distance to the query vector (NULL embeddings last)."""
    if not candidate_ids:
        return []
    lit = openai_client.to_vector_literal(query_vec)
    cur.execute(
        """
        SELECT id FROM properties
        WHERE id = ANY(%s)
        ORDER BY embedding <=> %s::vector
        LIMIT %s
        """,
        (candidate_ids, lit, top_k),
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
            reranked = rerank_ids(query_vec, ids, cur, top_k)
            if reranked:
                ordered_ids = reranked
                mode = "semantic"

        results = _fetch_rows_in_order(ordered_ids, cur)
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
