"""Central configuration for the AI layer.

Reads from the same .env that powers DATABASE_URL (python-dotenv). Nothing here
imports the OpenAI SDK, so importing this module is always safe.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# --- OpenAI ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
CHAT_MODEL = os.getenv("CHAT_MODEL", "gpt-4o-mini")  # used by the constraint extractor

# text-embedding-3-small => 1536 dims (must match properties.embedding vector(1536))
EMBEDDING_DIM = 1536

# --- Pipeline tuning ---
CANDIDATE_LIMIT = 200      # Stage 3 candidate-set ceiling before vector rerank
MIN_RESULTS = 10           # below this, Stage 3 relaxes constraints and retries
DEFAULT_TOP_K = 20         # Stage 4 results returned

# --- Hybrid ranking weights (Stage 4) ---
# Vector similarity stays DOMINANT so semantic search is never diluted; the rest
# are nudges/tie-breakers. Tune here without touching SQL. See
# query_pipeline.build_hybrid_order_sql.
HYBRID_W_VECTOR = 0.70     # cosine similarity to the query embedding
HYBRID_W_LEXICAL = 0.15    # full-text keyword overlap (ts_rank) on name+description
HYBRID_W_RATING = 0.10     # avg_rating / 5
HYBRID_W_RECENCY = 0.05    # mild freshness boost for newer listings

# --- LLM rerank (Stage 5, optional precision pass) ---
# After hybrid ranking, optionally let GPT reorder the top-N candidates by their
# relevance to the query (cross-encoder style). Fails soft to the hybrid order.
# Costs ONE extra gpt call per search; flip off here to trade precision for latency.
LLM_RERANK = os.getenv("LLM_RERANK", "1") not in ("0", "false", "False", "")
LLM_RERANK_TOP_N = 20      # how many top hybrid hits to hand the reranker

# --- Relevance gate (reject off-topic queries) ---
# Vector search always returns the *nearest* rows, even for off-topic queries
# ("castle", "spaceship"). A cosine floor can't fix this — short legit queries
# ('pool', 'sea view') score as low as nonsense — so for a PURELY semantic query
# (no hard filters) we ask the LLM whether our catalog can plausibly answer it, and
# return empty when it can't. Skipped whenever concrete filters are present.
RELEVANCE_GATE = os.getenv("RELEVANCE_GATE", "1") not in ("0", "false", "False", "")


def ai_enabled() -> bool:
    """True only when an API key is present AND the openai SDK is importable.

    Every call site checks this first; when False the system uses keyword search.
    """
    if not OPENAI_API_KEY:
        return False
    try:
        import openai  # noqa: F401
    except Exception:
        return False
    return True
