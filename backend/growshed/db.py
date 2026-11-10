"""SQLite storage: connection setup, numbered-SQL migrations, key/value settings.

SQLite calls here are synchronous. They are tiny local operations, so we call them
directly from async handlers rather than adding a thread pool or an async driver.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def connect(path: str | Path) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # readers never block the writer
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def migrate(conn: sqlite3.Connection, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply every not-yet-applied NNN_name.sql file in order. Returns the names applied."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migration (name TEXT PRIMARY KEY, applied_at INTEGER)"
    )
    done = {row["name"] for row in conn.execute("SELECT name FROM schema_migration")}
    applied = []
    for path in sorted(migrations_dir.glob("*.sql")):
        if path.name in done:
            continue
        conn.executescript(path.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO schema_migration (name, applied_at) VALUES (?, strftime('%s','now'))",
            (path.name,),
        )
        conn.commit()
        applied.append(path.name)
    return applied


def get_setting(conn: sqlite3.Connection, key: str, default: str) -> str:
    row = conn.execute("SELECT value FROM setting WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO setting (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
