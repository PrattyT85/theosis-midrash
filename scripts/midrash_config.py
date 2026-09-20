"""Shared runtime configuration for Midrash import and server tools."""
from __future__ import annotations

import os

DEFAULT_DATABASE_URL = "postgresql://midrash@/midrash?host=/var/run/postgresql"


def database_url(value: str | None = None) -> str:
    """Return an explicit DSN, then the environment DSN, then the local default."""
    return value or os.environ.get("MIDRASH_DATABASE_URL", DEFAULT_DATABASE_URL)
