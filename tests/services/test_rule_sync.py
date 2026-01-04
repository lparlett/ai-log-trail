"""Tests for syncing redaction rules into the database (AI-assisted)."""

from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from typing import cast

from src.services.database import ensure_schema, get_connection
from src.services.redaction_rules import (
    RedactionRule,
    RuleOptions,
    load_rules_from_db,
    sync_rules_to_db,
)


TC = unittest.TestCase()


def _make_conn(tmp_path: Path) -> sqlite3.Connection:
    conn = get_connection(tmp_path / "sync.sqlite")
    ensure_schema(conn)
    return conn


def _seed_interaction(conn: sqlite3.Connection) -> int:
    file_id = conn.execute(
        "INSERT INTO files (path, agent_type) VALUES ('/tmp/test.jsonl', 'codex')"
    ).lastrowid
    TC.assertIsNotNone(file_id)
    file_id_int = cast(int, file_id)

    session_id = conn.execute(
        "INSERT INTO sessions (file_id, agent_type) VALUES (?, 'codex')", (file_id_int,)
    ).lastrowid
    TC.assertIsNotNone(session_id)
    session_id_int = cast(int, session_id)

    interaction_id = conn.execute(
        """INSERT INTO interactions 
           (file_id, session_id, agent_type, interaction_index)
           VALUES (?, ?, 'codex', 0)""",
        (file_id_int, session_id_int),
    ).lastrowid
    TC.assertIsNotNone(interaction_id)
    return cast(int, interaction_id)


def test_sync_rules_soft_disables_missing_and_redactions(tmp_path: Path) -> None:
    """Rules missing from the file should be disabled and linked redactions inactivated."""

    conn = _make_conn(tmp_path)
    interaction_id = _seed_interaction(conn)
    conn.execute(
        """
        INSERT INTO redaction_rules
        (id, type, pattern, scope, replacement_text, rule_fingerprint, enabled)
        VALUES ('old', 'regex', 'secret', 'interaction', '<X>', 'fp-old', 1)
        """
    )
    conn.execute(
        """
        INSERT INTO redactions (interaction_id, rule_id, rule_fingerprint, active, applied_at)
        VALUES (?, 'old', 'fp-old', 1, datetime('now'))
        """,
        (interaction_id,),
    )

    new_rule = RedactionRule(
        id="new",
        type="literal",
        pattern="token",
        options=RuleOptions(scope="interaction", replacement="<R>"),
    )
    sync_rules_to_db(conn, [new_rule])

    rules = load_rules_from_db(conn, include_disabled=True)
    rule_states = {rule.id: rule.enabled for rule in rules}
    TC.assertTrue(rule_states["new"])
    TC.assertFalse(rule_states["old"])

    redaction_row = conn.execute(
        "SELECT active FROM redactions WHERE rule_id = 'old'"
    ).fetchone()
    TC.assertIsNotNone(redaction_row)
    TC.assertEqual(redaction_row[0], 0)

    conn.close()
