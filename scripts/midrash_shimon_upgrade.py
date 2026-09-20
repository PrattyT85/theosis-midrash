#!/usr/bin/env python3
"""Add the available English Sefaria editions for Mekhilta d'Rabbi Shimon ben Yochai."""
import psycopg2
from midrash_import import import_edition

TITLE = "Mekhilta DeRabbi Shimon Ben Yochai"
ED = [
    ("en", "Sefaria Community Translation", "CC0", "https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Halakhah/Mekhilta%20DeRabbi%20Shimon%20Ben%20Yochai/English/Sefaria%20Community%20Translation.json"),
    ("en", "merged", "Mixed/see metadata", "https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Halakhah/Mekhilta%20DeRabbi%20Shimon%20Ben%20Yochai/English/merged.json"),
    ("en", "Rabbi Mike Feuer, Jerusalem Anthology", "Not specified", "https://storage.googleapis.com/sefaria-export/cltk-flat/Midrash/Halakhah/Mekhilta%20DeRabbi%20Shimon%20Ben%20Yochai/English/Rabbi%20Mike%20Feuer%2C%20Jerusalem%20Anthology.json"),
]

with psycopg2.connect("dbname=midrash user=midrash host=/var/run/postgresql", options="-c client_encoding=UTF8") as conn:
    conn.set_client_encoding("UTF8")
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM works WHERE sefaria_title=%s", (TITLE,))
        row = cur.fetchone()
        if not row:
            raise SystemExit(f"Work not found: {TITLE}")
        work_id = row[0]
        for edition in ED:
            import_edition(cur, work_id, TITLE, *edition)
    conn.commit()
print("Mekhilta d'Rabbi Shimon English edition upgrade complete")
