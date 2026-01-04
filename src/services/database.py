"""SQLite helpers for AI Log Trail.

Purpose: Centralize SQLite schema management and connection helpers.
Author: Codex with Lauren Parlett
Date: 2025-10-30
Related tests: tests/test_db_utils_and_handlers.py, tests/test_ingest.py,
  tests/test_redactions.py
AI-assisted: Updated with Codex (GPT-5) and Claude Haiku 4.5.
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
    agent_type TEXT NOT NULL CHECK (agent_type IN ('codex', 'copilot')),
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL UNIQUE REFERENCES files(id) ON DELETE CASCADE,
    agent_type TEXT NOT NULL CHECK (agent_type IN ('codex', 'copilot')),
    agent_session_id TEXT,
    agent_metadata TEXT NOT NULL DEFAULT '{}',
    raw_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    agent_type TEXT NOT NULL CHECK (agent_type IN ('codex', 'copilot')),
    interaction_index INTEGER NOT NULL,
    timestamp TEXT,
    agent_user_input TEXT,
    agent_context TEXT NOT NULL DEFAULT '{}',
    agent_response TEXT NOT NULL DEFAULT '{}',
    raw_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interaction_id INTEGER NOT NULL REFERENCES interactions(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL CHECK (event_type IN (
        'token_usage', 'agent_reasoning', 'context_change', 'function_plan'
    )),
    timestamp TEXT,
    payload TEXT NOT NULL,
    raw_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_tool_invocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interaction_id INTEGER NOT NULL REFERENCES interactions(id) ON DELETE CASCADE,
    agent_type TEXT NOT NULL CHECK (agent_type IN ('codex', 'copilot')),
    tool_name TEXT NOT NULL,
    tool_id TEXT,
    invocation_id TEXT,
    call_timestamp TEXT,
    response_timestamp TEXT,
    tool_arguments TEXT,
    tool_output TEXT,
    tool_status TEXT CHECK (tool_status IN ('pending', 'success', 'error')),
    raw_input_json TEXT,
    raw_output_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS redaction_rules (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL CHECK (type IN ('regex', 'marker', 'literal')),
    pattern TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'interaction'
        CHECK (scope IN ('interaction', 'field', 'global')),
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
    interaction_id INTEGER REFERENCES interactions(id) ON DELETE CASCADE,
    prompt_id INTEGER,
    rule_id TEXT REFERENCES redaction_rules(id) ON DELETE SET NULL,
    rule_fingerprint TEXT NOT NULL,
    field_path TEXT,
    reason TEXT,
    actor TEXT,
    session_file_path TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT,
    UNIQUE(file_id, prompt_id, field_path, rule_id, rule_fingerprint)
);

CREATE INDEX IF NOT EXISTS idx_redactions_interaction
    ON redactions(interaction_id);
CREATE INDEX IF NOT EXISTS idx_interactions_session
    ON interactions(session_id, agent_type);
CREATE INDEX IF NOT EXISTS idx_tool_invocations_interaction
    ON agent_tool_invocations(interaction_id);
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
