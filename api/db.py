import os
from contextlib import contextmanager
from pathlib import Path
import hashlib

import psycopg
from psycopg.rows import dict_row

from authority_errors import DatabaseUnavailable

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()


def require_database_url() -> str:
    if not DATABASE_URL:
        raise DatabaseUnavailable("Database is not configured")
    return DATABASE_URL


@contextmanager
def get_conn():
    with psycopg.connect(require_database_url(), row_factory=dict_row, connect_timeout=5) as conn:
        conn.execute("SET statement_timeout = '10s'")
        conn.execute("SET lock_timeout = '5s'")
        yield conn


def init_db() -> None:
    """Apply checked-in migrations atomically, serialized across API replicas."""
    root = Path(__file__).resolve().parent.parent / "db" / "migrations"
    if not root.is_dir():
        raise DatabaseUnavailable("Database migrations are not packaged")
    with get_conn() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(781202602)")
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, sha256 TEXT NOT NULL)")
        applied = {row["name"]: row["sha256"] for row in conn.execute("SELECT name, sha256 FROM schema_migrations").fetchall()}
        for path in sorted(root.glob("*.sql")):
            source = path.read_bytes()
            digest = hashlib.sha256(source).hexdigest()
            if path.name in applied:
                if applied[path.name] != digest:
                    raise DatabaseUnavailable("Applied migration checksum changed")
                continue
            conn.execute(source.decode("utf-8"), prepare=False)
            conn.execute("INSERT INTO schema_migrations (name, sha256) VALUES (%s, %s)", (path.name, digest))
