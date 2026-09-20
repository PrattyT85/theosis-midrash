-- Add direct ingestion provenance and enforce one canonical edition per work.

ALTER TABLE public.ingestion_manifest
    ADD COLUMN IF NOT EXISTS edition_id bigint,
    ADD COLUMN IF NOT EXISTS content_sha256 text;

DO $migration$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.ingestion_manifest m
        LEFT JOIN public.works w ON w.sefaria_title = m.work_title
        LEFT JOIN public.editions e
          ON e.work_id = w.id
         AND e.language = m.language
         AND e.version_title = m.version_title
        WHERE e.id IS NULL
    ) THEN
        RAISE EXCEPTION 'ingestion_manifest contains rows without a matching edition';
    END IF;
END
$migration$;

UPDATE public.ingestion_manifest m
SET edition_id = e.id,
    content_sha256 = COALESCE(m.content_sha256, e.metadata->>'content_sha256')
FROM public.works w, public.editions e
WHERE w.sefaria_title = m.work_title
  AND e.work_id = w.id
  AND e.language = m.language
  AND e.version_title = m.version_title;

ALTER TABLE public.ingestion_manifest
    ALTER COLUMN edition_id SET NOT NULL;

DO $migration$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ingestion_manifest_edition_id_fkey'
    ) THEN
        ALTER TABLE public.ingestion_manifest
            ADD CONSTRAINT ingestion_manifest_edition_id_fkey
            FOREIGN KEY (edition_id) REFERENCES public.editions(id) ON DELETE CASCADE;
    END IF;
END
$migration$;

CREATE INDEX IF NOT EXISTS ingestion_manifest_edition_idx
    ON public.ingestion_manifest (edition_id, imported_at DESC);

WITH ranked AS (
    SELECT e.id,
           row_number() OVER (
               PARTITION BY e.work_id
               ORDER BY
                   CASE
                       WHEN e.language = 'en' AND e.version_title ILIKE '%Sefaria Community Translation%' THEN 0
                       WHEN e.language = 'en' THEN 1
                       WHEN e.is_source THEN 2
                       ELSE 3
                   END,
                   e.version_title,
                   e.id
           ) AS rank
    FROM public.editions e
)
UPDATE public.editions e
SET is_primary = (ranked.rank = 1)
FROM ranked
WHERE ranked.id = e.id;

CREATE UNIQUE INDEX IF NOT EXISTS editions_one_primary_per_work_idx
    ON public.editions (work_id)
    WHERE is_primary;
