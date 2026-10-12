"""Apply a .sql migration file to the database in DATABASE_URL.

Usage:  python scripts/run_migration.py scripts/migrations/001_ai_foundation.sql

Prints the active endpoint host first so you can confirm you are on the
intended branch (NOT main) before anything runs.
"""
import os
import sys
import re
import psycopg2
from dotenv import load_dotenv

load_dotenv()


def main():
    if len(sys.argv) < 2:
        print("ERROR: pass the path to a .sql file")
        sys.exit(1)

    sql_path = sys.argv[1]
    with open(sql_path, "r", encoding="utf-8") as f:
        sql = f.read()

    # Prefer the direct endpoint for DDL if available, else the pooled URL.
    url = os.getenv("DATABASE_URL_DIRECT") or os.getenv("DATABASE_URL")
    if not url:
        print("ERROR: no DATABASE_URL in environment")
        sys.exit(1)

    host = re.search(r"@([^/:]+)", url)
    print(f"Target endpoint: {host.group(1) if host else '??'}")
    print(f"Applying: {sql_path}\n")

    conn = psycopg2.connect(url, sslmode="require")
    conn.autocommit = True  # each statement commits; extensions/DDL run cleanly
    try:
        cur = conn.cursor()
        cur.execute(sql)
        cur.close()
        print("Migration applied successfully.")
    except Exception as e:
        print(f"MIGRATION FAILED: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
