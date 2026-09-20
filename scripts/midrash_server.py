#!/usr/bin/env python3
"""Midrash MCP service backed by PostgreSQL and Sefaria Export data."""
from __future__ import annotations

import os
import re
import asyncio
import html
import json
import logging
from typing import Any

import asyncpg
from mcp.server.fastmcp import FastMCP

DB_URL = os.environ.get("MIDRASH_DATABASE_URL", "postgresql://midrash@/midrash?host=/var/run/postgresql")
HOST = os.environ.get("MIDRASH_HOST", "0.0.0.0")
PORT = int(os.environ.get("MIDRASH_PORT", "8001"))
MAX_HEBREW_CANDIDATES = int(os.environ.get("MIDRASH_MAX_HEBREW_CANDIDATES", "50000"))
logger = logging.getLogger("midrash-mcp")

PREVIEW_COLUMNS = """
    s.sefaria_ref, left(s.text, 900) AS text, length(s.text) AS text_length,
    s.section_path, s.segment_number,
    w.sefaria_title AS work_title, w.hebrew_title, w.corpus, w.categories,
    w.source_url AS work_source_url, w.discovered_at,
    e.id AS edition_id, e.language, e.version_title, e.license,
    e.version_source AS source_url, e.is_source, e.is_primary,
    e.metadata AS edition_metadata
"""

FULL_COLUMNS = """
    s.sefaria_ref, s.text, length(s.text) AS text_length,
    s.section_path, s.segment_number,
    w.sefaria_title AS work_title, w.hebrew_title, w.corpus, w.categories,
    w.source_url AS work_source_url, w.discovered_at,
    e.id AS edition_id, e.language, e.version_title, e.license,
    e.version_source AS source_url, e.is_source, e.is_primary,
    e.metadata AS edition_metadata
"""

mcp = FastMCP(
    "midrash",
    instructions=(
        "Search and retrieve Jewish Midrash from Sefaria editions. "
        "Always cite the exact work, Sefaria reference, language, version title, "
        "license, and source URL returned by the tools. Midrash is interpretive "
        "literature; do not present it as the plain biblical text."
    ),
    host=HOST,
    port=PORT,
    streamable_http_path="/mcp",
    stateless_http=True,
)

_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()

async def pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        async with _pool_lock:
            if _pool is None:
                logger.info("Opening PostgreSQL connection pool")
                _pool = await asyncpg.create_pool(DB_URL, min_size=1, max_size=8, command_timeout=30)
    return _pool


def clean(value: str) -> str:
    # Decode entities before stripping tags so escaped markup cannot leak into
    # the rendered MCP result.
    value = html.unescape(value or "")
    value = re.sub(r'<i class="footnote">.*?</i>', "", value, flags=re.IGNORECASE | re.DOTALL)
    value = re.sub(r'<sup class="footnote-marker">.*?</sup>', "", value, flags=re.IGNORECASE | re.DOTALL)
    value = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", value).strip()


def clean_query(value: str) -> str:
    return re.sub(r"[^\w\u0590-\u05ff\s-]", " ", value or "").strip()


def normalize_hebrew(value: str) -> str:
    """Normalize Hebrew for search without changing stored source text."""
    import unicodedata
    value = unicodedata.normalize("NFD", value or "")
    value = "".join(ch for ch in value if not (0x0591 <= ord(ch) <= 0x05C7))
    value = value.translate(str.maketrans({"ך": "כ", "ם": "מ", "ן": "נ", "ף": "פ", "ץ": "צ"}))
    return re.sub(r"\s+", " ", value).strip()


def contains_hebrew(value: str) -> bool:
    return bool(re.search(r"[\u0590-\u05ff]", value or ""))


async def search_hebrew_in_python(p, query: str, work: str | None, category: str | None,
                                  corpus: str | None, language: str | None,
                                  phrase: bool, limit: int) -> list[dict[str, Any]]:
    """Use PostgreSQL's trigram index to narrow Hebrew candidates, then score in Python."""
    filters = []
    params: list[Any] = []
    n = 1
    if work:
        filters.append(f"w.sefaria_title ILIKE ${n}"); params.append(f"%{work}%"); n += 1
    if category:
        filters.append(f"${n} = ANY(w.categories)"); params.append(category); n += 1
    if corpus:
        filters.append(f"w.corpus = ${n}"); params.append(corpus); n += 1
    if language:
        filters.append(f"e.language = ${n}"); params.append(language); n += 1
    else:
        filters.append("e.language = 'he'")

    wanted = normalize_hebrew(query)
    terms = [normalize_hebrew(term) for term in query.split() if normalize_hebrew(term)]
    search_terms = [wanted] if phrase else list(dict.fromkeys(terms))
    if not search_terms:
        return []

    search_clauses = []
    for term in search_terms:
        like_term = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        search_clauses.append(
            f"public.midrash_normalize_hebrew(s.text) LIKE '%' || ${n} || '%' ESCAPE '\\'"
        )
        params.append(like_term)
        n += 1
    filters.append("(" + (" AND " if phrase else " OR ").join(search_clauses) + ")")
    where = " AND ".join(filters) or "TRUE"
    params.append(MAX_HEBREW_CANDIDATES + 1)
    rows = await p.fetch(f"""
        SELECT {PREVIEW_COLUMNS}
        FROM segments s JOIN works w ON w.id=s.work_id JOIN editions e ON e.id=s.edition_id
        WHERE {where}
        LIMIT ${n}
    """, *params)
    if len(rows) > MAX_HEBREW_CANDIDATES:
        raise ValueError(
            f"Hebrew search is too broad ({MAX_HEBREW_CANDIDATES:,}-row safety limit); "
            "add a work, category, corpus, or phrase filter."
        )
    scored = []
    for row in rows:
        text = normalize_hebrew(row["text"])
        if phrase:
            score = text.count(wanted) if wanted else 0
        else:
            score = sum(text.count(term) for term in terms)
        if score:
            item = dict(row); item["_score"] = score; scored.append(item)
    scored.sort(key=lambda item: (-item["_score"], item["sefaria_ref"]))
    return scored[:limit]



def row_dict(row: asyncpg.Record | None) -> dict[str, Any] | None:
    return dict(row) if row else None


async def schema_version(p: asyncpg.Pool) -> str:
    try:
        value = await p.fetchval("SELECT max(version) FROM schema_migrations")
        return value or "untracked"
    except asyncpg.UndefinedTableError:
        return "untracked"


def metadata_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def compact_json(value: Any, limit: int = 400) -> str:
    if value in (None, "", {}, []):
        return ""
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return text if len(text) <= limit else text[:limit] + "…"


def format_result(row: dict[str, Any], *, preview: bool = False) -> str:
    text = row.get("text") or ""
    text_length = row.get("text_length") or len(text)
    truncated = bool(preview and text_length > len(text))
    categories = ", ".join(row.get("categories") or []) or "not recorded"
    section_path = " › ".join(row.get("section_path") or []) or "not recorded"
    edition_meta = metadata_dict(row.get("edition_metadata"))
    provenance = []
    for key in ("licence_status", "export_generated_at", "metadata_source", "upgraded_at", "content_sha256"):
        if edition_meta.get(key):
            value = edition_meta[key]
            if key == "content_sha256":
                value = str(value)[:16] + "…"
            provenance.append(f"{key}={value}")
    lines = [
        f"**{row['sefaria_ref']}** — {row['work_title']}",
        f"Corpus: {row.get('corpus') or 'not recorded'} | Categories: {categories}",
        f"Language: {row['language']} | Edition: {row['version_title']} (edition id {row.get('edition_id')})",
        f"Edition flags: source={bool(row.get('is_source'))}; primary={bool(row.get('is_primary'))}",
        f"License: {row.get('license') or 'Not specified'}",
        f"Edition source: {row.get('source_url') or 'not recorded'}",
        f"Work source: {row.get('work_source_url') or 'not recorded'}",
        f"Section path: {section_path} | Segment: {row.get('segment_number') or 'not recorded'}",
    ]
    if provenance:
        lines.append("Import provenance: " + "; ".join(provenance))
    if truncated:
        lines.append(f"Text preview ({len(text):,} of {text_length:,} characters; use get_midrash_text for the full passage):")
    else:
        lines.append(f"Text ({text_length:,} characters):")
    lines.append(text)
    return "\n".join(lines)

@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    from starlette.responses import JSONResponse
    try:
        p = await pool()
        counts = await p.fetchrow("""
            SELECT
              (SELECT count(*) FROM works) AS works,
              (SELECT count(*) FROM editions) AS editions,
              (SELECT count(*) FROM segments) AS segments,
              (SELECT count(*) FROM source_links) AS source_links,
              (SELECT max(imported_at) FROM ingestion_manifest) AS last_imported_at,
              (SELECT pg_encoding_to_char(encoding) FROM pg_database WHERE datname=current_database()) AS encoding
        """)
        payload = dict(counts)
        if payload["last_imported_at"] is not None:
            payload["last_imported_at"] = payload["last_imported_at"].isoformat()
        payload["schema_version"] = await schema_version(p)
        return JSONResponse({"status": "ok", "service": "midrash-mcp", **payload})
    except Exception:
        logger.exception("Health check failed")
        return JSONResponse({"status": "error", "service": "midrash-mcp"}, status_code=503)

@mcp.tool()
async def list_midrash_works(language: str | None = None) -> str:
    """List imported Midrash works and edition/language coverage."""
    p = await pool()
    if language:
        rows = await p.fetch("""
            SELECT w.sefaria_title, w.hebrew_title, w.corpus, w.categories,
                   e.language, e.version_title, e.license, count(s.id) AS segments
            FROM works w JOIN editions e ON e.work_id=w.id
            LEFT JOIN segments s ON s.edition_id=e.id
            WHERE e.language=$1
            GROUP BY w.id,e.id ORDER BY w.sefaria_title,e.language,e.version_title
        """, language)
    else:
        rows = await p.fetch("""
            SELECT w.sefaria_title, w.hebrew_title, w.corpus, w.categories,
                   e.language, e.version_title, e.license, count(s.id) AS segments
            FROM works w JOIN editions e ON e.work_id=w.id
            LEFT JOIN segments s ON s.edition_id=e.id
            GROUP BY w.id,e.id ORDER BY w.sefaria_title,e.language,e.version_title
        """)
    if not rows:
        return "No Midrash works have been imported."
    lines = ["## Imported Midrash works", ""]
    for r in rows:
        lines.append(
            f"- **{r['sefaria_title']}** ({r['language']}) — {r['version_title']} "
            f"[{r['segments']} segments; {r['license'] or 'license unspecified'}]"
        )
    return "\n".join(lines)

@mcp.tool()
async def get_corpus_summary(work: str | None = None, corpus: str | None = None,
                             language: str | None = None, limit: int = 100) -> str:
    """Return corpus coverage, edition health, and import-quality signals."""
    p = await pool()
    limit = max(1, min(limit, 100))
    filters = []
    params: list[Any] = []
    n = 1
    if work:
        filters.append(f"w.sefaria_title ILIKE ${n}"); params.append(f"%{work}%"); n += 1
    if corpus:
        filters.append(f"w.corpus = ${n}"); params.append(corpus); n += 1
    if language:
        filters.append(f"e.language = ${n}"); params.append(language); n += 1
    where = " AND ".join(filters) or "TRUE"
    params.append(limit)
    per_work = await p.fetch(f"""
        SELECT w.sefaria_title,w.hebrew_title,w.corpus,w.categories,
               count(DISTINCT e.id) AS editions,
               count(DISTINCT s.id) AS segments,
               array_agg(DISTINCT e.language ORDER BY e.language) FILTER (WHERE e.id IS NOT NULL) AS languages,
               count(DISTINCT e.id) FILTER (WHERE e.is_source) AS source_editions,
               count(DISTINCT e.id) FILTER (WHERE e.is_primary) AS primary_editions,
               max(m.imported_at) AS last_imported_at
        FROM works w
        LEFT JOIN editions e ON e.work_id=w.id
        LEFT JOIN segments s ON s.edition_id=e.id
        LEFT JOIN ingestion_manifest m ON m.edition_id=e.id
        WHERE {where}
        GROUP BY w.id
        ORDER BY w.sefaria_title
        LIMIT ${n}
    """, *params)
    if not per_work:
        return "No corpus entries match the requested filters."

    language_rows = await p.fetch(f"""
        SELECT e.language,count(DISTINCT e.id) AS editions,count(DISTINCT s.id) AS segments
        FROM works w JOIN editions e ON e.work_id=w.id
        LEFT JOIN segments s ON s.edition_id=e.id
        WHERE {where}
        GROUP BY e.language ORDER BY e.language
    """, *params[:-1])
    quality = await p.fetchrow(f"""
        SELECT
          (SELECT count(*) FROM editions WHERE metadata->>'content_sha256' IS NULL) AS editions_missing_sha256,
          (SELECT count(*) FROM editions e WHERE NOT EXISTS (SELECT 1 FROM segments s WHERE s.edition_id=e.id)) AS empty_editions,
          (SELECT count(*) FROM ingestion_manifest m WHERE NOT EXISTS (SELECT 1 FROM editions e WHERE e.id=m.edition_id)) AS manifest_without_edition,
          (SELECT count(*) FROM ingestion_manifest m WHERE m.segment_count != (SELECT count(*) FROM segments s WHERE s.edition_id=m.edition_id)) AS manifest_mismatches
    """)
    total_editions = sum(int(row["editions"]) for row in per_work)
    total_segments = sum(int(row["segments"]) for row in per_work)
    lines = [
        f"## Midrash corpus summary (schema {await schema_version(p)})",
        f"Works returned: {len(per_work)} | Editions: {total_editions} | Segments: {total_segments}",
        "",
        "### Per-work coverage",
    ]
    for row in per_work:
        lines.append(
            f"- **{row['sefaria_title']}** ({row['corpus'] or 'uncategorized'}): "
            f"{row['editions']} editions, {row['segments']} segments; "
            f"languages={', '.join(row['languages'] or []) or 'none'}; "
            f"source_editions={row['source_editions']}; primary_editions={row['primary_editions']}; "
            f"last_import={row['last_imported_at'] or 'not recorded'}"
        )
    lines.append("\n### Language breakdown")
    lines.extend(f"- {row['language']}: {row['editions']} editions, {row['segments']} segments" for row in language_rows)
    lines.extend([
        "\n### Quality signals",
        f"- Editions missing content hash: {quality['editions_missing_sha256']}",
        f"- Empty editions: {quality['empty_editions']}",
        f"- Manifest rows without edition: {quality['manifest_without_edition']}",
        f"- Manifest segment-count mismatches: {quality['manifest_mismatches']}",
    ])
    if int(quality['editions_missing_sha256']) or int(quality['empty_editions']) or int(quality['manifest_without_edition']) or int(quality['manifest_mismatches']):
        lines.append("Warning: one or more corpus quality signals require review.")
    else:
        lines.append("Quality status: no missing editions, manifest links, or segment-count mismatches detected.")
    return "\n".join(lines)

@mcp.tool()
async def search_midrash(query: str, work: str | None = None, category: str | None = None,
                         corpus: str | None = None, language: str | None = None,
                         phrase: bool = False, limit: int = 10) -> str:
    """Search Midrash with exact-reference, phrase, corpus, and language filters.

    Exact Sefaria references are resolved before full-text search. Set phrase=true
    for an ordered phrase search; otherwise PostgreSQL's lexical search is used.
    """
    raw_query = query.strip()
    limit = max(1, min(limit, 50))
    if not raw_query:
        return "Provide a search query or Sefaria reference."
    p = await pool()

    # Exact reference lookup gets priority over lexical search and works even when
    # the reference contains punctuation that search-token cleaning would remove.
    exact_filters = ["s.sefaria_ref = $1"]
    exact_params: list[Any] = [raw_query]
    n = 2
    if work:
        exact_filters.append(f"w.sefaria_title ILIKE ${n}"); exact_params.append(f"%{work}%"); n += 1
    if category:
        exact_filters.append(f"${n} = ANY(w.categories)"); exact_params.append(category); n += 1
    if corpus:
        exact_filters.append(f"w.corpus = ${n}"); exact_params.append(corpus); n += 1
    if language:
        exact_filters.append(f"e.language = ${n}"); exact_params.append(language); n += 1
    exact_params.append(limit)
    rows = await p.fetch(f"""
        SELECT {PREVIEW_COLUMNS}
        FROM segments s JOIN works w ON w.id=s.work_id JOIN editions e ON e.id=s.edition_id
        WHERE {' AND '.join(exact_filters)}
        ORDER BY e.is_primary DESC NULLS LAST, e.language, e.version_title
        LIMIT ${n}
    """, *exact_params)
    if rows:
        return "## Exact Midrash reference\n\n" + "\n\n---\n\n".join(format_result(dict(r), preview=True) for r in rows)

    # PostgreSQL on this host is SQL_ASCII. Route Hebrew through a Unicode-aware
    # Python normalizer rather than risking a server-side encoding error.
    if contains_hebrew(raw_query):
        try:
            hebrew_rows = await search_hebrew_in_python(p, raw_query, work, category, corpus, language, phrase, limit)
        except ValueError as exc:
            return str(exc)
        if not hebrew_rows:
            return f"No Hebrew Midrash results found for '{raw_query}'."
        return "## Hebrew-normalized search results\n\n" + "\n\n---\n\n".join(format_result(row, preview=True) for row in hebrew_rows)

    cleaned = clean_query(raw_query)
    if not cleaned:
        return "Provide a search query containing letters or numbers."
    tsquery = "phraseto_tsquery('simple', $1)" if phrase else "plainto_tsquery('simple', $1)"
    filters = [f"s.search_vector @@ {tsquery}"]
    params: list[Any] = [cleaned]
    n = 2
    if work:
        filters.append(f"w.sefaria_title ILIKE ${n}"); params.append(f"%{work}%"); n += 1
    if category:
        filters.append(f"${n} = ANY(w.categories)"); params.append(category); n += 1
    if corpus:
        filters.append(f"w.corpus = ${n}"); params.append(corpus); n += 1
    if language:
        filters.append(f"e.language = ${n}"); params.append(language); n += 1
    params.append(limit)
    rows = await p.fetch(f"""
        SELECT {PREVIEW_COLUMNS},
               ts_rank_cd(s.search_vector, {tsquery}) AS relevance
        FROM segments s JOIN works w ON w.id=s.work_id JOIN editions e ON e.id=s.edition_id
        WHERE {' AND '.join(filters)}
        ORDER BY relevance DESC, e.is_primary DESC NULLS LAST, s.sefaria_ref
        LIMIT ${n}
    """, *params)
    if not rows:
        mode = "phrase " if phrase else ""
        return f"No {mode}Midrash results found for '{raw_query}'."
    title = "Phrase search results" if phrase else "Midrash search results"
    return f"## {title}\n\n" + "\n\n---\n\n".join(format_result(dict(r), preview=True) for r in rows)

@mcp.tool()
async def get_midrash_text(ref: str, language: str = "en", edition: str | None = None) -> str:
    """Retrieve the exact text for a Sefaria reference and language/edition."""
    p = await pool()
    if edition:
        row = await p.fetchrow(f"""
            SELECT {FULL_COLUMNS}
            FROM segments s JOIN works w ON w.id=s.work_id JOIN editions e ON e.id=s.edition_id
            WHERE s.sefaria_ref=$1 AND e.language=$2 AND e.version_title ILIKE $3 LIMIT 1
        """, ref, language, f"%{edition}%")
    else:
        row = await p.fetchrow(f"""
            SELECT {FULL_COLUMNS}
            FROM segments s JOIN works w ON w.id=s.work_id JOIN editions e ON e.id=s.edition_id
            WHERE s.sefaria_ref=$1 AND e.language=$2
            ORDER BY e.is_primary DESC NULLS LAST, e.version_title LIMIT 1
        """, ref, language)
    if not row:
        return f"Reference not found: {ref} ({language}). Use list_midrash_works or search_midrash first."
    return format_result(dict(row))

@mcp.tool()
async def get_midrash_parallel(ref: str, english_edition: str | None = None,
                                hebrew_edition: str | None = None,
                                include_sources: bool = True, source_limit: int = 10) -> str:
    """Return Hebrew and English text for one Sefaria ref with edition provenance.

    The two texts are retrieved independently because Sefaria editions can have
    different coverage. If one language is unavailable, the result says so rather
    than treating another edition as a translation.
    """
    p = await pool()
    source_limit = max(0, min(source_limit, 25))

    async def fetch(language: str, requested_edition: str | None):
        if requested_edition:
            return await p.fetchrow(f"""
                SELECT {FULL_COLUMNS}
                FROM segments s
                JOIN works w ON w.id=s.work_id
                JOIN editions e ON e.id=s.edition_id
                WHERE s.sefaria_ref=$1 AND e.language=$2
                  AND e.version_title ILIKE $3
                ORDER BY e.is_primary DESC NULLS LAST, e.version_title
                LIMIT 1
            """, ref, language, f"%{requested_edition}%")
        return await p.fetchrow(f"""
            SELECT {FULL_COLUMNS}
            FROM segments s
            JOIN works w ON w.id=s.work_id
            JOIN editions e ON e.id=s.edition_id
            WHERE s.sefaria_ref=$1 AND e.language=$2
            ORDER BY e.is_primary DESC NULLS LAST, e.version_title
            LIMIT 1
        """, ref, language)

    english = await fetch("en", english_edition)
    hebrew = await fetch("he", hebrew_edition)
    if not english and not hebrew:
        return f"Reference not found in either language: {ref}. Use search_midrash first."

    lines = [f"## Parallel Midrash text: {ref}", ""]
    if english:
        lines.extend(["### English", format_result(dict(english)), ""])
    else:
        lines.extend(["### English", f"No English edition is available for `{ref}`.", ""])

    if hebrew:
        lines.extend(["### Hebrew", format_result(dict(hebrew)), ""])
    else:
        lines.extend(["### Hebrew", f"No Hebrew edition is available for `{ref}`.", ""])

    if include_sources:
        related = await p.fetch("""
            SELECT source_ref, target_ref, link_type
            FROM source_links
            WHERE source_ref=$1 OR target_ref=$1
            ORDER BY CASE WHEN link_type IN ('quotation','midrash','commentary') THEN 0 ELSE 1 END, id
            LIMIT $2
        """, ref, source_limit)
        lines.append("### Related Sefaria sources")
        if related:
            lines.extend(f"- {r['source_ref']} → {r['target_ref']} ({r['link_type'] or 'link'})" for r in related)
        else:
            lines.append("No imported related sources found.")
    return "\n".join(lines)

@mcp.tool()
async def list_midrash_editions(work: str) -> str:
    """List editions and their licence/import provenance for matching works."""
    p = await pool()
    rows = await p.fetch("""
        SELECT w.sefaria_title,e.id AS edition_id,e.language,e.version_title,e.version_source,e.license,
               e.is_source,e.is_primary,e.metadata,count(s.id) AS segments
        FROM works w JOIN editions e ON e.work_id=w.id LEFT JOIN segments s ON s.edition_id=e.id
        WHERE w.sefaria_title ILIKE $1 GROUP BY w.id,e.id ORDER BY w.sefaria_title,e.language,e.version_title
    """, f"%{work}%")
    if not rows:
        return f"No imported work matches '{work}'."
    lines = [f"## Editions matching {work}", ""]
    for row in rows:
        metadata = metadata_dict(row["metadata"])
        status = metadata.get("licence_status") or "not recorded"
        lines.append(
            f"- **{row['sefaria_title']}** — edition {row['edition_id']}; {row['language']}: **{row['version_title']}**; "
            f"{row['segments']} segments; source={bool(row['is_source'])}; primary={bool(row['is_primary'])}; "
            f"license={row['license'] or 'unspecified'}; licence_status={status}; "
            f"version_source={row['version_source'] or 'not recorded'}"
        )
    return "\n".join(lines)

@mcp.tool()
async def get_midrash_metadata(work: str, exact_title: bool = False) -> str:
    """Return human-readable work and edition provenance; exact_title disambiguates matches."""
    p = await pool()
    operator = "=" if exact_title else "ILIKE"
    value = work if exact_title else f"%{work}%"
    rows = await p.fetch(f"""
        SELECT id,sefaria_title,hebrew_title,categories,corpus,description,source_url,discovered_at,metadata
        FROM works WHERE sefaria_title {operator} $1 ORDER BY sefaria_title LIMIT 20
    """, value)
    if not rows:
        return f"No imported work matches '{work}'."
    lines = [f"## Work provenance for {work} (matched {len(rows)})", ""]
    for row in rows:
        r = dict(row)
        lines.extend([
            f"### {r['sefaria_title']} (work id {r['id']})",
            f"Hebrew title: {r.get('hebrew_title') or 'not recorded'}",
            f"Corpus: {r.get('corpus') or 'not recorded'} | Categories: {', '.join(r.get('categories') or []) or 'not recorded'}",
            f"Description: {r.get('description') or 'not recorded'}",
            f"Sefaria source: {r.get('source_url') or 'not recorded'}",
            f"Discovered: {r.get('discovered_at')}",
        ])
        work_meta = metadata_dict(r.get("metadata"))
        useful = {key: work_meta[key] for key in ("era", "composition_date", "publication_date", "authors", "metadata_source") if work_meta.get(key)}
        if useful:
            lines.append("Work metadata: " + compact_json(useful))
        editions = await p.fetch("""
            SELECT id,language,version_title,version_source,license,is_source,is_primary,metadata
            FROM editions WHERE work_id=$1 ORDER BY language,version_title
        """, r["id"])
        lines.append("Editions:")
        for edition in editions:
            e = dict(edition)
            meta = metadata_dict(e.get("metadata"))
            lines.append(
                f"- edition {e['id']}: {e['language']} / {e['version_title']}; license={e['license'] or 'not specified'}; "
                f"source={e['version_source'] or 'not recorded'}; source_edition={bool(e['is_source'])}; primary={bool(e['is_primary'])}; "
                f"import={meta.get('export_generated_at') or 'not recorded'}; licence_status={meta.get('licence_status') or 'not recorded'}"
            )
    return "\n".join(lines)

@mcp.tool()
async def get_import_history(work: str | None = None, limit: int = 50) -> str:
    """List ingestion batches with exact source URLs, timestamps, counts, and hashes."""
    p = await pool()
    limit = max(1, min(limit, 200))
    if work:
        rows = await p.fetch("""
            SELECT m.work_title,m.language,m.version_title,m.source_url,m.export_generated_at,m.imported_at,m.segment_count,
                   e.id AS edition_id,e.metadata
            FROM ingestion_manifest m
            LEFT JOIN works w ON w.sefaria_title=m.work_title
            LEFT JOIN editions e ON e.work_id=w.id AND e.language=m.language AND e.version_title=m.version_title
            WHERE m.work_title ILIKE $1 ORDER BY m.imported_at DESC LIMIT $2
        """, f"%{work}%", limit)
    else:
        rows = await p.fetch("""
            SELECT m.work_title,m.language,m.version_title,m.source_url,m.export_generated_at,m.imported_at,m.segment_count,
                   e.id AS edition_id,e.metadata
            FROM ingestion_manifest m
            LEFT JOIN works w ON w.sefaria_title=m.work_title
            LEFT JOIN editions e ON e.work_id=w.id AND e.language=m.language AND e.version_title=m.version_title
            ORDER BY m.imported_at DESC LIMIT $1
        """, limit)
    if not rows:
        return "No ingestion history recorded."
    lines = [f"## Midrash import history ({len(rows)} records)", ""]
    for row in rows:
        meta = metadata_dict(row["metadata"])
        lines.append(
            f"- {row['work_title']} / {row['language']} / {row['version_title']} (edition {row['edition_id'] or 'unknown'}): "
            f"{row['segment_count']} segments; export={row['export_generated_at']}; imported={row['imported_at']}; "
            f"sha256={meta.get('content_sha256') or 'not recorded'}; source={row['source_url']}"
        )
    return "\n".join(lines)

@mcp.tool()
async def get_related_sources(ref: str, link_type: str | None = None,
                              offset: int = 0, limit: int = 20,
                              detail: bool = True) -> str:
    """List imported Sefaria links with source-export provenance and pagination."""
    p = await pool()
    offset = max(0, offset)
    limit = max(1, min(limit, 50))
    filters = ["(source_ref=$1 OR target_ref=$1)"]
    params: list[Any] = [ref]
    n = 2
    if link_type:
        filters.append(f"link_type=${n}")
        params.append(link_type)
        n += 1
    params.extend([limit, offset])
    rows = await p.fetch(f"""
        SELECT source_ref,target_ref,link_type,metadata
        FROM source_links
        WHERE {' AND '.join(filters)}
        ORDER BY CASE WHEN link_type IN ('quotation','midrash','commentary') THEN 0 ELSE 1 END, id
        LIMIT ${n} OFFSET ${n + 1}
    """, *params)
    if not rows:
        return f"No imported source links found for {ref} at offset {offset}."
    lines = [f"## Related Sefaria sources for {ref} (offset {offset}, returned {len(rows)})", ""]
    for row in rows:
        line = f"- {row['source_ref']} → {row['target_ref']} ({row['link_type'] or 'link'})"
        if detail:
            metadata = metadata_dict(row["metadata"])
            details = []
            for key in ("midrash_work", "source_export", "citation_1", "citation_2", "category_1", "category_2"):
                if metadata.get(key):
                    details.append(f"{key}={metadata[key]}")
            for key in ("text_1", "text_2"):
                if metadata.get(key):
                    value = str(metadata[key])
                    details.append(f"{key}={value[:280]}{'…' if len(value) > 280 else ''}")
            if details:
                line += "\n  Provenance: " + "; ".join(details)
        lines.append(line)
    return "\n".join(lines)

if __name__ == "__main__":
    mcp.run("streamable-http")
