# Theosis Midrash MCP

A separate MCP server and PostgreSQL corpus for Jewish Midrash, built alongside the Theosis Bible research system.

This repository contains the **code, schema, and repeatable import pipeline**. It does not contain Sefaria's exported corpus or a database dump of the text. The importer downloads the selected editions from Sefaria's structured export when run.

## Current deployment

The live instance runs separately from Theosis:

- PostgreSQL database: `midrash`
- MCP endpoint: `http://<host>:8001/mcp`
- Theosis remains on port `8000`
- Open WebUI can connect to both MCP endpoints independently

The service preserves work, edition, language, Sefaria reference, licence, source URL, and ingestion metadata rather than flattening all text into one table.

## Current corpus snapshot

The live deployment currently contains:

- 21 works
- 45 editions
- 29,367 segments
- 458,969 source links

These values are an operational snapshot and will change as the corpus is expanded.

## MCP tools

The server exposes:

- `list_midrash_works`
- `get_midrash_text`
- `search_midrash`
- `list_midrash_editions`
- `get_related_sources`
- `get_midrash_metadata`

Results identify the exact work, Sefaria reference, edition, language, licence, and source URL where available.

## Requirements

- PostgreSQL 16 or newer
- Python 3.11 or newer
- `asyncpg`
- `psycopg2-binary`
- MCP Python SDK
- Network access to the Sefaria Export bucket for ingestion

A UTF-8 database is recommended for a new installation. The original live database uses `SQL_ASCII` and the importer explicitly controls client encoding and Hebrew search normalization for that deployment.

## Installation

Create the database and apply the schema as a PostgreSQL administrator:

```bash
sudo -u postgres psql <<'SQL'
CREATE ROLE midrash LOGIN;
CREATE DATABASE midrash OWNER midrash;
SQL
sudo -u postgres psql -d midrash -f schema.sql
```

If the role or database already exists, skip the corresponding creation statement.

Create an environment and install dependencies:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
export MIDRASH_DATABASE_URL='postgresql://midrash@/midrash?host=/var/run/postgresql'
```

Import the initial bilingual corpus:

```bash
python scripts/midrash_import.py
```

Then expand and enrich it in bounded stages:

```bash
python scripts/midrash_expand.py
python scripts/midrash_megillot_expand.py
python scripts/midrash_shimon_upgrade.py
python scripts/midrash_metadata_upgrade.py
python scripts/midrash_links_import.py
python scripts/midrash_fix_refs.py
```

The later scripts are repeatable upgrades, but review their source and the Sefaria export metadata before running them against an existing database.

Start the MCP server:

```bash
export MIDRASH_DATABASE_URL='postgresql://midrash@/midrash?host=/var/run/postgresql'
python scripts/midrash_server.py
```

For a systemd deployment, use `deploy/midrash.service` as a template. Change the paths, service account, and environment file for the target host. Do not expose the database directly to the network.

## Open WebUI

Add a second MCP Streamable HTTP connection:

```text
http://<host>:8001/mcp
```

Keep the original Theosis connection on port `8000`. The Midrash service is a separate research corpus and should not be mixed into Theosis' `extra_biblical_texts` table.

## Data and licensing

Bulk ingestion uses Sefaria's structured Export/GCS corpus. The repository records the edition title, source URL, language, and licence metadata where available. Do not redistribute downloaded editions without checking the licence for that specific edition. A merged edition may contain multiple source licences and is recorded as `Mixed/see metadata` where appropriate.

## Security notes

The original live service runs as root and listens on `0.0.0.0:8001`. For a new deployment, run it under a dedicated Unix account, use systemd sandboxing, and restrict access to the Open WebUI/Hermes clients or bind to the required LAN address only.

## Source design

See `schema.sql` and `docs/live-inventory.md`. The design notes preserve edition identity, exact Sefaria references, bilingual coverage, and related-source provenance.
