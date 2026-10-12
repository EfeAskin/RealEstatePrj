"""Generate and store embeddings for properties that need them.

  python scripts/backfill_embeddings.py            # only rows that need it
  python scripts/backfill_embeddings.py --all      # force re-embed everything

Idempotent and resumable. Needs OPENAI_API_KEY in .env; if absent it explains
and exits 0 (so it is safe to wire into deploys before the key exists).

A row "needs embedding" when: embedding IS NULL, status <> 'done', or the row
was updated after it was last embedded (updated_at > embedding_synced_at).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from psycopg2.extras import RealDictCursor
from app.db.connection import get_db_connection
from app.services import ai_config, openai_client
from app.services.document_builder import build_document, get_feature_names

BATCH = 100

NEEDS_SQL = """
    SELECT * FROM properties
    WHERE %s
       OR embedding IS NULL
       OR embedding_status <> 'done'
       OR embedding_synced_at IS NULL
       OR (updated_at IS NOT NULL AND updated_at > embedding_synced_at)
    ORDER BY id
"""


def main():
    force_all = "--all" in sys.argv

    if not ai_config.ai_enabled():
        print("OPENAI_API_KEY not set (or openai SDK missing) — nothing to do yet.")
        print("Add the key to .env and re-run; the schema is already prepared.")
        return

    conn = get_db_connection()
    if not conn:
        print("No DB connection.")
        sys.exit(1)

    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(NEEDS_SQL, (force_all,))
    rows = cur.fetchall()
    print(f"{len(rows)} propert{'y' if len(rows)==1 else 'ies'} to embed.")

    done = failed = 0
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        docs, ids = [], []
        for r in chunk:
            feats = get_feature_names(r["id"], conn=conn)
            docs.append(build_document(dict(r), feature_names=feats))
            ids.append(r["id"])

        vectors = openai_client.embed_texts(docs)
        if vectors is None:
            # whole batch failed -> mark failed, continue
            for pid in ids:
                _mark_failed(cur, pid)
            conn.commit()
            failed += len(ids)
            print(f"  batch {i//BATCH+1}: embedding call failed ({len(ids)} marked failed)")
            continue

        for pid, doc, vec in zip(ids, docs, vectors):
            try:
                cur.execute(
                    """
                    UPDATE properties
                    SET embedding = %s::vector,
                        embedding_text = %s,
                        embedding_status = 'done',
                        embedding_synced_at = now()
                    WHERE id = %s
                    """,
                    (openai_client.to_vector_literal(vec), doc, pid),
                )
                done += 1
            except Exception as e:
                print(f"  id {pid}: store failed: {e}")
                conn.rollback()
                _mark_failed(cur, pid)
                failed += 1
        conn.commit()
        print(f"  batch {i//BATCH+1}: {done} done, {failed} failed so far")

    cur.close()
    conn.close()
    print(f"Finished. {done} embedded, {failed} failed.")


def _mark_failed(cur, pid):
    try:
        cur.execute("UPDATE properties SET embedding_status = 'failed' WHERE id = %s", (pid,))
    except Exception:
        pass


if __name__ == "__main__":
    main()
