#!/usr/bin/env python3
"""Import Sefaria Export links involving the Midrash corpus."""
from __future__ import annotations
import csv
import io
import json
import re
import urllib.request
from itertools import count
import psycopg2
from psycopg2.extras import execute_values
from midrash_config import database_url

LINK_FILES = [
    f"https://storage.googleapis.com/sefaria-export/links/links{i}.csv" for i in range(17)
]


def ascii_safe(value: str | None) -> str:
    return (value or "").encode("ascii", "replace").decode("ascii")


def is_midrash_ref(ref: str, titles: list[str]) -> str | None:
    ref = (ref or "").strip()
    for title in titles:
        if ref == title or ref.startswith(title + " ") or ref.startswith(title + ","):
            return title
    return None


def main():
    conn = psycopg2.connect(
        database_url(),
        options="-c client_encoding=UTF8",
    )
    conn.set_client_encoding("UTF8")
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT sefaria_title FROM works ORDER BY length(sefaria_title) DESC")
            titles = [row[0] for row in cur.fetchall()]
            cur.execute("SELECT pg_encoding_to_char(encoding) FROM pg_database WHERE datname=current_database()")
            encoding_row = cur.fetchone()
            db_encoding = encoding_row[0] if encoding_row else "SQL_ASCII"
        conn.commit()
        ascii_only = db_encoding.upper() == "SQL_ASCII"

        total_seen = 0
        total_matched = 0
        skipped_nonascii = 0
        batch: list[tuple[str, str, str | None, str]] = []
        for file_url in LINK_FILES:
            print("Reading", file_url, flush=True)
            request = urllib.request.Request(
                file_url, headers={"User-Agent": "midrash-links-import/1.0"}
            )
            with urllib.request.urlopen(request, timeout=180) as response:
                text_stream = io.TextIOWrapper(response, encoding="utf-8", errors="replace", newline="")
                reader = csv.DictReader(text_stream)
                for row in reader:
                    total_seen += 1
                    left = (row.get("Citation 1") or "").strip()
                    right = (row.get("Citation 2") or "").strip()
                    left_work = is_midrash_ref(left, titles)
                    right_work = is_midrash_ref(right, titles)
                    if not left_work and not right_work:
                        continue
                    if not left or not right:
                        continue
                    # The historical live database is SQL_ASCII. Preserve the
                    # old safe behaviour there, but retain Hebrew on UTF-8
                    # installations instead of silently replacing it.
                    if ascii_only and not all(ord(char) < 128 for char in left + right):
                        skipped_nonascii += 1
                        continue
                    if left_work:
                        source_ref, target_ref = left, right
                        source_work = left_work
                    else:
                        source_ref, target_ref = right, left
                        source_work = right_work
                    metadata = {
                        "source_export": file_url,
                        "midrash_work": source_work,
                        "citation_1": left,
                        "citation_2": right,
                        "text_1": row.get("Text 1") or "",
                        "text_2": row.get("Text 2") or "",
                        "category_1": row.get("Category 1") or "",
                        "category_2": row.get("Category 2") or "",
                    }
                    safe = ascii_safe if ascii_only else (lambda value: value or "")
                    batch.append((safe(source_ref), safe(target_ref),
                                  safe(row.get("Conection Type") or "") or "link",
                                  json.dumps({k: safe(str(v)) for k, v in metadata.items()},
                                             ensure_ascii=ascii_only)))
                    if len(batch) >= 2000:
                        # Deduplicate within the batch before ON CONFLICT, because
                        # PostgreSQL rejects two proposed updates to the same row.
                        batch = list({(a, b, c): (a, b, c, d) for a, b, c, d in batch}.values())
                    total_matched += 1
                    if len(batch) >= 2000:
                        with conn.cursor() as cur:
                            execute_values(cur, """
                                INSERT INTO source_links(source_ref,target_ref,link_type,metadata)
                                VALUES %s ON CONFLICT (source_ref,target_ref,link_type) DO UPDATE
                                SET metadata=EXCLUDED.metadata
                            """, batch, template="(%s,%s,%s,%s::jsonb)")
                        conn.commit()
                        batch.clear()
                        if total_matched % 10000 < 2000:
                            print("matched", total_matched, "rows", flush=True)
            print("finished", file_url, "matched", total_matched, flush=True)
        if batch:
            with conn.cursor() as cur:
                execute_values(cur, """
                    INSERT INTO source_links(source_ref,target_ref,link_type,metadata)
                    VALUES %s ON CONFLICT (source_ref,target_ref,link_type) DO UPDATE
                    SET metadata=EXCLUDED.metadata
                """, batch, template="(%s,%s,%s,%s::jsonb)")
            conn.commit()
        print("Complete; CSV rows seen:", total_seen, "matched:", total_matched,
              "skipped non-ASCII:", skipped_nonascii, "encoding:", db_encoding, flush=True)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
