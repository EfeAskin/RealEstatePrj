"""Prove the real pgvector path works WITHOUT OpenAI — using a rolled-back
transaction so nothing is persisted.

  python scripts/validate_pgvector.py

Fabricates one-hot 1536-dim vectors on three real properties, runs the exact
ORDER BY embedding <=> query used in production, asserts the nearest match is
correct, then ROLLS BACK. Confirms extension + column + operator + ordering.
"""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
DIM = 1536


def onehot(pos):
    v = [0.0] * DIM
    v[pos] = 1.0
    return "[" + ",".join(repr(x) for x in v) + "]"


def main():
    conn = psycopg2.connect(os.getenv("DATABASE_URL"), sslmode="require")
    host = conn.get_dsn_parameters().get("host", "?")
    print(f"endpoint: {host}")
    cur = conn.cursor()

    # operator sanity (no data needed)
    cur.execute("SELECT '[1,0,0]'::vector(3) <=> '[0,1,0]'::vector(3)")
    print(f"cosine distance orthogonal vectors = {cur.fetchone()[0]} (expect ~1.0)")

    cur.execute("SELECT id FROM properties ORDER BY id LIMIT 3")
    ids = [r[0] for r in cur.fetchall()]
    if len(ids) < 3:
        print("need >=3 properties to validate ranking"); return

    try:
        # set distinct one-hot vectors on three rows (positions 0, 1, 2)
        for pos, pid in enumerate(ids):
            cur.execute("UPDATE properties SET embedding = %s::vector WHERE id = %s", (onehot(pos), pid))

        # query closest to position 1 -> expect ids[1] first
        cur.execute(
            "SELECT id FROM properties WHERE id = ANY(%s) ORDER BY embedding <=> %s::vector",
            (ids, onehot(1)),
        )
        order = [r[0] for r in cur.fetchall()]
        print(f"candidate ids        : {ids}")
        print(f"reranked for pos-1 vec: {order}")
        ok = order and order[0] == ids[1]
        print("PASS — nearest match correct" if ok else "FAIL — unexpected ordering")
    finally:
        conn.rollback()   # nothing persisted
        print("rolled back (no data changed)")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
