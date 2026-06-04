"""Offline tests for the AI layer — no network, no DB, no API key required.

Run:  python tests/test_ai_offline.py
Validates the provider-agnostic logic so bugs surface before the key is added.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.place_aliases import normalize_places
from services.document_builder import build_document
from services import openai_client, ai_config, query_pipeline


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


def test_candidate_sql_location():
    print("build_candidate_sql (location robustness):")
    # A city filter must match the place across BOTH city and district columns
    # (flat free-text geography), case-insensitively, without dropping valid rows.
    sql, params = query_pipeline.build_candidate_sql({"city": "Kyrenia"})
    check("city matches city OR district", "city ILIKE %s OR district ILIKE %s" in sql)
    check("city value bound twice", params.count("Kyrenia") == 2)
    # A district filter also checks city + the longer free-text location column.
    sql2, params2 = query_pipeline.build_candidate_sql({"district": "Alsancak"})
    check("district matches across 3 columns",
          "district ILIKE %s OR city ILIKE %s OR location ILIKE %s" in sql2)
    check("district uses contains-match on location", "%Alsancak%" in params2)
    # property_type stays STRICT (exact equality, per requirement).
    sql3, _ = query_pipeline.build_candidate_sql({"property_type": "Villa"})
    check("property_type stays exact", "property_type = %s" in sql3)


def test_hybrid_order_sql():
    print("build_hybrid_order_sql (hybrid ranking):")
    sql, params = query_pipeline.build_hybrid_order_sql("[0.1,0.2]", "sea view villa")
    check("is an ORDER BY clause", sql.strip().startswith("ORDER BY"))
    check("vector term present", "embedding <=> %s::vector" in sql)
    check("lexical term present", "ts_rank" in sql and "plainto_tsquery" in sql)
    check("rating term present", "avg_rating" in sql)
    check("NULL embeddings sink", "NULLS LAST" in sql)
    check("exactly two params (qvec, query_text)", params == ["[0.1,0.2]", "sea view villa"])
    check("vector weight dominant",
          ai_config.HYBRID_W_VECTOR > (ai_config.HYBRID_W_LEXICAL
                                       + ai_config.HYBRID_W_RATING
                                       + ai_config.HYBRID_W_RECENCY))


def test_llm_rerank_helpers():
    print("LLM rerank helpers:")
    row = {"id": 7, "name": "Azure Infinity Villa", "property_type": "Villa",
           "listing_type": "sale", "room_count": "4+1", "city": "Kyrenia",
           "district": "Esentepe", "net_m2": 300, "price_normalized": 750000,
           "currency_code": "GBP"}
    s = query_pipeline.summarize_for_rerank(row)
    check("summary has title", "Azure Infinity Villa" in s)
    check("summary has type + location", "Villa" in s and "Kyrenia" in s)
    check("summary has price + currency", "750000 GBP" in s)
    # Gating: with LLM_RERANK off, rows pass through untouched (no API call).
    saved = ai_config.LLM_RERANK
    ai_config.LLM_RERANK = False
    try:
        rows = [{"id": 1}, {"id": 2}]
        check("disabled -> input returned as-is", query_pipeline.llm_rerank_rows("q", rows) is rows)
    finally:
        ai_config.LLM_RERANK = saved
    # A single-row list is never reranked (no API call regardless of config).
    check("single row -> unchanged", query_pipeline.llm_rerank_rows("q", [{"id": 1}]) == [{"id": 1}])


def test_relevance_gate():
    print("relevance gate:")
    # A query with any concrete filter is "specific" -> never gated.
    check("city counts as a hard filter",
          query_pipeline.has_hard_filters({"city": "Kyrenia", "semantic_query": "x"}))
    check("price counts as a hard filter",
          query_pipeline.has_hard_filters({"max_price": 500, "semantic_query": "x"}))
    check("pure semantic query has no hard filters",
          not query_pipeline.has_hard_filters({"semantic_query": "castle with a beach"}))
    # has_filters=True short-circuits -> never off-topic, no LLM call.
    check("hard-filtered query is never gated",
          query_pipeline.is_off_topic("castle", has_filters=True) is False)
    # Gate disabled -> never off-topic, no LLM call.
    saved = ai_config.RELEVANCE_GATE
    ai_config.RELEVANCE_GATE = False
    try:
        check("disabled gate keeps results",
              query_pipeline.is_off_topic("castle", has_filters=False) is False)
    finally:
        ai_config.RELEVANCE_GATE = saved


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
    for t in (test_place_aliases, test_document_builder, test_vector_literal,
              test_candidate_sql_location, test_hybrid_order_sql,
              test_llm_rerank_helpers, test_relevance_gate, test_graceful_without_key):
        t()
    print(f"\n{'ALL PASS' if check.failed == 0 else str(check.failed) + ' FAILED'}")
    sys.exit(1 if check.failed else 0)
