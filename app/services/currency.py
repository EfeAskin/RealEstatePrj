"""Live currency conversion for price filtering — cached so it never adds per-search lag.

Prices in `properties` are stored in mixed currencies (GBP/TRY/EUR/USD). To make a
price range meaningful we convert each listing to a common base (USD) inside a single
SQL CASE expression, using rates fetched live and cached in-process.

Rates change constantly in Cyprus, so we fetch fresh (open.er-api.com, no key) but only
when the cache is older than TTL. A network failure falls back to recent approximate
rates — search must never break on FX.
"""
import json
import threading
import time
import urllib.request

_RATES_URL = "https://open.er-api.com/v6/latest/USD"   # rates = units per 1 USD
_TTL = 6 * 3600  # refresh at most every 6 hours
_lock = threading.Lock()
_cache = {"at": 0.0, "usd_per_unit": {}}

# Fallback only if the live fetch fails (resilience, not the primary path).
_FALLBACK_USD_PER_UNIT = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27, "TRY": 0.031}

SUPPORTED = ("USD", "EUR", "GBP", "TRY")


def _fetch() -> dict:
    """Return {currency: USD value of 1 unit}. Network call; caller handles caching."""
    with urllib.request.urlopen(_RATES_URL, timeout=5) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    rates = data.get("rates") or {}
    # API gives units-per-USD; we want USD-per-unit = 1/rate.
    out = {}
    for cur in SUPPORTED:
        r = rates.get(cur)
        out[cur] = (1.0 / r) if r else _FALLBACK_USD_PER_UNIT[cur]
    return out


def get_usd_rates() -> dict:
    """Cached {currency: USD-per-unit}. Refreshes after TTL; falls back on failure."""
    now = time.time()
    if _cache["usd_per_unit"] and now - _cache["at"] < _TTL:
        return _cache["usd_per_unit"]
    with _lock:
        if _cache["usd_per_unit"] and now - _cache["at"] < _TTL:
            return _cache["usd_per_unit"]
        try:
            rates = _fetch()
            _cache.update(at=now, usd_per_unit=rates)
        except Exception as e:
            print(f"[currency] live fetch failed, using fallback: {e}")
            if not _cache["usd_per_unit"]:
                _cache.update(at=now, usd_per_unit=dict(_FALLBACK_USD_PER_UNIT))
        return _cache["usd_per_unit"]


def to_usd(amount: float, currency: str) -> float:
    """Convert an amount in `currency` to USD using cached rates."""
    rates = get_usd_rates()
    return float(amount) * rates.get((currency or "USD").upper(), 1.0)
