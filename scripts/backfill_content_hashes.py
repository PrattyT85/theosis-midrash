#!/usr/bin/env python3
"""Backfill source hashes for historical ingestion-manifest rows without reimporting text."""
from __future__ import annotations

import argparse
import hashlib
import urllib.request

import psycopg2
from psycopg2.extras import Json

from midrash_config import database_url


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=database_url())
    args = parser.parse_args()
    with psycopg2.connect(args.db) as conn:
        conn.set_client_encoding("UTF8")
        with conn.cursor() as cur:
            cur.execute("""
                SELECT m.edition_id,m.source_url,e.metadata
                FROM ingestion_manifest m
                JOIN editions e ON e.id=m.edition_id
                WHERE m.content_sha256 IS NULL
                ORDER BY m.edition_id
            """)
            rows = cur.fetchall()
            for edition_id, source_url, old_metadata in rows:
                request = urllib.request.Request(
                    source_url,
                    headers={"User-Agent": "theosis-midrash-hash-backfill/1.0"},
                )
                with urllib.request.urlopen(request, timeout=180) as response:
                    payload = response.read()
                digest = hashlib.sha256(payload).hexdigest()
                metadata = dict(old_metadata or {})
                metadata.update({
                    "content_sha256": digest,
                    "source_bytes": len(payload),
                    "source_export_url": source_url,
                })
                cur.execute(
                    "UPDATE editions SET metadata=%s WHERE id=%s",
                    (Json(metadata), edition_id),
                )
                cur.execute(
                    "UPDATE ingestion_manifest SET content_sha256=%s WHERE edition_id=%s",
                    (digest, edition_id),
                )
                print(edition_id, digest[:12], source_url, flush=True)
            print(f"Backfilled {len(rows)} historical content hashes")


if __name__ == "__main__":
    main()
