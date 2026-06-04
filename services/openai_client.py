"""The ONLY module that talks to OpenAI.

Swap providers by rewriting this file alone. Every function fails soft: if the
key is missing, the SDK is absent, or the API errors, it returns None / [] and
logs — callers fall back to keyword search. Nothing here ever raises to the request.
"""
import json
import threading
from typing import List, Optional

from services import ai_config

_client = None
_client_lock = threading.Lock()

# tiny in-process cache: identical queries within a process don't re-embed/re-pay
_query_cache: dict = {}


def _get_client():
    """Lazily build a singleton OpenAI client. Returns None if unavailable."""
    global _client
    if not ai_config.ai_enabled():
        return None
    if _client is not None:
        return _client
    with _client_lock:
        if _client is None:
            try:
                from openai import OpenAI
                _client = OpenAI(api_key=ai_config.OPENAI_API_KEY)
            except Exception as e:
                print(f"[openai_client] client init failed: {e}")
                return None
    return _client


# ---------------------------------------------------------------- embeddings

def embed_texts(texts: List[str]) -> Optional[List[List[float]]]:
    """Embed a batch of documents (index-time). Returns one vector per input,
    or None if embeddings are unavailable. OpenAI accepts up to 2048 inputs/call."""
    client = _get_client()
    if client is None or not texts:
        return None
    try:
        resp = client.embeddings.create(model=ai_config.EMBEDDING_MODEL, input=texts)
        # resp.data is returned in input order
        return [d.embedding for d in resp.data]
    except Exception as e:
        print(f"[openai_client] embed_texts failed: {e}")
        return None


def embed_query(text: str) -> Optional[List[float]]:
    """Embed a single user query (query-time), cached. Returns None if unavailable."""
    if not text:
        return None
    if text in _query_cache:
        return _query_cache[text]
    vecs = embed_texts([text])
    if not vecs:
        return None
    _query_cache[text] = vecs[0]
    return vecs[0]


# ----------------------------------------------------- GPT constraint extractor

def extract_constraints(query: str, system_prompt: str) -> Optional[dict]:
    """Stage 2: parse a natural-language query into a structured filter dict via GPT.

    Returns the raw parsed JSON (still UNVALIDATED — caller must validate) or None
    on any failure, so the pipeline can proceed with no hard filters.
    """
    client = _get_client()
    if client is None or not query:
        return None
    try:
        resp = client.chat.completions.create(
            model=ai_config.CHAT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content
        return json.loads(content)
    except Exception as e:
        print(f"[openai_client] extract_constraints failed: {e}")
        return None


# ----------------------------------------------------- conversational reply

def chat_reply(user_message: str, filters: dict, count: int,
               sample_titles: Optional[List[str]] = None,
               dropped: Optional[List[str]] = None) -> Optional[str]:
    """Write a short, friendly assistant sentence to wrap the search results.

    Deliberately grounded: GPT only sees the user's message, the structured
    filters we actually applied, the result count, and which constraints (if any)
    had to be relaxed — never free-form property facts — so it cannot invent
    listings or claim a constraint held when it didn't. Returns None on any
    failure; the caller then falls back to a templated sentence.
    """
    client = _get_client()
    if client is None or not user_message:
        return None
    facts = {
        "applied_filters": {k: v for k, v in (filters or {}).items()
                            if k != "semantic_query" and v not in (None, "")},
        "result_count": count,
        "relaxed_constraints": dropped or [],
        "example_titles": (sample_titles or [])[:3],
    }
    system = (
        "You are a concise, warm real-estate search assistant for a North Cyprus / "
        "Turkey property site. You DO NOT chit-chat about unrelated topics — you only "
        "help find properties. Given the user's request and a JSON summary of what the "
        "search engine actually matched, write ONE short, natural sentence (max ~30 words) "
        "introducing the results, like 'Here are the apartments I found in Famagusta within "
        "your budget.' IMPORTANT: if 'relaxed_constraints' is non-empty, those filters could "
        "NOT be met, so be honest — e.g. 'I couldn't find any under that budget, but here are "
        "the closest matches.' Never claim a constraint was satisfied when it is listed in "
        "relaxed_constraints. If result_count is 0, gently say nothing matched and suggest "
        "widening the budget or location. Never invent specific listings, prices, or counts "
        "beyond result_count. Reply in the user's language. Output only the sentence."
    )
    try:
        resp = client.chat.completions.create(
            model=ai_config.CHAT_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content":
                    f"User request: {user_message}\n\nSearch summary (JSON): {json.dumps(facts, ensure_ascii=False)}"},
            ],
            temperature=0.4,
            max_tokens=80,
        )
        return (resp.choices[0].message.content or "").strip() or None
    except Exception as e:
        print(f"[openai_client] chat_reply failed: {e}")
        return None


# ---------------------------------------------------------------- vector helper

def to_vector_literal(vec: List[float]) -> str:
    """Format a Python float list as a pgvector literal: '[0.1,0.2,...]'.

    Bind with a `%s::vector` cast — avoids needing the pgvector psycopg2 adapter.
    """
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"
