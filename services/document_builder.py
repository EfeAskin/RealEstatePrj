"""Builds the composite text document that gets embedded for each property.

Per the reference guide's key insight: do NOT embed only `description` — fold in
the structured columns and the (bilingual) feature names so that "3 bedrooms in
Kyrenia" matches "3+1 daire Girne". Adapted to our FLAT `properties` schema
(no listings/locations/districts joins).
"""
from typing import Optional
from db.connection import get_db_connection
from psycopg2.extras import RealDictCursor

_LISTING_LABEL = {
    "sale": "for sale", "satılık": "for sale", "satilik": "for sale",
    "rent": "for rent", "kiralık": "for rent", "kiralik": "for rent",
}


def get_feature_names(property_id, conn=None) -> list:
    """Fetch this property's feature names (e.g. 'Balcony', 'Deniz Manzarası')."""
    own_conn = conn is None
    conn = conn or get_db_connection()
    if not conn:
        return []
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT f.name FROM features f
            JOIN property_features pf ON f.id = pf.feature_id
            WHERE pf.property_id = %s
            """,
            (property_id,),
        )
        names = [r["name"] for r in cur.fetchall()]
        cur.close()
        return names
    except Exception as e:
        print(f"[document_builder] feature fetch failed: {e}")
        return []
    finally:
        if own_conn:
            conn.close()


def build_document(prop: dict, feature_names: Optional[list] = None) -> str:
    """Assemble one descriptive string from a property row dict.

    Robust to missing columns. `feature_names` can be passed in to avoid a DB hit
    during batch backfill; otherwise it is fetched if an id is present.
    """
    if feature_names is None and prop.get("id") is not None:
        feature_names = get_feature_names(prop["id"])
    feature_names = feature_names or []

    name = (prop.get("name") or prop.get("title") or "").strip()
    ptype = (prop.get("property_type") or "").strip()
    raw_listing = str(prop.get("listing_type") or "").lower().strip()
    listing = _LISTING_LABEL.get(raw_listing, raw_listing)
    rooms = str(prop.get("room_count") or "").strip()
    beds = prop.get("beds")
    baths = prop.get("baths")
    net = prop.get("net_m2")
    gross = prop.get("gross_m2")
    city = (prop.get("city") or "").strip()
    district = (prop.get("district") or "").strip()
    country = (prop.get("country") or "").strip()
    heating = (prop.get("heating") or "").strip()
    age = str(prop.get("building_age") or "").strip()
    desc = (prop.get("description") or "").strip()

    parts = []
    if name:
        parts.append(name + ".")
    type_bits = " ".join(b for b in [ptype, listing] if b).strip()
    if type_bits:
        parts.append(type_bits + ".")

    loc = ", ".join(b for b in [district, city, country] if b)
    if loc:
        parts.append("Location: " + loc + ".")

    room_bits = []
    if rooms:
        room_bits.append(rooms)
    if beds:
        room_bits.append(f"{beds} bedrooms")
    if baths:
        room_bits.append(f"{baths} bathrooms")
    if room_bits:
        parts.append(", ".join(room_bits) + ".")

    size_bits = []
    if net:
        size_bits.append(f"{net} m2 net")
    if gross:
        size_bits.append(f"{gross} m2 gross")
    if size_bits:
        parts.append(", ".join(size_bits) + ".")

    if heating:
        parts.append(f"{heating} heating.")
    if age:
        parts.append(f"Building age: {age}.")
    if feature_names:
        parts.append("Features: " + ", ".join(feature_names) + ".")
    if desc:
        parts.append(desc)

    return " ".join(parts).strip()
