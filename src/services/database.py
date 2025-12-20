"""SQLite helpers for codex_sessions_tool.

Purpose: Centralize SQLite schema management and connection helpers.
Author: Codex with Lauren Parlett
Date: 2025-10-30
Related tests: tests/test_db_utils_and_handlers.py, tests/test_ingest.py,
  tests/test_redactions.py
AI-assisted: Updated with Codex (GPT-5).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from src.services.config import DatabaseConfig
from src.services import postgres_schema


SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL UNIQUE REFERENCES files(id) ON DELETE CASCADE,
    session_id TEXT,
    session_timestamp TEXT,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS session_context (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL UNIQUE REFERENCES sessions(id) ON DELETE CASCADE,
    cwd TEXT,
    approval_policy TEXT,
    sandbox_mode TEXT,
    network_access TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    prompt_index INTEGER NOT NULL,
    timestamp TEXT,
    message TEXT,
    active_file TEXT,
    open_tabs TEXT,
    my_request TEXT,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS redaction_rules (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL CHECK (type IN ('regex', 'marker', 'literal')),
    pattern TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'prompt'
        CHECK (scope IN ('prompt', 'field', 'global')),
    replacement_text TEXT NOT NULL,
    rule_fingerprint TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    reason TEXT,
    actor TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS redactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
    prompt_id INTEGER REFERENCES prompts(id) ON DELETE CASCADE,
    rule_id TEXT REFERENCES redaction_rules(id) ON DELETE SET NULL,
    rule_fingerprint TEXT NOT NULL,
    field_path TEXT,
    reason TEXT,
    actor TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    session_file_path TEXT,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_redactions_prompt
    ON redactions(prompt_id);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_redactions_application
    ON redactions(
        file_id,
        prompt_id,
        field_path,
        rule_id,
        rule_fingerprint
    );

CREATE TABLE IF NOT EXISTS token_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id INTEGER NOT NULL REFERENCES prompts(id) ON DELETE CASCADE,
    timestamp TEXT,
    primary_used_percent REAL,
    primary_window_minutes INTEGER,
    primary_resets TEXT,
    secondary_used_percent REAL,
    secondary_window_minutes INTEGER,
    secondary_resets TEXT,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS turn_context_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id INTEGER NOT NULL REFERENCES prompts(id) ON DELETE CASCADE,
    timestamp TEXT,
    writable_roots TEXT,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS agent_reasoning_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id INTEGER NOT NULL REFERENCES prompts(id) ON DELETE CASCADE,
    timestamp TEXT,
    source TEXT,
    text TEXT,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS function_plan_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id INTEGER NOT NULL REFERENCES prompts(id) ON DELETE CASCADE,
    timestamp TEXT,
    name TEXT,
    arguments TEXT,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS function_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id INTEGER NOT NULL REFERENCES prompts(id) ON DELETE CASCADE,
    call_timestamp TEXT,
    output_timestamp TEXT,
    name TEXT,
    call_id TEXT,
    arguments TEXT,
    output TEXT,
    raw_call_json TEXT,
    raw_output_json TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    category TEXT NOT NULL,
    priority TEXT NOT NULL,
    session_id TEXT,
    data TEXT,
    raw_json TEXT
);
"""


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Return SQLite connection with foreign keys enabled."""

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Apply base schema if tables do not exist."""

    conn.executescript(SCHEMA)


def get_connection_for_config(db_config: DatabaseConfig) -> Any:
    """Return a connection for sqlite or Postgres and ensure schema exists."""

    if db_config.backend == "sqlite":
        sqlite_conn = get_connection(db_config.sqlite_path)
        ensure_schema(sqlite_conn)
        return sqlite_conn

    if not db_config.postgres_dsn:
        raise RuntimeError("postgres_dsn is required for Postgres backend.")

    try:
        import psycopg2  # pylint: disable=import-outside-toplevel
        from psycopg2.extensions import (  # pylint: disable=import-outside-toplevel
            connection as PgConnection,
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - env dependent
        raise RuntimeError(
            "psycopg2-binary is required for Postgres connections. "
            "Install the 'postgres' optional dependency."
        ) from exc

    conn: PgConnection = psycopg2.connect(db_config.postgres_dsn)
    cursor = conn.cursor()
    try:
        cursor.execute(postgres_schema.POSTGRES_SCHEMA)
    finally:
        cursor.close()
    conn.commit()
    return conn
