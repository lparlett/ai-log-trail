"""Tests for session ingestion functionality."""

# pylint: disable=import-error,protected-access,import-outside-toplevel

from __future__ import annotations

import json
import logging
import sqlite3
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from pytest import raises

from src.parsers.handlers.db_utils import insert_prompt
from src.services import ingest
from src.services.ingest import (
    ErrorSeverity,
    ProcessingError,
    ProcessingErrorAction,
    SanitizationError,
    SessionIngester,
    _build_prompt_insert,
    _prepare_events,
    _process_events,
    ingest_session_file,
    sanitize_json_for_storage,
)

TC = unittest.TestCase()


@pytest.fixture(name="sample_session_file")
def fixture_sample_session_file(tmp_path: Path) -> Path:
    """Create a temporary copy of the sample session file."""
    source = Path("tests/fixtures/codex_sample_session.jsonl")
    dest = tmp_path / "test_session.jsonl"
    dest.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return dest


@pytest.fixture(name="codex_updates_file")
def fixture_codex_updates_file(tmp_path: Path) -> Path:
    """Create a temporary copy of the Codex updates session file."""
    source = Path("tests/fixtures/codex_file_updates.jsonl")
    dest = tmp_path / "codex_file_updates.jsonl"
    dest.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return dest


def test_sanitize_json_for_storage_validates_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that sanitize_json_for_storage properly validates its input."""
    test_case = unittest.TestCase()

    with test_case.assertRaises(TypeError):
        sanitize_json_for_storage("not a dict")  # type: ignore

    with test_case.assertRaises(SanitizationError):
        # Mock the sanitize_json function to return a non-dict
        def mock_sanitize(_data: dict[str, Any]) -> str:
            return "invalid"

        monkeypatch.setattr(ingest, "sanitize_json", mock_sanitize)
        sanitize_json_for_storage({"test": "data"})


def test_prepare_events_batch_processing(
    sample_session_file: Path, sample_timestamp: datetime
) -> None:
    """Test that _prepare_events correctly processes events in batches."""
    test_case = unittest.TestCase()

    # Create test event data
    test_event = {
        "type": "event_msg",
        "timestamp": sample_timestamp.isoformat(),
        "payload": {"type": "user_message", "message": "Test message"},
    }

    events = [test_event, test_event]  # Two identical events
    errors: list[ProcessingError] = []
    prepared = _prepare_events(events, sample_session_file, errors, batch_size=1)

    test_case.assertEqual(
        len(prepared), len(events), "All valid events should be processed"
    )
    test_case.assertEqual(
        len(errors), 0, "No errors should be reported for valid events"
    )

    # Check structure of prepared events
    for event in prepared:
        test_case.assertIsInstance(event, dict)
        test_case.assertIn("type", event)
        test_case.assertIn("timestamp", event)
        test_case.assertIn("payload", event)


def test_session_ingester_processes_session(
    db_connection: sqlite3.Connection,
    sample_session_file: Path,
) -> None:
    """Test that SessionIngester correctly processes a complete session."""
    test_case = unittest.TestCase()
    ingester = SessionIngester(
        conn=db_connection,
        session_file=sample_session_file,
        batch_size=2,
        verbose=False,
        errors=[],
    )

    summary = ingester.process_session()

    # Validate summary contains expected counts
    test_case.assertIsInstance(summary, dict)
    test_case.assertIn("prompts", summary)
    test_case.assertGreaterEqual(summary["prompts"], 0)

    # Check database has expected records
    cursor = db_connection.cursor()
    cursor.execute("SELECT COUNT(*) FROM sessions")
    session_count = cursor.fetchone()[0]
    test_case.assertGreater(session_count, 0, "Expected at least one session record")

    cursor.execute("SELECT COUNT(*) FROM events")
    event_count = cursor.fetchone()[0]
    test_case.assertGreater(event_count, 0, "Expected at least one event record")
    test_case.assertEqual(
        summary["agent_reasoning_messages"], 1, "Expected one agent reasoning message"
    )
    test_case.assertFalse(summary["errors"], "Expected no errors")

    # Verify data was persisted
    cursor = db_connection.cursor()

    cursor.execute("SELECT COUNT(*) FROM files")
    test_case.assertEqual(cursor.fetchone()[0], 1, "Expected one file record")

    cursor.execute("SELECT COUNT(*) FROM prompts")
    test_case.assertEqual(cursor.fetchone()[0], 1, "Expected one prompt record")

    cursor.execute("SELECT COUNT(*) FROM sessions")
    test_case.assertEqual(cursor.fetchone()[0], 1, "Expected one session record")


def test_session_ingester_handles_function_calls_and_prelude_turn_context(
    db_connection: sqlite3.Connection,
    codex_updates_file: Path,
) -> None:
    """Ensure ingestion processes function calls and preserves prelude events."""
    test_case = unittest.TestCase()
    ingester = SessionIngester(
        conn=db_connection,
        session_file=codex_updates_file,
        batch_size=4,
        verbose=False,
        errors=[],
    )

    summary = ingester.process_session()

    test_case.assertEqual(summary["prompts"], 1, "Expected single prompt")
    test_case.assertEqual(summary["function_calls"], 1, "Expected one function call")
    test_case.assertEqual(summary["agent_reasoning_messages"], 2)
    test_case.assertEqual(summary["token_messages"], 1)
    # turn_context appears in prelude, not grouped counts
    test_case.assertEqual(summary["turn_context_messages"], 0)
    test_case.assertFalse(
        summary["errors"], "Expected no errors for sanitized fixtures"
    )

    session_row = db_connection.execute(
        "SELECT raw_json FROM sessions WHERE file_id = ?",
        (summary["file_id"],),
    ).fetchone()
    test_case.assertIsNotNone(session_row)
    prelude_events = json.loads(session_row[0]).get("events", [])
    test_case.assertTrue(prelude_events)
    test_case.assertTrue(
        any(event.get("type") == "turn_context" for event in prelude_events),
        "Expected turn_context to be preserved in prelude events",
    )

    function_row = db_connection.execute(
        "SELECT call_id, output FROM function_calls ORDER BY id ASC"
    ).fetchone()
    test_case.assertEqual(function_row[0], "call_placeholder")
    test_case.assertEqual(function_row[1], "diff count 1")


def test_ingest_session_file_handles_errors(tmp_path: Path) -> None:
    """Test that ingest_session_file properly handles and reports errors."""
    invalid_file = tmp_path / "invalid.jsonl"
    invalid_file.write_text("invalid json\n{", encoding="utf-8")
    db_path = tmp_path / "test.sqlite"

    with raises(ValueError, match="Failed to parse JSON"):
        ingest_session_file(invalid_file, db_path)


def test_process_events_in_batches_limits_size() -> None:
    """Ensure batches are emitted with the requested size."""
    events = ({"type": "event_msg", "payload": {}} for _ in range(5))
    batches = list(ingest.process_events_in_batches(events, batch_size=2))
    TC.assertEqual([len(batch) for batch in batches], [2, 2, 1])


def test_prepare_events_filters_invalid(sample_session_file: Path) -> None:
    """Invalid events should be recorded as processing errors and skipped."""
    raw_events = [
        {"type": "event_msg", "payload": {}},  # valid
        {"type": "event_msg", "payload": "bad"},  # invalid payload type
    ]
    errors: list[ProcessingError] = []
    prepared = _prepare_events(
        raw_events,  # type: ignore[arg-type]
        sample_session_file,
        errors,
        batch_size=1,
    )
    TC.assertEqual(len(prepared), 1)
    TC.assertTrue(errors)
    TC.assertEqual(errors[0].code, "invalid_event")


def test_ensure_file_row_resets_existing(tmp_path: Path) -> None:
    """_ensure_file_row should reuse file id and clear prior prompt/session rows."""
    conn = ingest.get_connection(tmp_path / "db.sqlite")
    ingest.ensure_schema(conn)
    session_file = tmp_path / "session.jsonl"
    session_file.write_text("{}", encoding="utf-8")

    file_id = ingest._ensure_file_row(  # pylint: disable=protected-access
        conn, session_file
    )
    conn.execute(
        "INSERT INTO prompts (file_id, prompt_index) VALUES (?, ?)",
        (file_id, 1),
    )
    conn.execute(
        "INSERT INTO sessions (file_id) VALUES (?)",
        (file_id,),
    )
    reused_id = ingest._ensure_file_row(  # pylint: disable=protected-access
        conn, session_file
    )
    TC.assertEqual(reused_id, file_id)
    TC.assertEqual(conn.execute("SELECT COUNT(*) FROM prompts").fetchone()[0], 0)
    TC.assertEqual(conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)
    conn.close()


def test_ingest_single_session_rolls_back_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_ingest_single_session should roll back inserts when processing fails."""
    conn = ingest.get_connection(tmp_path / "rollback.sqlite")
    ingest.ensure_schema(conn)
    session_file = tmp_path / "bad.jsonl"
    session_file.write_text('{"type": "event_msg", "payload": {}}', encoding="utf-8")

    def _raise(*_args: Any, **_kwargs: Any) -> None:  # pylint: disable=unused-argument
        raise RuntimeError("boom")

    monkeypatch.setattr(ingest.SessionIngester, "process_session", _raise)
    with pytest.raises(RuntimeError):
        ingest._ingest_single_session(  # pylint: disable=protected-access
            conn,
            session_file,
        )
    TC.assertEqual(conn.execute("SELECT COUNT(*) FROM files").fetchone()[0], 0)
    conn.close()


def test_ingest_session_file_rollback_on_db_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ingest_session_file should rollback and re-raise on DB errors."""

    session_file = tmp_path / "sess.jsonl"
    session_file.write_text('{"type": "event_msg", "payload": {}}', encoding="utf-8")
    db_path = tmp_path / "db.sqlite"

    class _BrokenConn(sqlite3.Connection):  # pylint: disable=too-few-public-methods
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.executed = False

        def execute(self, *args: Any, **kwargs: Any) -> Any:
            """Simulate a failing execute call for rollback testing."""
            _ = args
            _ = kwargs
            self.executed = True
            raise sqlite3.DatabaseError("boom")

    def _broken_get_connection(path: Path) -> sqlite3.Connection:
        return _BrokenConn(path)

    monkeypatch.setattr(ingest, "get_connection", _broken_get_connection)
    with pytest.raises(sqlite3.DatabaseError):
        ingest_session_file(session_file, db_path)


def test_ingest_sessions_in_directory_handles_limits(
    tmp_path: Path, sample_session_file: Path
) -> None:
    """ingest_sessions_in_directory should respect limit and iterate by date."""
    root = tmp_path / "2025" / "11" / "23"
    root.mkdir(parents=True)
    target = root / "a.jsonl"
    target.write_text(sample_session_file.read_text(encoding="utf-8"), encoding="utf-8")
    db_path = tmp_path / "test.sqlite"
    summaries = list(
        ingest.ingest_sessions_in_directory(
            tmp_path,
            db_path,
            limit=1,
            verbose=False,
            batch_size=2,
        )
    )
    TC.assertEqual(len(summaries), 1)


def test_ingest_sessions_in_directory_returns_iterator(tmp_path: Path) -> None:
    """ingest_sessions_in_directory should return iterator even before iteration."""

    root = tmp_path / "2025" / "11" / "23"
    root.mkdir(parents=True)
    (root / "a.jsonl").write_text("{}", encoding="utf-8")
    db_path = tmp_path / "db.sqlite"
    iterator = ingest.ingest_sessions_in_directory(root, db_path, limit=None)
    TC.assertTrue(hasattr(iterator, "__iter__"))


def test_ingest_sessions_in_directory_raises_on_empty(tmp_path: Path) -> None:
    """ingest_sessions_in_directory should raise when no files are found."""
    db_path = tmp_path / "test.sqlite"
    empty_root = tmp_path / "missing"
    empty_root.mkdir(parents=True, exist_ok=True)
    with pytest.raises(ingest.SessionDiscoveryError):
        list(
            ingest.ingest_sessions_in_directory(
                empty_root,
                db_path,
            )
        )


def test_ingest_sessions_in_directory_propagates_non_discovery_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unexpected errors inside ingest_sessions_in_directory should propagate."""

    def _boom(_root: Path) -> list[Path]:  # pylint: disable=unused-argument
        raise RuntimeError("explode")

    monkeypatch.setattr(ingest, "iter_session_files", _boom)
    with pytest.raises(RuntimeError):
        list(
            ingest.ingest_sessions_in_directory(
                tmp_path,
                tmp_path / "db.sqlite",
            )
        )


def test_ingest_single_session_propagates_unexpected_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_ingest_single_session should re-raise unexpected exceptions."""

    conn = ingest.get_connection(tmp_path / "err.sqlite")
    ingest.ensure_schema(conn)
    session_file = tmp_path / "session.jsonl"
    session_file.write_text("{}", encoding="utf-8")

    def _boom(*_args: Any, **_kwargs: Any) -> None:  # pylint: disable=unused-argument
        raise RuntimeError("explode")

    monkeypatch.setattr(ingest, "load_session_events", _boom)
    with pytest.raises(RuntimeError):
        ingest._ingest_single_session(  # pylint: disable=protected-access
            conn,
            session_file,
        )
    conn.close()


def test_log_processing_error_and_serialization(
    sample_session_file: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Exercise logging and serialization of ProcessingError."""
    error = ProcessingError(
        severity=ErrorSeverity.ERROR,
        code="invalid_event",
        message="bad",
        recommended_action=ProcessingErrorAction.CONTINUE,
        file_path=sample_session_file,
        line_number=5,
        context={"event": {"payload": "bad"}},
    )
    with caplog.at_level(logging.ERROR):
        ingest._log_processing_error(error)  # pylint: disable=protected-access
    serialized = ingest.serialize_processing_error(error)
    TC.assertIn("invalid_event", caplog.text)
    TC.assertTrue(serialized["file_path"].endswith("test_session.jsonl"))
    TC.assertEqual(serialized["line_number"], 5)
    TC.assertEqual(serialized["context"]["event"]["payload"], "bad")


def test_build_prompt_insert_handles_missing_payload(tmp_path: Path) -> None:
    """_build_prompt_insert should tolerate non-dict payloads."""
    conn = ingest.get_connection(tmp_path / "prompt.sqlite")
    ingest.ensure_schema(conn)
    insert = _build_prompt_insert(  # pylint: disable=protected-access
        conn,
        1,
        1,
        {"timestamp": "t1", "payload": "not a dict"},
    )
    TC.assertEqual(insert.message, "")
    conn.close()


def test_process_events_covers_all_branches(tmp_path: Path) -> None:
    """_process_events should handle non-dict payloads and multiple event types."""
    conn = ingest.get_connection(tmp_path / "branches.sqlite")
    ingest.ensure_schema(conn)
    file_id = conn.execute(
        "INSERT INTO files (path) VALUES (?)", ("file.jsonl",)
    ).lastrowid
    if file_id is None:
        raise RuntimeError("Failed to insert file row")
    prompt_insert = _build_prompt_insert(  # pylint: disable=protected-access
        conn,
        int(file_id),
        1,
        {"timestamp": "t1", "payload": {"message": "Hi"}},
    )
    prompt_id = insert_prompt(prompt_insert)
    events = [
        {"type": "event_msg", "payload": "skip me"},
        {"type": "turn_context", "payload": {"sandbox_policy": {"mode": "r"}}},
        {
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "update_plan",
                "arguments": "{}",
            },
        },
        {
            "type": "response_item",
            "payload": {"type": "function_call_output", "output": "ok"},
        },
    ]
    counts = _process_events(
        conn,
        int(file_id),
        prompt_id,
        events,  # type: ignore[arg-type]
    )  # pylint: disable=protected-access
    TC.assertEqual(counts["turn_context_messages"], 1)
    TC.assertEqual(counts["function_plan_messages"], 1)
    TC.assertEqual(counts["function_calls"], 1)
    conn.close()


def test_ingest_session_file_success(sample_session_file: Path, tmp_path: Path) -> None:
    """ingest_session_file should return summary on success."""
    db_path = tmp_path / "ok.sqlite"
    summary = ingest_session_file(sample_session_file, db_path, batch_size=2)
    TC.assertGreaterEqual(summary["prompts"], 0)


def test_log_processing_error_critical_severity() -> None:
    """Test that CRITICAL severity errors are logged at critical level."""
    from unittest.mock import patch

    critical_error = ProcessingError(
        severity=ErrorSeverity.CRITICAL,
        code="test_critical",
        message="This is a critical error",
        recommended_action=ProcessingErrorAction.ABORT,
    )

    with patch("src.services.ingest.logger") as mock_logger:
        ingest._log_processing_error(critical_error)
        mock_logger.critical.assert_called_once()


def test_serialize_processing_error_with_context() -> None:
    """Test that ProcessingError with context is properly serialized."""
    error = ProcessingError(
        severity=ErrorSeverity.ERROR,
        code="test_error",
        message="Test error message",
        recommended_action=ProcessingErrorAction.CONTINUE,
        file_path=Path("test.jsonl"),
        line_number=42,
        context={"key": "value"},
    )

    serialized = ingest.serialize_processing_error(error)
    TC.assertEqual(serialized["severity"], "ERROR")
    TC.assertEqual(serialized["code"], "test_error")
    TC.assertEqual(serialized["message"], "Test error message")
    TC.assertIn("context", serialized)


def test_serialize_processing_error_without_context() -> None:
    """Test that ProcessingError without context serializes correctly."""
    error = ProcessingError(
        severity=ErrorSeverity.WARNING,
        code="test_warning",
        message="Test warning",
        recommended_action=ProcessingErrorAction.CONTINUE,
    )

    serialized = ingest.serialize_processing_error(error)
    TC.assertEqual(serialized["severity"], "WARNING")
    TC.assertEqual(serialized["code"], "test_warning")
    TC.assertIsNone(serialized.get("context"))


def test_ensure_file_row_reuses_existing(
    db_connection: sqlite3.Connection, tmp_path: Path
) -> None:
    """Test that _ensure_file_row reuses existing file entries."""
    session_file = tmp_path / "existing.jsonl"
    session_file.write_text("{}", encoding="utf-8")

    # Insert first time
    file_id_1 = ingest._ensure_file_row(db_connection, session_file)
    TC.assertGreater(file_id_1, 0)

    # Insert again - should return same ID
    file_id_2 = ingest._ensure_file_row(db_connection, session_file)
    TC.assertEqual(file_id_1, file_id_2)

    # Verify only one file record exists
    cursor = db_connection.cursor()
    cursor.execute("SELECT COUNT(*) FROM files WHERE path = ?", (str(session_file),))
    TC.assertEqual(cursor.fetchone()[0], 1)


def test_ensure_file_row_clears_previous_data(
    db_connection: sqlite3.Connection, tmp_path: Path
) -> None:
    """Test that reinserting a file clears previous prompts and sessions."""
    session_file = tmp_path / "reused.jsonl"
    session_file.write_text("{}", encoding="utf-8")

    file_id_1 = ingest._ensure_file_row(db_connection, session_file)

    # Insert some dummy data
    cursor = db_connection.cursor()
    cursor.execute(
        "INSERT INTO sessions (file_id) VALUES (?)",
        (file_id_1,),
    )
    cursor.execute(
        "INSERT INTO prompts (file_id, prompt_index) VALUES (?, ?)",
        (file_id_1, 0),
    )
    db_connection.commit()

    # Verify data was inserted
    cursor.execute("SELECT COUNT(*) FROM sessions WHERE file_id = ?", (file_id_1,))
    initial_count = cursor.fetchone()[0]
    TC.assertEqual(initial_count, 1)

    # Ensure file row again
    file_id_2 = ingest._ensure_file_row(db_connection, session_file)
    TC.assertEqual(file_id_1, file_id_2)

    # Verify previous data was cleared
    cursor.execute("SELECT COUNT(*) FROM sessions WHERE file_id = ?", (file_id_1,))
    final_count = cursor.fetchone()[0]
    TC.assertEqual(final_count, 0, "Previous sessions should be cleared")

    cursor.execute("SELECT COUNT(*) FROM prompts WHERE file_id = ?", (file_id_1,))
    prompt_count = cursor.fetchone()[0]
    TC.assertEqual(prompt_count, 0, "Previous prompts should be cleared")


def test_build_prompt_insert_with_full_payload(
    db_connection: sqlite3.Connection,
) -> None:
    """Test _build_prompt_insert with complete payload data."""
    file_id = 1
    # Insert dummy file for FK constraint
    db_connection.execute("INSERT INTO files (path) VALUES (?)", ("test.jsonl",))

    prompt_event = {
        "type": "event_msg",
        "timestamp": "2025-01-01T00:00:00Z",
        "payload": {
            "type": "user_message",
            "message": "Hello, world!",
            "activeFile": "main.py",
            "openTabs": ["main.py", "test.py"],
            "myRequest": "Help me refactor",
        },
    }

    result = ingest._build_prompt_insert(db_connection, file_id, 0, prompt_event)
    TC.assertIsInstance(result, ingest.PromptInsert)
    TC.assertEqual(result.message, "Hello, world!")
    TC.assertEqual(result.file_id, file_id)
    TC.assertEqual(result.prompt_index, 0)


def test_sanitize_json_for_storage_with_complex_data() -> None:
    """Test sanitize_json_for_storage handles nested structures."""
    complex_data = {
        "level1": {
            "level2": {
                "list": [1, 2, 3],
                "string": "value",
                "null": None,
            },
        },
        "array": ["a", "b", "c"],
    }

    result = ingest.sanitize_json_for_storage(complex_data)
    TC.assertIsInstance(result, dict)
    TC.assertIn("level1", result)
    TC.assertIsInstance(result["level1"], dict)
