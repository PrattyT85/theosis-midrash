-- Add an indexed normalization path for Hebrew Midrash search.
-- Run as the database owner on a UTF-8 database.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE OR REPLACE FUNCTION public.midrash_normalize_hebrew(value text)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
    SELECT regexp_replace(
        regexp_replace(
            translate(coalesce(value, ''), 'ךםןףץ', 'כמנפצ'),
            '[' || chr(1425) || '-' || chr(1479) || ']', '', 'g'
        ),
        '\s+', ' ', 'g'
    )
$$;

CREATE INDEX IF NOT EXISTS segments_hebrew_search_trgm_idx
ON public.segments
USING gin (public.midrash_normalize_hebrew(text) gin_trgm_ops);
