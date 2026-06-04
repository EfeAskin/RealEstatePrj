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
