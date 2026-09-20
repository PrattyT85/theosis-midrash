# Live Midrash inventory

This is a snapshot of the Midrash deployment on CT125 recorded during repository separation. It is not a substitute for querying the live database.

## Service

- systemd unit: `midrash.service`
- endpoint: `192.168.1.130:8001/mcp`
- service user: `midrash`
- deployed repository commit: `fe91d3f`
- schema migration version: `001`
- database: `midrash` (UTF-8)
- legacy rollback database: `midrash_sqlascii_legacy`
- source service file is `/etc/systemd/system/midrash.service`

## Database counts

| Table | Rows |
|---|---:|
| `works` | 21 |
| `editions` | 45 |
| `segments` | 29,367 |
| `source_links` | 594,373 |
| `ingestion_manifest` | 45 |

The live `midrash` database is now UTF-8. It has the `segments_hebrew_search_trgm_idx` expression index for normalized Hebrew search. The former SQL_ASCII database is retained as `midrash_sqlascii_legacy` for rollback until the migration is fully signed off.

## Source snapshot

The importer records the Sefaria Export timestamp used by the current scripts as `2026-09-07T11:53:39Z`. Source data is not committed to this repository. Re-run the importers to acquire current exports and preserve the metadata/licence fields returned by Sefaria.
