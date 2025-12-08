"""Tests for redaction CRUD helpers (AI-assisted by Codex GPT-5)."""

# pylint: disable=import-error

from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from typing import Any, cast

import pytest

from src.services.database import ensure_schema, get_connection
from src.services.redactions import (
    RedactionCreate,
    RedactionRecord,
    create_redaction,
    delete_redaction,
    get_redaction,
    list_redactions,
    update_redaction,
)

TC = unittest.TestCase()


def _make_connection(tmp_path: Path) -> sqlite3.Connection:
    """Create SQLite connection with schema applied."""

    conn = get_connection(tmp_path / "redactions.sqlite")
    ensure_schema(conn)
    return conn


def _insert_prompt(conn: sqlite3.Connection, *, path_suffix: str = "") -> int:
    """Insert minimal file + prompt rows for FK coverage."""

    file_path = f"tests/redactions{path_suffix}.jsonl"
    file_id = conn.execute(
        "INSERT INTO files (path) VALUES (?)", (file_path,)
    ).lastrowid
    if file_id is None:
        raise RuntimeError("Failed to insert file row for test setup.")
    prompt_id = conn.execute(
        """
        INSERT INTO prompts (file_id, prompt_index, timestamp, message, raw_json)
        VALUES (?, 1, 't0', 'prompt', '{}')
        """,
        (int(file_id),),
    ).lastrowid
    if prompt_id is None:
        raise RuntimeError("Failed to insert prompt row for test setup.")
    return int(prompt_id)


def test_create_and_get_redaction(tmp_path: Path) -> None:
    """create_redaction should persist and fetch a prompt-level entry."""

    conn = _make_connection(tmp_path)
    prompt_id = _insert_prompt(conn)
    redaction_id = create_redaction(
        conn,
        RedactionCreate(
            file_id=None,
            prompt_id=prompt_id,
            rule_id=None,
            rule_fingerprint="fp-create",
            reason="sensitive",
            actor="tester",
        ),
    )
    record = get_redaction(conn, redaction_id)
    TC.assertIsNotNone(record)
    record = cast("RedactionRecord", record)
    TC.assertEqual(record.prompt_id, prompt_id)
    TC.assertIsNone(record.rule_id)
    TC.assertEqual(record.reason, "sensitive")
    TC.assertEqual(record.actor, "tester")
    TC.assertTrue(record.active)
    conn.close()


def test_list_and_update_redaction(tmp_path: Path) -> None:
    """list_redactions and update_redaction should filter and mutate rows."""

    conn = _make_connection(tmp_path)
    prompt_id = _insert_prompt(conn)
    redaction_id = create_redaction(
        conn,
        RedactionCreate(
            file_id=None,
            prompt_id=prompt_id,
            rule_id=None,
            rule_fingerprint="fp-update",
            field_path="message",
        ),
    )
    records = list_redactions(conn, prompt_id=prompt_id)
    TC.assertEqual(len(records), 1)
    updated = update_redaction(
        conn,
        redaction_id,
        reason="privacy",
        field_path="raw_json.events[0].payload",
    )
    TC.assertTrue(updated)
    refreshed = get_redaction(conn, redaction_id)
    TC.assertIsNotNone(refreshed)
    refreshed = cast(RedactionRecord, refreshed)
    TC.assertEqual(refreshed.reason, "privacy")
    TC.assertEqual(
        refreshed.field_path,
        "raw_json.events[0].payload",
    )
    TC.assertIsNotNone(refreshed.updated_at)
    conn.close()


def test_delete_redaction_and_validation(tmp_path: Path) -> None:
    """delete_redaction should remove rows and validation should guard field_path."""

    conn = _make_connection(tmp_path)
    prompt_id = _insert_prompt(conn)
    redaction_id = create_redaction(
        conn,
        RedactionCreate(
            file_id=None,
            prompt_id=prompt_id,
            rule_id=None,
            rule_fingerprint="fp-delete",
        ),
    )
    deleted = delete_redaction(conn, redaction_id)
    TC.assertTrue(deleted)
    TC.assertIsNone(get_redaction(conn, redaction_id))

    # Test validation: field_path cannot be blank if provided
    with pytest.raises(ValueError):
        create_redaction(
            conn,
            RedactionCreate(
                file_id=None,
                prompt_id=None,
                rule_id=None,
                rule_fingerprint="fp-field-blank",
                field_path="",
            ),
        )

    conn.close()


def test_list_and_scope_filtering(tmp_path: Path) -> None:
    """list_redactions should filter by prompt_id."""

    conn = _make_connection(tmp_path)
    first_prompt = _insert_prompt(conn, path_suffix="-1")
    second_prompt = _insert_prompt(conn, path_suffix="-2")
    create_redaction(
        conn,
        RedactionCreate(
            file_id=None,
            prompt_id=first_prompt,
            rule_id=None,
            rule_fingerprint="fp-scope1",
        ),
    )
    create_redaction(
        conn,
        RedactionCreate(
            file_id=None,
            prompt_id=second_prompt,
            rule_id=None,
            rule_fingerprint="fp-scope2",
            field_path="message",
        ),
    )
    all_records = list_redactions(conn)
    TC.assertEqual(len(all_records), 2)

    first_only = list_redactions(conn, prompt_id=first_prompt)
    TC.assertEqual(len(first_only), 1)
    TC.assertEqual(first_only[0].prompt_id, first_prompt)

    second_only = list_redactions(conn, prompt_id=second_prompt)
    TC.assertEqual(len(second_only), 1)
    TC.assertEqual(second_only[0].prompt_id, second_prompt)
    conn.close()


def test_update_redaction_no_changes(tmp_path: Path) -> None:
    """update_redaction should return False when no fields were provided."""

    conn = _make_connection(tmp_path)
    prompt_id = _insert_prompt(conn)
    redaction_id = create_redaction(
        conn,
        RedactionCreate(
            file_id=None,
            prompt_id=prompt_id,
            rule_id=None,
            rule_fingerprint="fp-nochange",
        ),
    )
    TC.assertFalse(update_redaction(conn, redaction_id))
    conn.close()


def test_update_redaction_rejects_blank_replacement() -> None:
    """Test removed - replacement_text no longer stored in redactions table."""
    # Test deprecated due to schema change


def test_get_redaction_missing(tmp_path: Path) -> None:
    """get_redaction should return None for unknown ids."""

    conn = _make_connection(tmp_path)
    TC.assertIsNone(get_redaction(conn, 999))
    conn.close()


def test_update_redaction_sets_prompt_and_actor(tmp_path: Path) -> None:
    """update_redaction should allow prompt and actor updates."""

    conn = _make_connection(tmp_path)
    prompt_id = _insert_prompt(conn)
    new_prompt = _insert_prompt(conn, path_suffix="-actor")
    redaction_id = create_redaction(
        conn,
        RedactionCreate(
            file_id=None,
            prompt_id=prompt_id,
            rule_id=None,
            rule_fingerprint="fp-update-actor",
        ),
    )
    updated = update_redaction(
        conn,
        redaction_id,
        prompt_id=new_prompt,
        actor="reviewer",
    )
    TC.assertTrue(updated)
    refreshed = get_redaction(conn, redaction_id)
    TC.assertIsNotNone(refreshed)
    refreshed = cast("RedactionRecord", refreshed)
    TC.assertEqual(refreshed.prompt_id, new_prompt)
    TC.assertEqual(refreshed.actor, "reviewer")
    conn.close()


def test_update_redaction_sets_active_status(tmp_path: Path) -> None:
    """update_redaction should allow active flag updates."""

    conn = _make_connection(tmp_path)
    prompt_id = _insert_prompt(conn)
    redaction_id = create_redaction(
        conn,
        RedactionCreate(
            file_id=None,
            prompt_id=prompt_id,
            rule_id=None,
            rule_fingerprint="fp-update-active",
        ),
    )

    # Update to deactivate
    updated = update_redaction(conn, redaction_id, active=False)
    TC.assertTrue(updated)
    refreshed = get_redaction(conn, redaction_id)
    TC.assertIsNotNone(refreshed)
    refreshed = cast("RedactionRecord", refreshed)
    TC.assertEqual(refreshed.active, 0)

    # Update to reactivate
    updated = update_redaction(conn, redaction_id, active=True)
    TC.assertTrue(updated)
    refreshed = get_redaction(conn, redaction_id)
    TC.assertIsNotNone(refreshed)
    refreshed = cast("RedactionRecord", refreshed)
    TC.assertEqual(refreshed.active, 1)
    conn.close()


def test_create_redaction_raises_when_lastrowid_missing() -> None:
    """create_redaction should raise when cursor.lastrowid is None."""

    class _NoRowConn:
        def __init__(self) -> None:
            self.executed: list[tuple[Any, ...]] = []
            self.lastrowid: int | None = None
            self.rowcount: int = 0

        def cursor(self) -> _NoRowConn:  # pylint: disable=undefined-variable
            """Return self as cursor stub."""
            return self

        def execute(
            self, stmt: str, params: tuple[Any, ...]
        ) -> _NoRowConn:  # pylint: disable=undefined-variable
            """Record executed statement and reset row metadata."""
            self.executed.append((stmt, params))
            self.lastrowid = None
            self.rowcount = 0
            return self

        def close(self) -> None:
            """Close cursor stub."""
            return None

    conn = _NoRowConn()
    with pytest.raises(RuntimeError):
        create_redaction(
            conn,  # type: ignore[arg-type]
            RedactionCreate(
                file_id=None,
                prompt_id=None,
                rule_id=None,
                rule_fingerprint="fp-lastrowid",
            ),
        )
    conn.close()


def test_insert_prompt_raises_when_file_id_missing() -> None:
    """_insert_prompt should raise when file insert does not return an id."""

    class _Conn:
        def __init__(self) -> None:
            self.lastrowid: int | None = None
            self.rowcount: int = 0

        def cursor(self) -> _Conn:  # pylint: disable=undefined-variable
            """Return self as cursor stub."""
            return self

        def execute(
            self, _stmt: str, _params: tuple[Any, ...]
        ) -> _Conn:  # pylint: disable=undefined-variable
            """Simulate failed insert by leaving lastrowid as None."""
            self.lastrowid = None
            return self

        def close(self) -> None:
            """Close stub connection."""
            return None

    dummy = _Conn()
    with pytest.raises(RuntimeError):
        _insert_prompt(dummy)  # type: ignore[arg-type]
    dummy.close()


def test_update_redaction_with_rule_id(tmp_path: Path) -> None:
    """update_redaction should handle rule_id updates to None."""
    conn = _make_connection(tmp_path)
    prompt_id = _insert_prompt(conn)

    redaction_id = create_redaction(
        conn,
        RedactionCreate(
            file_id=None,
            prompt_id=prompt_id,
            rule_id=None,
            rule_fingerprint="fp-initial",
        ),
    )

    # Update with new rule_id (None remains None without a valid rule)
    # This tests the _append_rule_id code path
    updated = update_redaction(conn, redaction_id, rule_id=None)
    TC.assertFalse(updated)  # No actual change when setting to None

    conn.close()


def test_update_redaction_with_rule_fingerprint(tmp_path: Path) -> None:
    """update_redaction should handle rule_fingerprint updates."""
    conn = _make_connection(tmp_path)
    prompt_id = _insert_prompt(conn)

    redaction_id = create_redaction(
        conn,
        RedactionCreate(
            file_id=None,
            prompt_id=prompt_id,
            rule_id=None,
            rule_fingerprint="fp-v1",
        ),
    )

    # Update with new rule_fingerprint
    updated = update_redaction(conn, redaction_id, rule_fingerprint="fp-v2")
    TC.assertTrue(updated)

    refreshed = get_redaction(conn, redaction_id)
    TC.assertIsNotNone(refreshed)
    refreshed = cast(RedactionRecord, refreshed)
    TC.assertEqual(refreshed.rule_fingerprint, "fp-v2")
    conn.close()


def test_update_redaction_with_active_flag(tmp_path: Path) -> None:
    """update_redaction should handle active flag updates."""
    conn = _make_connection(tmp_path)
    prompt_id = _insert_prompt(conn)

    redaction_id = create_redaction(
        conn,
        RedactionCreate(
            file_id=None,
            prompt_id=prompt_id,
            rule_id=None,
            rule_fingerprint="fp-active",
        ),
    )

    # Deactivate
    updated = update_redaction(conn, redaction_id, active=False)
    TC.assertTrue(updated)

    refreshed = get_redaction(conn, redaction_id)
    TC.assertIsNotNone(refreshed)
    refreshed = cast(RedactionRecord, refreshed)
    TC.assertEqual(refreshed.active, 0)

    # Reactivate
    updated = update_redaction(conn, redaction_id, active=True)
    TC.assertTrue(updated)

    refreshed = get_redaction(conn, redaction_id)
    TC.assertIsNotNone(refreshed)
    refreshed = cast(RedactionRecord, refreshed)
    TC.assertEqual(refreshed.active, 1)
    conn.close()


def test_create_redaction_minimal(tmp_path: Path) -> None:
    """create_redaction should insert minimal redaction with defaults."""
    conn = _make_connection(tmp_path)
    prompt_id = _insert_prompt(conn)

    redaction_id = create_redaction(
        conn,
        RedactionCreate(
            file_id=None,
            prompt_id=prompt_id,
            rule_id=None,
            rule_fingerprint="fp-minimal",
        ),
    )

    TC.assertGreater(redaction_id, 0)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT prompt_id, rule_fingerprint FROM redactions WHERE id = ?",
        (redaction_id,),
    )
    row = cursor.fetchone()
    TC.assertIsNotNone(row)
    TC.assertEqual(row[0], prompt_id)
    TC.assertEqual(row[1], "fp-minimal")
    conn.close()


def test_create_redaction_all_fields(tmp_path: Path) -> None:
    """create_redaction should persist all provided fields."""
    conn = _make_connection(tmp_path)
    file_id = conn.execute(
        "INSERT INTO files (path) VALUES (?)", ("test.jsonl",)
    ).lastrowid
    if file_id is None:
        TC.fail("Failed to insert file")
    file_id = int(file_id)
    prompt_id = _insert_prompt(conn)

    redaction_id = create_redaction(
        conn,
        RedactionCreate(
            file_id=file_id,
            prompt_id=prompt_id,
            rule_id=None,
            rule_fingerprint="fp-complete",
            field_path="payload.message",
            reason="contains_pii",
            actor="redactor",
            session_file_path="2025/12/test.jsonl",
        ),
    )

    TC.assertGreater(redaction_id, 0)

    # Verify all fields were stored
    cursor = conn.cursor()
    cursor.execute(
        "SELECT file_id, prompt_id, rule_id, rule_fingerprint, "
        "field_path, reason, actor, session_file_path "
        "FROM redactions WHERE id = ?",
        (redaction_id,),
    )
    row = cursor.fetchone()
    TC.assertIsNotNone(row)
    TC.assertEqual(row[0], file_id)
    TC.assertEqual(row[1], prompt_id)
    TC.assertIsNone(row[2])
    TC.assertEqual(row[3], "fp-complete")
    TC.assertEqual(row[4], "payload.message")
    TC.assertEqual(row[5], "contains_pii")
    TC.assertEqual(row[6], "redactor")
    TC.assertEqual(row[7], "2025/12/test.jsonl")
    conn.close()


def test_list_redactions_filtering(tmp_path: Path) -> None:
    """list_redactions should filter by prompt_id correctly."""
    conn = _make_connection(tmp_path)

    # Insert two files/prompts
    file_id_1 = conn.execute(
        "INSERT INTO files (path) VALUES (?)", ("test1.jsonl",)
    ).lastrowid
    if file_id_1 is None:
        TC.fail("Failed to insert file 1")
    file_id_1 = int(file_id_1)

    file_id_2 = conn.execute(
        "INSERT INTO files (path) VALUES (?)", ("test2.jsonl",)
    ).lastrowid
    if file_id_2 is None:
        TC.fail("Failed to insert file 2")
    file_id_2 = int(file_id_2)

    prompt_id_1 = conn.execute(
        "INSERT INTO prompts (file_id, prompt_index, timestamp, message, raw_json) "
        "VALUES (?, 1, 't0', 'test1', '{}')",
        (file_id_1,),
    ).lastrowid
    if prompt_id_1 is None:
        TC.fail("Failed to insert prompt 1")
    prompt_id_1 = int(prompt_id_1)

    prompt_id_2 = conn.execute(
        "INSERT INTO prompts (file_id, prompt_index, timestamp, message, raw_json) "
        "VALUES (?, 1, 't0', 'test2', '{}')",
        (file_id_2,),
    ).lastrowid
    if prompt_id_2 is None:
        TC.fail("Failed to insert prompt 2")
    prompt_id_2 = int(prompt_id_2)

    # Create redactions for both prompts
    create_redaction(
        conn,
        RedactionCreate(
            file_id=None,
            prompt_id=prompt_id_1,
            rule_id=None,
            rule_fingerprint="fp1",
        ),
    )
    create_redaction(
        conn,
        RedactionCreate(
            file_id=None,
            prompt_id=prompt_id_2,
            rule_id=None,
            rule_fingerprint="fp2",
        ),
    )

    # List all
    all_records = list_redactions(conn)
    TC.assertEqual(len(all_records), 2)

    # Filter by prompt_id_1
    filtered = list_redactions(conn, prompt_id=prompt_id_1)
    TC.assertEqual(len(filtered), 1)
    TC.assertEqual(filtered[0].prompt_id, prompt_id_1)

    # Filter by prompt_id_2
    filtered = list_redactions(conn, prompt_id=prompt_id_2)
    TC.assertEqual(len(filtered), 1)
    TC.assertEqual(filtered[0].prompt_id, prompt_id_2)

    conn.close()


def test_update_redaction_various_fields(tmp_path: Path) -> None:
    """update_redaction should handle updating different field combinations."""
    conn = _make_connection(tmp_path)

    # Insert file and prompt
    file_id = conn.execute(
        "INSERT INTO files (path) VALUES (?)", ("test.jsonl",)
    ).lastrowid
    if file_id is None:
        TC.fail("Failed to insert file")
    file_id = int(file_id)
    prompt_id = conn.execute(
        "INSERT INTO prompts (file_id, prompt_index, timestamp, message, raw_json) "
        "VALUES (?, 1, 't0', 'test', '{}')",
        (file_id,),
    ).lastrowid
    if prompt_id is None:
        TC.fail("Failed to insert prompt")
    prompt_id = int(prompt_id)

    redaction_id = create_redaction(
        conn,
        RedactionCreate(
            file_id=None,
            prompt_id=prompt_id,
            rule_id=None,
            rule_fingerprint="fp-update",
            reason="initial_reason",
            actor="original_actor",
        ),
    )

    # Update reason only
    updated = update_redaction(conn, redaction_id, reason="updated_reason")
    TC.assertTrue(updated)

    # Update actor only
    updated = update_redaction(conn, redaction_id, actor="new_actor")
    TC.assertTrue(updated)

    # Update multiple fields
    updated = update_redaction(
        conn,
        redaction_id,
        reason="final_reason",
        actor="final_actor",
        field_path="new.path",
    )
    TC.assertTrue(updated)

    # Verify updates
    cursor = conn.cursor()
    cursor.execute(
        "SELECT reason, actor, field_path FROM redactions WHERE id = ?", (redaction_id,)
    )
    row = cursor.fetchone()
    TC.assertEqual(row[0], "final_reason")
    TC.assertEqual(row[1], "final_actor")
    TC.assertEqual(row[2], "new.path")

    conn.close()


def test_insert_prompt_raises_when_prompt_id_missing() -> None:
    """_insert_prompt should raise when prompt insert does not return an id."""

    class _Conn:
        def __init__(self) -> None:
            self.calls = 0
            self.lastrowid: int | None = None
            self.rowcount: int = 0

        def cursor(self) -> _Conn:  # pylint: disable=undefined-variable
            """Return self as cursor stub."""
            return self

        def execute(
            self, _stmt: str, _params: tuple[Any, ...]
        ) -> _Conn:  # pylint: disable=undefined-variable
            """Simulate first insert success then failure."""
            self.calls += 1
            if self.calls == 1:
                self.lastrowid = 1
            else:
                self.lastrowid = None
            return self

        def close(self) -> None:
            """Close stub connection."""
            return None

    dummy = _Conn()
    with pytest.raises(RuntimeError):
        _insert_prompt(dummy)  # type: ignore[arg-type]
    dummy.close()
