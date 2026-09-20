#!/usr/bin/env python3
"""Midrash MCP service backed by PostgreSQL and Sefaria Export data."""
from __future__ import annotations

import os
import re
from typing import Any

import asyncpg
from mcp.server.fastmcp import FastMCP

DB_URL = os.environ.get("MIDRASH_DATABASE_URL", "postgresql://midrash@/midrash?host=/var/run/postgresql")

mcp = FastMCP(
    "midrash",
    instructions=(
        "Search and retrieve Jewish Midrash from Sefaria editions. "
        "Always cite the exact work, Sefaria reference, language, version title, "
        "license, and source URL returned by the tools. Midrash is interpretive "
        "literature; do not present it as the plain biblical text."
    ),
    host="0.0.0.0",
    port=8001,
    streamable_http_path="/mcp",
    stateless_http=True,
)

_pool: asyncpg.Pool | None = None

async def pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DB_URL, min_size=1, max_size=8, command_timeout=30)
    return _pool


def clean(value: str) -> str:
    # Remove Sefaria footnote elements and markers while retaining prose.
    value = re.sub(r'<i class="footnote">.*?</i>', "", value or "", flags=re.IGNORECASE | re.DOTALL)
    value = re.sub(r'<sup class="footnote-marker">.*?</sup>', "", value, flags=re.IGNORECASE | re.DOTALL)
    value = re.sub(r"<[^>]+>", "", value)
    value = value.replace("&nbsp;", " ").replace("&amp;", "&")
    value = value.replace("&quot;", '"').replace("&#39;", "'")
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
    """Search Hebrew in Python because CT125 is SQL_ASCII and cannot safely
    apply Unicode normalization inside PostgreSQL."""
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
    where = " AND ".join(filters) or "TRUE"
    rows = await p.fetch(f"""
        SELECT s.sefaria_ref, s.text, w.sefaria_title AS work_title,
               e.language, e.version_title, e.license, e.version_source AS source_url
        FROM segments s JOIN works w ON w.id=s.work_id JOIN editions e ON e.id=s.edition_id
        WHERE {where}
    """, *params)
    wanted = normalize_hebrew(query)
    scored = []
    for row in rows:
        text = normalize_hebrew(row["text"])
        if phrase:
            score = text.count(wanted) if wanted else 0
        else:
            terms = [normalize_hebrew(term) for term in query.split() if term]
            score = sum(text.count(term) for term in terms)
        if score:
            item = dict(row); item["_score"] = score; scored.append(item)
    scored.sort(key=lambda item: (-item["_score"], item["sefaria_ref"]))
    return scored[:limit]



def row_dict(row: asyncpg.Record | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def format_result(row: dict[str, Any]) -> str:
    return (
        f"**{row['sefaria_ref']}** — {row['work_title']}\n"
        f"Language: {row['language']} | Edition: {row['version_title']}\n"
        f"License: {row.get('license') or 'Not specified'}\n"
        f"Source: {row.get('source_url') or 'https://www.sefaria.org/'}\n\n"
        f"{row['text']}"
    )

@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    from starlette.responses import JSONResponse
    try:
        p = await pool()
        count = await p.fetchval("SELECT count(*) FROM segments")
        return JSONResponse({"status": "ok", "service": "midrash-mcp", "segments": count})
    except Exception as exc:
        return JSONResponse({"status": "error", "error": str(exc)}, status_code=503)

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
        SELECT s.sefaria_ref, left(s.text, 900) AS text, w.sefaria_title AS work_title,
               e.language, e.version_title, e.license, e.version_source AS source_url
        FROM segments s JOIN works w ON w.id=s.work_id JOIN editions e ON e.id=s.edition_id
        WHERE {' AND '.join(exact_filters)}
        ORDER BY e.is_primary DESC NULLS LAST, e.language, e.version_title
        LIMIT ${n}
    """, *exact_params)
    if rows:
        return "## Exact Midrash reference\n\n" + "\n\n---\n\n".join(format_result(dict(r)) for r in rows)

    # PostgreSQL on this host is SQL_ASCII. Route Hebrew through a Unicode-aware
    # Python normalizer rather than risking a server-side encoding error.
    if contains_hebrew(raw_query):
        hebrew_rows = await search_hebrew_in_python(p, raw_query, work, category, corpus, language, phrase, limit)
        if not hebrew_rows:
            return f"No Hebrew Midrash results found for '{raw_query}'."
        return "## Hebrew-normalized search results\n\n" + "\n\n---\n\n".join(format_result(row) for row in hebrew_rows)

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
        SELECT s.sefaria_ref, left(s.text, 900) AS text, w.sefaria_title AS work_title,
               e.language, e.version_title, e.license, e.version_source AS source_url,
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
    return f"## {title}\n\n" + "\n\n---\n\n".join(format_result(dict(r)) for r in rows)

@mcp.tool()
async def get_midrash_text(ref: str, language: str = "en", edition: str | None = None) -> str:
    """Retrieve the exact text for a Sefaria reference and language/edition."""
    p = await pool()
    if edition:
        row = await p.fetchrow("""
            SELECT s.sefaria_ref,s.text,w.sefaria_title AS work_title,e.language,e.version_title,
                   e.license,e.version_source AS source_url
            FROM segments s JOIN works w ON w.id=s.work_id JOIN editions e ON e.id=s.edition_id
            WHERE s.sefaria_ref=$1 AND e.language=$2 AND e.version_title ILIKE $3 LIMIT 1
        """, ref, language, f"%{edition}%")
    else:
        row = await p.fetchrow("""
            SELECT s.sefaria_ref,s.text,w.sefaria_title AS work_title,e.language,e.version_title,
                   e.license,e.version_source AS source_url
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
            return await p.fetchrow("""
                SELECT s.sefaria_ref, s.text, w.sefaria_title AS work_title,
                       e.language, e.version_title, e.license,
                       e.version_source AS source_url
                FROM segments s
                JOIN works w ON w.id=s.work_id
                JOIN editions e ON e.id=s.edition_id
                WHERE s.sefaria_ref=$1 AND e.language=$2
                  AND e.version_title ILIKE $3
                ORDER BY e.is_primary DESC NULLS LAST, e.version_title
                LIMIT 1
            """, ref, language, f"%{requested_edition}%")
        return await p.fetchrow("""
            SELECT s.sefaria_ref, s.text, w.sefaria_title AS work_title,
                   e.language, e.version_title, e.license,
                   e.version_source AS source_url
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
        e = dict(english)
        lines.extend([
            "### English",
            f"Work: **{e['work_title']}**",
            f"Edition: {e['version_title']}",
            f"License: {e.get('license') or 'Not specified'}",
            f"Source: {e.get('source_url') or 'https://www.sefaria.org/'}",
            "",
            e['text'],
            "",
        ])
    else:
        lines.extend(["### English", f"No English edition is available for `{ref}`.", ""])

    if hebrew:
        h = dict(hebrew)
        lines.extend([
            "### Hebrew",
            f"Work: **{h['work_title']}**",
            f"Edition: {h['version_title']}",
            f"License: {h.get('license') or 'Not specified'}",
            f"Source: {h.get('source_url') or 'https://www.sefaria.org/'}",
            "",
            h['text'],
            "",
        ])
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
    """List editions imported for one Midrash work."""
    p = await pool()
    rows = await p.fetch("""
        SELECT w.sefaria_title,e.language,e.version_title,e.version_source,e.license,
               e.is_source,e.is_primary,count(s.id) AS segments
        FROM works w JOIN editions e ON e.work_id=w.id LEFT JOIN segments s ON s.edition_id=e.id
        WHERE w.sefaria_title ILIKE $1 GROUP BY w.id,e.id ORDER BY e.language,e.version_title
    """, f"%{work}%")
    if not rows:
        return f"No imported work matches '{work}'."
    return "## Editions\n\n" + "\n".join(
        f"- {r['language']}: **{r['version_title']}** — {r['segments']} segments; "
        f"license={r['license'] or 'unspecified'}; source={r['version_source'] or 'unspecified'}"
        for r in rows
    )

@mcp.tool()
async def get_midrash_metadata(work: str) -> str:
    """Return work metadata, categories, and source information."""
    p = await pool()
    row = await p.fetchrow("SELECT * FROM works WHERE sefaria_title ILIKE $1 LIMIT 1", f"%{work}%")
    if not row:
        return f"No imported work matches '{work}'."
    r = dict(row)
    return (f"## {r['sefaria_title']}\n\nHebrew title: {r.get('hebrew_title') or 'not recorded'}\n"
            f"Corpus: {r.get('corpus') or 'not recorded'}\nCategories: {', '.join(r['categories'] or [])}\n"
            f"Description: {r.get('description') or 'not recorded'}\n"
            f"Sefaria source: {r.get('source_url') or 'not recorded'}")

@mcp.tool()
async def get_related_sources(ref: str) -> str:
    """List imported Sefaria links associated with a reference, if available."""
    p = await pool()
    rows = await p.fetch("""
        SELECT source_ref,target_ref,link_type,metadata FROM source_links
        WHERE source_ref=$1 OR target_ref=$1 ORDER BY id LIMIT 50
    """, ref)
    if not rows:
        return f"No imported source links found for {ref}."
    return "\n".join(f"- {r['source_ref']} → {r['target_ref']} ({r['link_type'] or 'link'})" for r in rows)

if __name__ == "__main__":
    mcp.run("streamable-http")
