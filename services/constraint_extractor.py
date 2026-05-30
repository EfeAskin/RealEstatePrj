"""Stage 2: natural-language query -> validated structured filter dict (via GPT).

Adapted from the reference guide to OUR real values:
  listing_type: rent | sale         (not RENT/SALE enums)
  property_type: Apartment | Villa | Penthouse (+ whatever exists in data)
  district/city: validated against the live distinct values in our properties.

GPT output is NEVER trusted directly — `validate_filters` re-checks every field.
"""
import threading
import time
from typing import Optional

from db.connection import get_db_connection
from services import openai_client

PRICE_MAX_PLAUSIBLE = 500_000_000   # TRY-scale ceiling; above this we ignore the value
VALID_CURRENCIES = {"USD", "EUR", "GBP", "TRY"}
DEFAULT_QUERY_CURRENCY = "USD"      # assumed when a price is given but no currency stated

_loc_cache = {"at": 0.0, "cities": set(), "districts": set(), "ptypes": set()}
_loc_lock = threading.Lock()
_LOC_TTL = 300  # seconds

# cache GPT extractions per normalized query (cuts latency + cost on repeats)
_extract_cache: dict = {}


def _refresh_known_values():
    """Cache distinct cities/districts/property_types from the DB (5-min TTL)."""
    now = time.time()
    if now - _loc_cache["at"] < _LOC_TTL and _loc_cache["cities"]:
        return
    with _loc_lock:
        if now - _loc_cache["at"] < _LOC_TTL and _loc_cache["cities"]:
            return
        conn = get_db_connection()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("SELECT DISTINCT city FROM properties WHERE city IS NOT NULL AND city <> ''")
            cities = {r[0] for r in cur.fetchall()}
            cur.execute("SELECT DISTINCT district FROM properties WHERE district IS NOT NULL AND district <> ''")
            districts = {r[0] for r in cur.fetchall()}
            cur.execute("SELECT DISTINCT property_type FROM properties WHERE property_type IS NOT NULL")
            ptypes = {r[0] for r in cur.fetchall()}
            cur.close()
            _loc_cache.update(at=now, cities=cities, districts=districts, ptypes=ptypes)
        except Exception as e:
            print(f"[constraint_extractor] known-values refresh failed: {e}")
        finally:
            conn.close()


def build_system_prompt() -> str:
    _refresh_known_values()
    cities = sorted(_loc_cache["cities"]) or ["Nicosia", "Kyrenia", "Famagusta"]
    ptypes = sorted(_loc_cache["ptypes"]) or ["Apartment", "Villa", "Penthouse"]
    return f"""You are a real estate query parser. Extract structured filters from the user query.
Return ONLY a valid JSON object. No explanation, no markdown.

Schema:
{{
  "listing_type": "rent" | "sale" | null,
  "property_type": one of {ptypes} or null,
  "min_price": number | null,
  "max_price": number | null,
  "min_beds": number | null,
  "max_beds": number | null,
  "city": one of {cities} or null,
  "district": string | null,
  "currency": "USD" | "EUR" | "GBP" | "TRY" | null,
  "semantic_query": string
}}

Rules:
- Use null for any field not mentioned.
- "cheap"/"affordable" -> leave price null unless a number is given.
- city/district must match one of the listed names (use English spelling) or be null.
- currency = the currency of the stated price (e.g. "500 USD" -> "USD"); null if no price.
- semantic_query = the full original query text, always present.
- Do NOT invent fields.
"""


def validate_filters(raw: dict, original_query: str) -> dict:
    """Deterministically sanitize GPT output. Invalid fields become null/ignored."""
    _refresh_known_values()
    f = {}

    lt = (raw.get("listing_type") or "").lower() if isinstance(raw.get("listing_type"), str) else None
    f["listing_type"] = lt if lt in ("rent", "sale") else None

    pt = raw.get("property_type")
    f["property_type"] = pt if pt in _loc_cache["ptypes"] else None

    for k in ("min_price", "max_price"):
        v = raw.get(k)
        f[k] = v if isinstance(v, (int, float)) and 0 <= v <= PRICE_MAX_PLAUSIBLE else None

    for k in ("min_beds", "max_beds"):
        v = raw.get(k)
        f[k] = int(v) if isinstance(v, (int, float)) and 0 <= v <= 20 else None

    city = raw.get("city")
    f["city"] = city if city in _loc_cache["cities"] else None

    dist = raw.get("district")
    f["district"] = dist if dist in _loc_cache["districts"] else None

    cur = (raw.get("currency") or "").upper() if isinstance(raw.get("currency"), str) else None
    if cur not in VALID_CURRENCIES:
        cur = None
    # if a price was given without a currency, assume the default base
    if cur is None and (f["min_price"] is not None or f["max_price"] is not None):
        cur = DEFAULT_QUERY_CURRENCY
    f["currency"] = cur

    sq = raw.get("semantic_query") or original_query
    f["semantic_query"] = sq if isinstance(sq, str) and sq.strip() else original_query
    return f


def extract(normalized_query: str) -> dict:
    """Run GPT extraction + validation (cached per query). On any failure, returns a
    filter dict with no hard constraints (just semantic_query) so search still works."""
    if normalized_query in _extract_cache:
        return _extract_cache[normalized_query]
    raw = openai_client.extract_constraints(normalized_query, build_system_prompt())
    if not raw:
        return {"semantic_query": normalized_query}
    try:
        result = validate_filters(raw, normalized_query)
    except Exception as e:
        print(f"[constraint_extractor] validation failed: {e}")
        result = {"semantic_query": normalized_query}
    _extract_cache[normalized_query] = result
    return result
