"""Stage 1 helper: place-name normalization.

The reference guide assumed TRNC-only place names. OUR data spans BOTH North
Cyprus and mainland Turkey, with Turkish and English spellings mixed. This map
canonicalizes Turkish/variant spellings to the English forms actually stored in
our `properties` city/district columns, so a query in either language matches.

It is intentionally a plain dict + string replace (cheap, deterministic, no API).
"""

# Turkish / variant spelling  ->  canonical English form used in our data.
PLACE_ALIASES = {
    # --- North Cyprus cities ---
    "lefkoşa": "Nicosia",
    "lefkosa": "Nicosia",
    "girne": "Kyrenia",
    "gazimağusa": "Famagusta",
    "gazimagusa": "Famagusta",
    "mağusa": "Famagusta",
    "magusa": "Famagusta",
    "iskele": "Trikomo",
    "i̇skele": "Trikomo",
    "lefke": "Lefka",
    # --- North Cyprus districts / areas (kept as-is where already canonical) ---
    "karakum": "Karakum",
    "çatalköy": "Catalkoy",
    "catalkoy": "Catalkoy",
    "esentepe": "Esentepe",
    "alsancak": "Alsancak",
    "zeytinlik": "Zeytinlik",
    "ortaköy": "Ortakoy Nicosia",
    "küçük kaymaklı": "Kucuk Kaymakli",
    "kucuk kaymakli": "Kucuk Kaymakli",
    # --- Mainland Turkey cities (our data also has these) ---
    "muğla": "Mugla",
    "mugla": "Mugla",
    "antalya": "Antalya",
    "bodrum": "Bodrum",
    "fethiye": "Fethiye",
    "kaş": "Kas",
}


def normalize_places(query: str) -> str:
    """Replace known Turkish/variant place spellings with canonical English forms.

    Case-insensitive on the alias key; preserves the rest of the query untouched.
    """
    if not query:
        return query
    out = query
    low = query.lower()
    for tr, en in PLACE_ALIASES.items():
        if tr in low:
            # rebuild against the lowercased index to catch any-case occurrences
            idx = low.find(tr)
            while idx != -1:
                out = out[:idx] + en + out[idx + len(tr):]
                low = out.lower()
                idx = low.find(tr, idx + len(en))
    return out
