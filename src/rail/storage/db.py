"""SQLite database initialization, connection management, and auto-migrations."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Optional, Union

LATEST_SCHEMA_VERSION = 1


def get_default_rail_home() -> Path:
    """Return the default Rail home directory: ~/.rail/."""
    return Path.home() / ".rail"


def get_default_db_path() -> Path:
    """Return the default SQLite database path: ~/.rail/rail.db."""
    return get_default_rail_home() / "rail.db"


def connect_db(db_path: Optional[Union[str, Path]] = None) -> sqlite3.Connection:
    """Open a connection to the SQLite database and configure connection pragmas.

    If db_path is None, defaults to get_default_db_path().
    Ensures parent directories exist before connecting.
    """
    if db_path is None:
        target_path = get_default_db_path()
    elif isinstance(db_path, str) and db_path == ":memory:":
        target_path = ":memory:"
    else:
        target_path = Path(db_path).resolve()

    if isinstance(target_path, Path):
        target_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(target_path))
    else:
        conn = sqlite3.connect(target_path)

    conn.row_factory = sqlite3.Row

    # Enforce SQLite best practices
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    if target_path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL;")

    return conn


def apply_migrations(conn: sqlite3.Connection) -> int:
    """Ensure database schema is up-to-date and apply pending migrations.

    Returns the current schema version.
    """
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
            """
        )

    cur = conn.execute("SELECT coalesce(MAX(version), 0) AS current_version FROM schema_migrations;")
    row = cur.fetchone()
    current_version = row["current_version"] if row else 0

    if current_version < 1:
        _apply_migration_v1(conn)
        current_version = 1

    return current_version


def _apply_migration_v1(conn: sqlite3.Connection) -> None:
    """Migration 1: Initial schema for runs and step_history."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                workflow_name TEXT NOT NULL,
                task TEXT NOT NULL,
                status TEXT NOT NULL,
                current_step TEXT,
                workspace_path TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS step_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                step_id TEXT NOT NULL,
                step_type TEXT NOT NULL,
                role TEXT,
                result TEXT,
                transition_taken TEXT,
                started_at TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_workspace_status ON runs(workspace_path, status);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_step_history_run_id ON step_history(run_id, started_at);")

        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?);",
            (1, now_iso),
        )


def init_db(db_path: Optional[Union[str, Path]] = None) -> sqlite3.Connection:
    """Initialize database connection and auto-run all pending migrations."""
    conn = connect_db(db_path)
    apply_migrations(conn)
    return conn
