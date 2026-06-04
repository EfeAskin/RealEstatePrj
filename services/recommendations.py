"""Recommendation engine (content-based first, behavioral-ready).

Cold-start strategy from the reference guide, adapted to our flat schema:
  - New item  -> 'similar listings' via vector nearest-neighbour (no user data needed).
  - New user  -> synthetic query document from user_preferences (onboarding).
  - New system-> popularity baseline (favorites count + avg_rating) when nothing else.

Behavioral scoring formula (used once user_events/favorites accumulate):
  score = 0.40*cosine + 0.30*favorite + 0.15*view(recency) + 0.10*feature + 0.05*rating
"""
from typing import Optional

import psycopg2.extras as _extras
from db.connection import get_db_connection
from services import ai_config, openai_client
from services.document_builder import build_document, get_feature_names

_LISTING_LABEL = {"rent": "for rent", "sale": "for sale"}


# ----------------------------------------------------- similar listings (new item)

def similar_properties(property_id, top_k: int = 8) -> list:
    """Vector nearest-neighbours to a given property. Falls back to [] if no embeddings."""
    conn = get_db_connection()
    if not conn:
        return []
    try:
        cur = conn.cursor(cursor_factory=_extras.RealDictCursor)
        cur.execute(
            """
            SELECT id FROM properties
            WHERE status = 'active' AND id <> %s AND embedding IS NOT NULL
              AND embedding <=> (SELECT embedding FROM properties WHERE id = %s) IS NOT NULL
            ORDER BY embedding <=> (SELECT embedding FROM properties WHERE id = %s)
            LIMIT %s
            """,
            (property_id, property_id, property_id, top_k),
        )
        ids = [r["id"] for r in cur.fetchall()]
        rows = _fetch_rows(ids, cur) if ids else []
        cur.close()
        return rows
    except Exception as e:
        print(f"[recommendations] similar_properties failed: {e}")
        return []
    finally:
        conn.close()


# --------------------------------------------------- preference document (new user)

def build_preference_document(prefs: dict) -> str:
    """Turn a user_preferences row into a synthetic query string to embed."""
    bits = []
    lt = _LISTING_LABEL.get(str(prefs.get("listing_type") or "").lower())
    if prefs.get("property_type"):
        bits.append(str(prefs["property_type"]))
    if lt:
        bits.append(lt)
    where = ", ".join(b for b in [prefs.get("preferred_district"), prefs.get("preferred_city")] if b)
    if where:
        bits.append("in " + where)
    if prefs.get("min_beds") or prefs.get("max_beds"):
        lo = prefs.get("min_beds") or ""
        hi = prefs.get("max_beds") or ""
        bits.append(f"{lo}-{hi} bedrooms".strip("-"))
    if prefs.get("max_price"):
        bits.append(f"up to {prefs['max_price']}")
    if prefs.get("furnished"):
        bits.append(str(prefs["furnished"]))
    return ", ".join(bits)


def recommend_for_user(user_id, top_k: int = 10) -> dict:
    """Content-based recommendations. Returns {'results': [...], 'basis': <how>}."""
    conn = get_db_connection()
    if not conn:
        return {"results": [], "basis": "error"}
    try:
        cur = conn.cursor(cursor_factory=_extras.RealDictCursor)
        cur.execute("SELECT * FROM user_preferences WHERE user_id = %s", (user_id,))
        prefs = cur.fetchone()

        # Path 1: preferences + embeddings -> synthetic-query vector search
        if prefs and ai_config.ai_enabled():
            doc = build_preference_document(dict(prefs))
            vec = openai_client.embed_query(doc) if doc else None
            if vec is not None:
                lit = openai_client.to_vector_literal(vec)
                conds, params = ["status = 'active'", "embedding IS NOT NULL"], []
                if prefs.get("max_price"):
                    conds.append("price_normalized <= %s"); params.append(prefs["max_price"])
                if prefs.get("min_beds"):
                    conds.append("beds >= %s"); params.append(prefs["min_beds"])
                sql = ("SELECT id FROM properties WHERE " + " AND ".join(conds)
                       + f" ORDER BY embedding <=> '{lit}'::vector LIMIT %s")
                cur.execute(sql, tuple(params) + (top_k,))
                ids = [r["id"] for r in cur.fetchall()]
                rows = _fetch_rows(ids, cur)
                cur.close()
                return {"results": rows, "basis": "preferences"}

        # Path 2: popularity baseline (favorites count + rating) — true cold start
        cur.execute(
            """
            SELECT p.*, COUNT(uf.id) AS fav_count
            FROM properties p
            LEFT JOIN user_favorites uf ON uf.property_id = p.id
            WHERE p.status = 'active'
            GROUP BY p.id
            ORDER BY fav_count DESC, COALESCE(p.avg_rating, 0) DESC, p.id DESC
            LIMIT %s
            """,
            (top_k,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return {"results": rows, "basis": "popularity"}
    except Exception as e:
        print(f"[recommendations] recommend_for_user failed: {e}")
        return {"results": [], "basis": "error"}
    finally:
        conn.close()


# --------------------------------------------------- taste embedding (behavioral)

def update_taste_embedding(user_id) -> bool:
    """Recompute a user's taste vector as the mean of embeddings of properties they
    favorited or viewed, and store it on users.taste_embedding. Needs AI enabled."""
    if not ai_config.ai_enabled():
        return False
    conn = get_db_connection()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT p.id FROM properties p
            WHERE p.embedding IS NOT NULL AND (
                p.id IN (SELECT property_id FROM user_favorites WHERE user_id = %s)
                OR p.id IN (SELECT property_id FROM user_events
                            WHERE user_id = %s AND event_type = 'view')
            )
            """,
            (user_id, user_id),
        )
        ids = [r[0] for r in cur.fetchall()]
        if not ids:
            cur.close()
            return False
        # average the vectors in SQL via avg over unnest is awkward; do it numerically
        cur.execute("SELECT embedding FROM properties WHERE id = ANY(%s)", (ids,))
        vecs = [_parse_vector(r[0]) for r in cur.fetchall() if r[0] is not None]
        if not vecs:
            cur.close()
            return False
        dim = len(vecs[0])
        mean = [sum(v[i] for v in vecs) / len(vecs) for i in range(dim)]
        lit = openai_client.to_vector_literal(mean)
        cur.execute(
            "UPDATE users SET taste_embedding = %s::vector, taste_updated_at = now() WHERE id = %s",
            (lit, user_id),
        )
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print(f"[recommendations] update_taste_embedding failed: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        conn.close()


# ---------------------------------------------------------------- helpers

def _fetch_rows(ids: list, cur) -> list:
    if not ids:
        return []
    cur.execute("SELECT * FROM properties WHERE id = ANY(%s)", (ids,))
    by_id = {r["id"]: dict(r) for r in cur.fetchall()}
    return [by_id[i] for i in ids if i in by_id]


def _parse_vector(raw) -> Optional[list]:
    """pgvector returns the column as a '[1,2,3]' string."""
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        return list(raw)
    s = str(raw).strip().lstrip("[").rstrip("]")
    return [float(x) for x in s.split(",")] if s else None
