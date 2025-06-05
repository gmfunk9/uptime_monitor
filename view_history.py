#!/usr/bin/env python3

"""Simple CLI to print scan history"""

import sqlite3
import sys
from pathlib import Path


def list_tables(conn):
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    names = [row[0] for row in cur.fetchall()]
    return names


def fetch_rows(conn, table, limit):
    cur = conn.cursor()
    cur.execute(
        f"SELECT timestamp, response_code, ttfb, total FROM {table}"
        " ORDER BY timestamp DESC LIMIT ?",
        (limit,),
    )
    return cur.fetchall()


def print_rows(domain, rows):
    print(domain)
    for ts, code, ttfb, total in rows:
        scan = "H" if ttfb is None and total is None else "G"
        print(f"{ts} {scan} {code or ''} {ttfb or ''} {total or ''}")
    print()


def main():
    db_file = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("website_stats.db")
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10

    conn = sqlite3.connect(db_file)
    tables = list_tables(conn)
    for table in tables:
        rows = fetch_rows(conn, table, limit)
        domain = table.replace("_", ".")
        print_rows(domain, rows)
    conn.close()


if __name__ == "__main__":
    main()

