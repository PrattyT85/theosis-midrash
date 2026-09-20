import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from migrate import discover_migrations  # noqa: E402


def test_migrations_are_ordered_and_have_stable_checksums():
    migrations = discover_migrations(Path(__file__).parents[1] / "migrations")
    assert [migration.version for migration in migrations] == ["001", "002"]
    assert all(len(migration.checksum) == 64 for migration in migrations)
    assert migrations[0].name == "hebrew_search_index"
    assert migrations[1].name == "ingestion_provenance_primary"


def test_migration_sql_is_not_empty():
    migration = discover_migrations(Path(__file__).parents[1] / "migrations")[0]
    assert "CREATE EXTENSION IF NOT EXISTS pg_trgm" in migration.sql
    assert "segments_hebrew_search_trgm_idx" in migration.sql
