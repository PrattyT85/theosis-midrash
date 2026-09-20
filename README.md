# Theosis Midrash MCP

A separate PostgreSQL corpus and MCP server for Jewish Midrash, built alongside the [Theosis Bible research system](https://github.com/PrattyT85/theosis-mcp).

Theosis Midrash is **not the Bible database** and does not replace Theosis. It provides Jewish interpretive and rabbinic context with edition-level provenance, Hebrew/English coverage, Sefaria references, licences, source links, and import hashes.

## Related repositories

- [theosis-mcp](https://github.com/PrattyT85/theosis-mcp) — Bible texts, translations, Christian commentaries, lexicons, and theological research; MCP port 8000.
- **theosis-midrash** — this repository; Midrash corpus and MCP port 8001.
- [theosis-sefaria-context](https://github.com/PrattyT85/theosis-sefaria-context) — Targumim, Mishnah, Jewish commentary, Second Temple context, and on-demand Sefaria cache; MCP port 8002.

## Current live deployment

- Database: PostgreSQL `midrash` on CT125
- Endpoint: `http://192.168.1.130:8001/mcp`
- Health: `http://192.168.1.130:8001/health`
- Service: `midrash.service`
- Service account: `midrash`
- Encoding: UTF-8
- Schema migration: `002`
- Live corpus snapshot: 21 works, 45 editions, 29,367 segments, 594,373 source links

Counts are operational snapshots; use `get_corpus_summary` or `/health` for current values.

## What is included

The local corpus contains selected aggadic and halakhic Midrash, including Midrash Rabbah, Midrash Tanchuma, Pirkei DeRabbi Eliezer, Mekhilta, Sifra, Sifrei, Pesikta, Midrash Tehillim, and Midrash Mishlei. The database preserves work, edition, language, exact Sefaria reference, section path, licence, source URL, import timestamp, and content hash where available.

The live schema also includes roughly 594,000 imported Sefaria source links. The original SQL_ASCII database is retained separately as `midrash_sqlascii_legacy` for rollback; it is not the active service database.

## MCP tools

| Tool | Purpose | Main inputs |
|---|---|---|
| `list_midrash_works` | List imported works and edition/language coverage. | `language` |
| `search_midrash` | Search exact refs, English full text, or normalized Hebrew. | `query`, `work`, `category`, `corpus`, `language`, `phrase`, `limit` |
| `get_midrash_text` | Retrieve one complete passage. | `ref`, `language`, optional `edition` |
| `get_midrash_parallel` | Retrieve English and Hebrew editions side by side. | `ref`, optional edition names |
| `list_midrash_editions` | Show edition, licence, source, primary/source flags, and segment counts. | `work` |
| `get_midrash_metadata` | Show work metadata and all edition provenance. | `work`, `exact_title` |
| `get_related_sources` | Show Sefaria links and imported citation/source metadata. | `ref`, `link_type`, `offset`, `limit`, `detail` |
| `get_import_history` | Show ingestion batches, source URLs, counts, timestamps, and hashes. | optional `work`, `limit` |
| `get_corpus_summary` | Show work/language coverage and data-quality signals. | optional `work`, `corpus`, `language`, `limit` |

Results identify the source tradition. Midrash is interpretive literature and must not be presented as plain biblical text.

## Requirements

- PostgreSQL 16+
- UTF-8 database
- Python 3.11+
- `asyncpg`, `psycopg2-binary`, MCP Python SDK
- `pg_trgm` PostgreSQL extension
- Network access to Sefaria export data for ingestion

Use `requirements.lock` for deployment and `requirements-dev.lock` for development/testing.

## Fresh installation

```bash
sudo -u postgres psql <<'SQL'
CREATE ROLE midrash LOGIN;
CREATE DATABASE midrash OWNER midrash ENCODING 'UTF8' TEMPLATE template0;
SQL
sudo -u postgres psql -d midrash -f schema.sql

python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.lock
export MIDRASH_DATABASE_URL='postgresql://midrash@/midrash?host=/var/run/postgresql'

# Apply and record numbered migrations as the PostgreSQL administrator.
sudo -u postgres env MIDRASH_DATABASE_URL=postgresql:///midrash?host=/var/run/postgresql python scripts/migrate.py --status
sudo -u postgres env MIDRASH_DATABASE_URL=postgresql:///midrash?host=/var/run/postgresql python scripts/migrate.py
```

## Import workflow

The importer downloads only the approved edition manifest, hashes the raw payload, validates generated references before replacing segments, and records direct `edition_id` plus source hash in `ingestion_manifest`.

```bash
python scripts/midrash_import.py
python scripts/midrash_expand.py
python scripts/midrash_megillot_expand.py
python scripts/midrash_shimon_upgrade.py
python scripts/midrash_metadata_upgrade.py
python scripts/midrash_links_import.py
python scripts/midrash_fix_refs.py
```

All import/upgrade scripts honour `MIDRASH_DATABASE_URL`. The main importer also accepts `--db`.

The expansion scripts are intentionally bounded and should be run only after reviewing their edition/licence definitions. Take a PostgreSQL backup before bulk changes.

## Deployment

Use [deploy/midrash.service](deploy/midrash.service) as the systemd template. It runs as the dedicated `midrash` user, uses systemd sandboxing, and binds to the configured LAN address. The MCP endpoint has no application authentication; for a different network threat model, add a firewall or authenticated reverse proxy.

```bash
sudo cp deploy/midrash.service /etc/systemd/system/midrash.service
sudo systemctl daemon-reload
sudo systemctl enable --now midrash.service
curl http://127.0.0.1:8001/health
```

## Client integration

For Hermes Desktop, enable the `theosis_midrash` server in the dedicated `theosis_ai` profile. For another MCP client, add the Streamable HTTP endpoint:

```text
http://<host>:8001/mcp
```

Theosis Midrash remains separate from the Theosis endpoint on port 8000 and the Sefaria Context endpoint on port 8002.

## Schema and migration design

- [schema.sql](schema.sql) — UTF-8 baseline schema.
- [migrations/](migrations/) — numbered, checksum-tracked migrations.
- [scripts/migrate.py](scripts/migrate.py) — ordered migration runner with advisory locking.
- [docs/live-inventory.md](docs/live-inventory.md) — point-in-time live deployment snapshot.

The baseline includes the normalized Hebrew search function and trigram index. Running migration 001 afterward is idempotent and records the migration state; migration 002 adds direct ingestion provenance and enforces one primary edition per work.

## Licensing and data policy

Sefaria licences apply to individual editions and languages. The repository contains code, schema, and import definitions—not a database dump or bundled downloaded corpus. Check every edition’s licence before redistribution. Merged editions may contain mixed licences and are labelled accordingly.

## Development and verification

```bash
.venv/bin/pytest -q
.venv/bin/python -m compileall -q scripts tests
```

GitHub Actions runs the tests and compile check on Python 3.11 and 3.13.
