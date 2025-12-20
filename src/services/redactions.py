"""Redaction persistence helpers for prompts and related content.

Purpose: CRUD helpers for the ``redactions`` table (AI-assisted by Codex GPT-5).
Author: Codex with Lauren Parlett
Date: 2025-11-27
Related tests: tests/test_redactions.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from sqlite3 import Connection
from typing import Any, Iterable


# pylint: disable=too-many-instance-attributes
# Justification: Redaction tracking requires: file_id, prompt_id, rule_id,
# fingerprint, field_path, reason, actor, session_file_path, applied_at. Each
# field is necessary for comprehensive audit trail and deduplication.
@dataclass(frozen=True)
class RedactionCreate:
    """Input payload for creating a redaction record."""

    file_id: int | None
    prompt_id: int | None
    rule_id: str | None
    rule_fingerprint: str
    field_path: str | None = None
    reason: str | None = None
    actor: str | None = None
    session_file_path: str | None = None
    applied_at: str | None = None


@dataclass(frozen=True)
class RedactionRecord:  # pylint: disable=too-many-instance-attributes
    """Represents a stored redaction row."""

    id: int
    file_id: int | None
    prompt_id: int | None
    rule_id: str | None
    rule_fingerprint: str
    field_path: str | None
    reason: str | None
    actor: str | None
    active: bool
    session_file_path: str | None
    applied_at: str
    created_at: str
    updated_at: str | None


def create_redaction(conn: Connection, payload: RedactionCreate) -> int:
    """Insert a redaction row and return its id."""

    _validate_field_path(payload.field_path)
    _validate_rule_fingerprint(payload.rule_fingerprint)

    # Generate timestamp if not provided
    applied_at = payload.applied_at or datetime.now(timezone.utc).isoformat()

    cursor = _execute(
        conn,
        """
        INSERT INTO redactions (
            file_id,
            prompt_id,
            rule_id,
            rule_fingerprint,
            field_path,
            reason,
            actor,
            session_file_path,
            applied_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload.file_id,
            payload.prompt_id,
            payload.rule_id,
            payload.rule_fingerprint,
            payload.field_path.strip() if payload.field_path else None,
            _normalize_optional(payload.reason),
            _normalize_optional(payload.actor),
            _normalize_optional(payload.session_file_path),
            applied_at,
        ),
    )
    if cursor.lastrowid is None:
        raise RuntimeError("Failed to insert redaction row.")
    return int(cursor.lastrowid)


def insert_redaction_application(conn: Connection, payload: RedactionCreate) -> None:
    """Insert a redaction application row, ignoring duplicates via unique index."""

    _validate_field_path(payload.field_path)
    _validate_rule_fingerprint(payload.rule_fingerprint)

    # Generate timestamp if not provided
    applied_at = payload.applied_at or datetime.now(timezone.utc).isoformat()

    values = (
        payload.file_id,
        payload.prompt_id,
        payload.rule_id,
        payload.rule_fingerprint,
        payload.field_path.strip() if payload.field_path else None,
        _normalize_optional(payload.reason),
        _normalize_optional(payload.actor),
        _normalize_optional(payload.session_file_path),
        applied_at,
    )

    module_name = conn.__class__.__module__
    if module_name.startswith("sqlite3"):
        query = """
            INSERT OR IGNORE INTO redactions (
                file_id,
                prompt_id,
                rule_id,
                rule_fingerprint,
                field_path,
                reason,
                actor,
                session_file_path,
                applied_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
    else:
        query = """
            INSERT INTO redactions (
                file_id,
                prompt_id,
                rule_id,
                rule_fingerprint,
                field_path,
                reason,
                actor,
                session_file_path,
                applied_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (file_id, prompt_id, field_path, rule_id, rule_fingerprint)
            DO NOTHING
        """
    cursor = conn.cursor()
    cursor.execute(query, values)
    cursor.close()


def get_redaction(conn: Connection, redaction_id: int) -> RedactionRecord | None:
    """Return a single redaction row by id."""

    cursor = _execute(
        conn,
        """
        SELECT
            id,
            file_id,
            prompt_id,
            rule_id,
            rule_fingerprint,
            field_path,
            reason,
            actor,
            active,
            session_file_path,
            applied_at,
            created_at,
            updated_at
        FROM redactions
        WHERE id = ?
        """,
        (redaction_id,),
    )
    row = cursor.fetchone()
    return _row_to_record(row) if row else None


def list_redactions(
    conn: Connection,
    *,
    prompt_id: int | None = None,
) -> list[RedactionRecord]:
    """Return redactions filtered by prompt."""

    query = """
        SELECT
            id,
            file_id,
            prompt_id,
            rule_id,
            rule_fingerprint,
            field_path,
            reason,
            actor,
            active,
            session_file_path,
            applied_at,
            created_at,
            updated_at
        FROM redactions
        WHERE (? IS NULL OR prompt_id = ?)
          AND active = ?
        ORDER BY created_at DESC, id DESC
    """
    params: tuple[Any, ...] = (prompt_id, prompt_id, 1)
    cursor = _execute(conn, query, params)
    rows = cursor.fetchall()
    return [_row_to_record(row) for row in rows]


# pylint: disable=too-many-arguments
# pylint: disable=too-many-locals
def update_redaction(
    conn: Connection,
    redaction_id: int,
    *,
    file_id: int | None = None,
    prompt_id: int | None = None,
    field_path: str | None = None,
    reason: str | None = None,
    actor: str | None = None,
    rule_id: str | None = None,
    rule_fingerprint: str | None = None,
    active: bool | None = None,
    session_file_path: str | None = None,
    applied_at: str | None = None,
) -> bool:
    """Update a redaction row; returns True when a row was changed."""

    assignments, params = _collect_update_fields(
        file_id=file_id,
        prompt_id=prompt_id,
        field_path=field_path,
        reason=reason,
        actor=actor,
        rule_id=rule_id,
        rule_fingerprint=rule_fingerprint,
        active=active,
        session_file_path=session_file_path,
        applied_at=applied_at,
    )
    if not assignments:
        return False

    assignments.append("updated_at = CURRENT_TIMESTAMP")
    params.append(redaction_id)
    set_clause = ", ".join(assignments)
    # Bandit B608: assignments are constructed from vetted columns only.
    query = "UPDATE redactions SET " + set_clause + " WHERE id = ?"  # nosec B608
    cursor = _execute(conn, query, tuple(params))
    return bool(getattr(cursor, "rowcount", 0) > 0)


def delete_redaction(conn: Connection, redaction_id: int) -> bool:
    """Delete a redaction row by id."""

    cursor = _execute(conn, "DELETE FROM redactions WHERE id = ?", (redaction_id,))
    return bool(getattr(cursor, "rowcount", 0) > 0)


def _row_to_record(row: Iterable[Any]) -> RedactionRecord:
    """Convert a DB row to a RedactionRecord."""

    (
        row_id,
        file_id,
        prompt_id,
        rule_id,
        rule_fingerprint,
        field_path,
        reason,
        actor,
        active,
        session_file_path,
        applied_at,
        created_at,
        updated_at,
    ) = row
    return RedactionRecord(
        id=int(row_id),
        file_id=int(file_id) if file_id is not None else None,
        prompt_id=int(prompt_id) if prompt_id is not None else None,
        rule_id=str(rule_id) if rule_id is not None else None,
        rule_fingerprint=str(rule_fingerprint),
        field_path=str(field_path) if field_path is not None else None,
        reason=str(reason) if reason is not None else None,
        actor=str(actor) if actor is not None else None,
        active=bool(active),
        session_file_path=(
            str(session_file_path) if session_file_path is not None else None
        ),
        applied_at=str(applied_at),
        created_at=str(created_at),
        updated_at=str(updated_at) if updated_at is not None else None,
    )


def _validate_field_path(field_path: str | None) -> None:
    """Validate field_path format if provided."""

    if field_path is not None and not field_path.strip():
        raise ValueError("field_path cannot be blank when provided.")


def _normalize_optional(value: str | None) -> str | None:
    """Return a trimmed optional string or None."""

    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _collect_update_fields(
    *,
    file_id: int | None,
    prompt_id: int | None,
    field_path: str | None,
    reason: str | None,
    actor: str | None,
    rule_id: str | None,
    rule_fingerprint: str | None,
    active: bool | None,
    session_file_path: str | None,
    applied_at: str | None,
) -> tuple[list[str], list[Any]]:
    """Build update clause components with validation."""

    assignments: list[str] = []
    params: list[Any] = []

    _append_file(assignments, params, file_id)
    _append_prompt(assignments, params, prompt_id)
    _append_field_path(assignments, params, field_path)
    _append_optional(assignments, params, "reason", reason)
    _append_optional(assignments, params, "actor", actor)
    _append_rule(assignments, params, rule_id)
    _append_rule_fingerprint(assignments, params, rule_fingerprint)
    _append_active(assignments, params, active)
    _append_optional(assignments, params, "session_file_path", session_file_path)
    _append_optional(assignments, params, "applied_at", applied_at)

    return assignments, params


def _append_prompt(
    assignments: list[str], params: list[Any], prompt_id: int | None
) -> None:
    """Add prompt assignment when present."""

    if prompt_id is not None:
        assignments.append("prompt_id = ?")
        params.append(prompt_id)


def _append_file(
    assignments: list[str], params: list[Any], file_id: int | None
) -> None:
    """Add file assignment when present."""

    if file_id is not None:
        assignments.append("file_id = ?")
        params.append(file_id)


def _append_scope(
    assignments: list[str],  # pylint: disable=unused-argument
    params: list[Any],  # pylint: disable=unused-argument
    scope: str | None,  # pylint: disable=unused-argument
) -> None:
    """Deprecated: scope is no longer stored in redactions table."""
    # This function is kept for API compatibility but is no longer used


def _append_field_path(
    assignments: list[str],
    params: list[Any],
    field_path: str | None,
) -> None:
    """Add field_path assignment with validation."""

    if field_path is None:
        return
    _validate_field_path(field_path)
    assignments.append("field_path = ?")
    params.append(field_path.strip() or None)


def _append_replacement(
    assignments: list[str],  # pylint: disable=unused-argument
    params: list[Any],  # pylint: disable=unused-argument
    replacement_text: str | None,  # pylint: disable=unused-argument
) -> None:
    """Deprecated: replacement_text is no longer stored in redactions table."""
    # This function is kept for API compatibility but is no longer used


def _append_optional(
    assignments: list[str],
    params: list[Any],
    column: str,
    value: str | None,
) -> None:
    """Add optional string assignment."""

    if value is not None:
        assignments.append(f"{column} = ?")
        params.append(_normalize_optional(value))


def _append_rule(
    assignments: list[str], params: list[Any], rule_id: str | None
) -> None:
    """Add rule_id assignment when provided."""

    if rule_id is not None:
        assignments.append("rule_id = ?")
        params.append(rule_id)


def _append_rule_fingerprint(
    assignments: list[str], params: list[Any], rule_fingerprint: str | None
) -> None:
    """Add rule_fingerprint assignment when provided."""

    if rule_fingerprint is not None:
        _validate_rule_fingerprint(rule_fingerprint)
        assignments.append("rule_fingerprint = ?")
        params.append(rule_fingerprint)


def _append_active(
    assignments: list[str], params: list[Any], active: bool | None
) -> None:
    """Add active flag assignment when provided."""

    if active is not None:
        assignments.append("active = ?")
        params.append(1 if active else 0)


def _execute(conn: Any, query: str, params: Iterable[Any] | None = None) -> Any:
    """Execute a query with placeholder adaptation for sqlite and psycopg2."""

    params = tuple(params or ())
    prepared = _prepare_query(conn, query)
    cursor = conn.cursor()
    cursor.execute(prepared, params)
    return cursor


def _validate_rule_fingerprint(rule_fingerprint: str) -> None:
    """Ensure rule_fingerprint is non-empty."""

    if not rule_fingerprint or not rule_fingerprint.strip():
        raise ValueError("rule_fingerprint must be a non-empty string.")


def _prepare_query(conn: Any, query: str) -> str:
    """Convert sqlite-style ? placeholders to %s when needed."""

    module_name = conn.__class__.__module__
    if module_name.startswith("sqlite3"):
        return query
    return query.replace("?", "%s")
