#!/usr/bin/env python3
"""Enrich Midrash works/editions with Sefaria metadata and licence evidence."""
from __future__ import annotations
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
import psycopg2
from psycopg2.extras import Json
from midrash_config import database_url

BASE_SCHEMA = "https://storage.googleapis.com/sefaria-export/schemas/"
API_BASE = "https://www.sefaria.org/api/v3/texts/"


def fetch_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "midrash-metadata-upgrader/1.0"})
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.load(response)


def schema_for(title: str):
    url = BASE_SCHEMA + urllib.parse.quote(title.replace(" ", "_") + ".json")
    try:
        return fetch_json(url), url
    except Exception as exc:
        print("schema unavailable", title, type(exc).__name__, exc)
        return {}, url


def api_for(ref: str):
    url = API_BASE + urllib.parse.quote(ref, safe="")
    try:
        return fetch_json(url), url
    except Exception as exc:
        print("API metadata unavailable", ref, type(exc).__name__, exc)
        return {}, url


def ascii_safe(value):
    if isinstance(value, dict):
        return {str(k): ascii_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [ascii_safe(v) for v in value]
    if isinstance(value, str):
        return value.encode("ascii", "replace").decode("ascii")
    return value


def version_summary(v: dict) -> dict:
    keep = [
        "versionTitle", "versionSource", "license", "language", "actualLanguage",
        "isSource", "isPrimary", "versionUrl", "versionNotes",
    ]
    return {k: v.get(k) for k in keep if v.get(k) is not None}


def main():
    conn = psycopg2.connect(database_url(), options="-c client_encoding=UTF8")
    conn.set_client_encoding("UTF8")
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_encoding_to_char(encoding) FROM pg_database WHERE datname=current_database()")
            encoding_row = cur.fetchone()
            ascii_only = (encoding_row[0] if encoding_row else "SQL_ASCII").upper() == "SQL_ASCII"
            cur.execute("""
                SELECT w.id,w.sefaria_title,e.id,e.language,e.version_title,e.license,e.version_source,
                       s.sefaria_ref
                FROM works w JOIN editions e ON e.work_id=w.id
                LEFT JOIN LATERAL (SELECT sefaria_ref FROM segments WHERE edition_id=e.id ORDER BY id LIMIT 1) s ON true
                ORDER BY w.sefaria_title,e.language,e.version_title
            """)
            rows = cur.fetchall()
            schema_cache = {}
            api_cache = {}
            for work_id, title, edition_id, language, version_title, old_license, old_source, sample_ref in rows:
                if title not in schema_cache:
                    schema_cache[title] = schema_for(title)
                schema, schema_url = schema_cache[title]
                categories = schema.get("categories") or []
                he_title = schema.get("heTitle")
                description = schema.get("enDesc") or schema.get("enShortDesc")
                work_meta = {
                    "metadata_source": schema_url,
                    "schema_title": schema.get("title"),
                    "categories": categories,
                    "era": schema.get("era"),
                    "composition_date": schema.get("compDate"),
                    "publication_date": schema.get("pubDate"),
                    "he_description_available": bool(schema.get("heDesc")),
                    "composition_date_display": schema.get("compDateString", {}).get("en") if isinstance(schema.get("compDateString"), dict) else schema.get("compDateString"),
                    "publication_date_display": schema.get("pubDateString", {}).get("en") if isinstance(schema.get("pubDateString"), dict) else schema.get("pubDateString"),
                    "authors": schema.get("authors"),
                    "en_short_description": schema.get("enShortDesc"),
                }
                cur.execute("""
                    UPDATE works SET hebrew_title=COALESCE(%s,hebrew_title),
                        categories=COALESCE(NULLIF(%s::text[], '{}'::text[]), categories),
                        description=COALESCE(%s,description), metadata=%s
 WHERE id=%s
 """, (he_title, categories, description,
       json.dumps(ascii_safe(work_meta) if ascii_only else work_meta,
                  ensure_ascii=ascii_only), work_id))

                api_data, api_url = ({}, None)
                if sample_ref:
                    if sample_ref not in api_cache:
                        api_cache[sample_ref] = api_for(sample_ref)
                    api_data, api_url = api_cache[sample_ref]
                available = [version_summary(v) for v in (api_data.get("available_versions") or [])]
                matching = next((v for v in available if v.get("versionTitle") == version_title and (v.get("language") in (None, language))), None)
                # The export's merged edition combines one or more Sefaria versions;
                # do not falsely assign a single version's licence to it.
                if matching and matching.get("license"):
                    new_license = matching["license"]
                elif version_title == "merged":
                    new_license = "Mixed/see metadata" if available else old_license
                else:
                    new_license = old_license
                edition_meta = {
                    "format": "cltk-flat",
                    "metadata_source": api_url,
                    "sample_ref": sample_ref,
                    "available_versions": available,
                    "matched_version": matching,
                    "licence_status": "validated" if matching and matching.get("license") else ("mixed" if version_title == "merged" and available else "not_found"),
                    "upgraded_at": datetime.now(timezone.utc).isoformat(),
                }
                cur.execute("""
                    UPDATE editions SET license=%s, version_source=COALESCE(%s,version_source), metadata=metadata || %s::jsonb
                    WHERE id=%s
                """, (new_license, matching.get("versionSource") if matching else None,
                      json.dumps(ascii_safe(edition_meta) if ascii_only else edition_meta,
                                 ensure_ascii=ascii_only), edition_id))
                print(title, language, version_title, "=>", new_license, "available", len(available), "matched", bool(matching))
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
