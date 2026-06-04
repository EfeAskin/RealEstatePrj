"""AI services package: semantic search + recommendation engine.

All OpenAI access is isolated in `openai_client.py`. The rest of the package
(document building, place normalization, the query pipeline, recommendations)
is provider-agnostic and runs without an API key — the pipeline degrades to
keyword search when embeddings/GPT are unavailable.
"""
