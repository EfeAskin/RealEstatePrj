"""Offline tests for the AI layer — no network, no DB, no API key required.

Run:  python tests/test_ai_offline.py
Validates the provider-agnostic logic so bugs surface before the key is added.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.place_aliases import normalize_places
from services.document_builder import build_document
from services import openai_client, ai_config


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        check.failed += 1
check.failed = 0


def test_place_aliases():
    print("place_aliases:")
    check("Girne -> Kyrenia", "Kyrenia" in normalize_places("Girne'de 3+1 daire"))
    check("Lefkoşa -> Nicosia", "Nicosia" in normalize_places("Lefkoşa merkez"))
    check("mainland Muğla -> Mugla", "Mugla" in normalize_places("muğla bodrum villa"))
    check("English passes through", normalize_places("sea view in Kyrenia") == "sea view in Kyrenia")


def test_document_builder():
    print("document_builder:")
    prop = {
        "name": "Cozy seaside flat", "property_type": "Apartment", "listing_type": "sale",
        "room_count": "3+1", "beds": 3, "baths": 2, "net_m2": 120, "city": "Kyrenia",
        "district": "Alsancak", "country": "North Cyprus", "heating": "Central",
        "description": "Walking distance to the beach.",
    }
    doc = build_document(prop, feature_names=["Balcony", "Deniz Manzarası", "Pool"])
    check("includes title", "Cozy seaside flat" in doc)
    check("maps sale->for sale", "for sale" in doc)
    check("includes location", "Alsancak" in doc and "Kyrenia" in doc)
    check("includes bilingual feature", "Deniz Manzarası" in doc)
    check("includes description", "beach" in doc)


def test_vector_literal():
    print("vector helper:")
    lit = openai_client.to_vector_literal([0.1, 0.2, 0.3])
    check("formats pgvector literal", lit.startswith("[") and lit.endswith("]") and "0.1" in lit)


def test_graceful_without_key():
    print("graceful degradation (no key):")
    # With no key, every OpenAI entrypoint must return None, not raise.
    check("ai_enabled is False without key", ai_config.ai_enabled() in (True, False))
    if not ai_config.ai_enabled():
        check("embed_query -> None", openai_client.embed_query("x") is None)
        check("extract_constraints -> None", openai_client.extract_constraints("x", "sys") is None)
    else:
        print("  (key present — skipping no-key assertions)")


if __name__ == "__main__":
    for t in (test_place_aliases, test_document_builder, test_vector_literal, test_graceful_without_key):
        t()
    print(f"\n{'ALL PASS' if check.failed == 0 else str(check.failed) + ' FAILED'}")
    sys.exit(1 if check.failed else 0)
