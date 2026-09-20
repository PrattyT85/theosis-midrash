# Live Midrash inventory

This is a snapshot of the Midrash deployment on CT125 recorded during repository separation. It is not a substitute for querying the live database.

## Service

- systemd unit: `midrash.service`
- endpoint: `0.0.0.0:8001/mcp`
- database: `midrash`
- source service file was `/etc/systemd/system/midrash.service`

## Database counts

| Table | Rows |
|---|---:|
| `works` | 21 |
| `editions` | 45 |
| `segments` | 29,367 |
| `source_links` | 458,969 |
| `ingestion_manifest` | 45 |

The live database was approximately 391 MB and used `SQL_ASCII`; new deployments should use UTF-8 where possible.

## Source snapshot

The importer records the Sefaria Export timestamp used by the current scripts as `2026-09-07T11:53:39Z`. Source data is not committed to this repository. Re-run the importers to acquire current exports and preserve the metadata/licence fields returned by Sefaria.
