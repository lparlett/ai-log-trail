"""Comprehensive branch coverage and edge case tests for session ingestion."""

# pylint: disable=import-error,protected-access,import-outside-toplevel

from __future__ import annotations

import json
import logging
import unittest
from pathlib import Path
from typing import Any

import pytest

from src.services.database import get_connection, ensure_schema
from src.services.ingest import (
    ErrorSeverity,
    ProcessingError,
    ProcessingErrorAction,
    SessionIngester,
    _apply_rule_applications_for_event,
    _apply_rule_applications_for_prompt,
    _apply_rule_applications_for_text,
    _apply_rule_applications_pre_prompt,
    _build_prompt_insert,
    _create_empty_summary,
    _load_rules_safely,
    _log_processing_error,
    _prepare_events,
    _process_events,
    ingest_session_file,
    serialize_processing_error,
)
from src.services.redaction_rules import RedactionRule

TC = unittest.TestCase()


class TestErrorSeverityBranches:
    """Test all ErrorSeverity logging branches in _log_processing_error."""

    def test_log_processing_error_warning_severity(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test WARNING severity branch in _log_processing_error."""
        error = ProcessingError(
            severity=ErrorSeverity.WARNING,
            code="test_warning",
            message="This is a warning",
            recommended_action=ProcessingErrorAction.CONTINUE,
            file_path=Path("test.jsonl"),
            line_number=10,
            context=None,
        )
        with caplog.at_level(logging.WARNING):
            _log_processing_error(error)
        TC.assertIn("test_warning", caplog.text)
        TC.assertIn("This is a warning", caplog.text)

    def test_log_processing_error_error_severity(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test ERROR severity branch in _log_processing_error."""
        error = ProcessingError(
            severity=ErrorSeverity.ERROR,
            code="test_error",
            message="This is an error",
            recommended_action=ProcessingErrorAction.RETRY,
            file_path=Path("test.jsonl"),
            line_number=20,
            context=None,
        )
        with caplog.at_level(logging.ERROR):
            _log_processing_error(error)
        TC.assertIn("test_error", caplog.text)
        TC.assertIn("This is an error", caplog.text)

    def test_log_processing_error_critical_severity(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test CRITICAL severity branch in _log_processing_error."""
        error = ProcessingError(
            severity=ErrorSeverity.CRITICAL,
            code="test_critical",
            message="This is critical",
            recommended_action=ProcessingErrorAction.ABORT,
            file_path=Path("critical.jsonl"),
            line_number=999,
            context=None,
        )
        with caplog.at_level(logging.CRITICAL):
            _log_processing_error(error)
        TC.assertIn("test_critical", caplog.text)
        TC.assertIn("This is critical", caplog.text)

    def test_log_processing_error_with_no_file_path(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test error logging when file_path is None."""
        error = ProcessingError(
            severity=ErrorSeverity.WARNING,
            code="no_file",
            message="No file path",
            recommended_action=ProcessingErrorAction.CONTINUE,
            file_path=None,
            line_number=None,
            context=None,
        )
        with caplog.at_level(logging.WARNING):
            _log_processing_error(error)
        TC.assertIn("no_file", caplog.text)
        TC.assertIn("No file path", caplog.text)

    def test_log_processing_error_with_file_but_no_line(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test error logging when file_path exists but line_number is None."""
        error = ProcessingError(
            severity=ErrorSeverity.ERROR,
            code="no_line",
            message="File but no line",
            recommended_action=ProcessingErrorAction.RETRY,
            file_path=Path("test.jsonl"),
            line_number=None,
            context=None,
        )
        with caplog.at_level(logging.ERROR):
            _log_processing_error(error)
        TC.assertIn("no_line", caplog.text)
        TC.assertIn("test.jsonl", caplog.text)
        TC.assertNotIn(":None", caplog.text)

    def test_log_processing_error_with_context(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test error logging when context data is present."""
        error = ProcessingError(
            severity=ErrorSeverity.WARNING,
            code="with_context",
            message="Has context",
            recommended_action=ProcessingErrorAction.CONTINUE,
            file_path=Path("test.jsonl"),
            line_number=5,
            context={"key": "value", "nested": {"data": "here"}},
        )
        with caplog.at_level(logging.WARNING):
            _log_processing_error(error)
        TC.assertIn("with_context", caplog.text)
        TC.assertIn("context=", caplog.text)


class TestErrorSerializationBranches:
    """Test optional field handling in serialize_processing_error."""

    def test_serialize_error_with_all_fields(self, tmp_path: Path) -> None:
        """Serialize error with all fields populated."""
        error = ProcessingError(
            severity=ErrorSeverity.ERROR,
            code="full_error",
            message="Full error message",
            recommended_action=ProcessingErrorAction.RETRY,
            file_path=tmp_path / "test.jsonl",
            line_number=42,
            context={"data": "test_value"},
        )
        serialized = serialize_processing_error(error)
        TC.assertEqual(serialized["severity"], "ERROR")
        TC.assertEqual(serialized["code"], "full_error")
        TC.assertEqual(serialized["message"], "Full error message")
        TC.assertEqual(serialized["recommended_action"], "RETRY")
        TC.assertTrue(serialized["file_path"].endswith("test.jsonl"))
        TC.assertEqual(serialized["line_number"], 42)
        TC.assertIsNotNone(serialized["context"])

    def test_serialize_error_with_no_file_path(self) -> None:
        """Serialize error when file_path is None."""
        error = ProcessingError(
            severity=ErrorSeverity.WARNING,
            code="no_file",
            message="No file",
            recommended_action=ProcessingErrorAction.CONTINUE,
            file_path=None,
            line_number=None,
            context=None,
        )
        serialized = serialize_processing_error(error)
        TC.assertIsNone(serialized["file_path"])
        TC.assertIsNone(serialized["line_number"])
        TC.assertIsNone(serialized["context"])

    def test_serialize_error_with_no_context(self, tmp_path: Path) -> None:
        """Serialize error when context is None."""
        error = ProcessingError(
            severity=ErrorSeverity.CRITICAL,
            code="no_context",
            message="Context-less",
            recommended_action=ProcessingErrorAction.ABORT,
            file_path=tmp_path / "test.jsonl",
            line_number=10,
            context=None,
        )
        serialized = serialize_processing_error(error)
        TC.assertIsNone(serialized["context"])
        TC.assertEqual(serialized["code"], "no_context")


class TestRuleLoadingBranches:
    """Test error handling in _load_rules_safely."""

    def test_load_rules_safely_missing_file_verbose_false(self, tmp_path: Path) -> None:
        """Test _load_rules_safely when rules file is missing and verbose=False."""
        nonexistent = tmp_path / "nonexistent_rules.yml"
        result = _load_rules_safely(nonexistent, verbose=False)
        TC.assertIsNone(result)

    def test_load_rules_safely_missing_file_verbose_true(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test _load_rules_safely when rules file is missing and verbose=True."""
        nonexistent = tmp_path / "nonexistent_rules.yml"
        with caplog.at_level(logging.WARNING):
            result = _load_rules_safely(nonexistent, verbose=True)
        TC.assertIsNone(result)
        TC.assertIn("Failed to load rules", caplog.text)
        TC.assertIn("continuing ingest without rule logging", caplog.text)

    def test_load_rules_safely_invalid_yaml_verbose_true(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test _load_rules_safely with invalid YAML and verbose=True."""
        invalid_rules = tmp_path / "invalid_rules.yml"
        invalid_rules.write_text("{ invalid yaml content: [", encoding="utf-8")

        with caplog.at_level(logging.WARNING):
            result = _load_rules_safely(invalid_rules, verbose=True)
        TC.assertIsNone(result)
        TC.assertIn("Failed to load rules", caplog.text)


class TestEventPayloadTypeBranches:
    """Test payload type checking branches in event processing."""

    def test_prepare_events_with_non_dict_payload(self, tmp_path: Path) -> None:
        """Test _prepare_events skips events with non-dict payloads."""
        raw_events: list[dict[str, Any]] = [
            {"type": "event_msg", "payload": None},
            {"type": "event_msg", "payload": "string"},
            {"type": "event_msg", "payload": 123},
            {"type": "event_msg", "payload": []},
            {
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "valid"},
            },
        ]
        test_file = tmp_path / "test.jsonl"
        test_file.write_text("", encoding="utf-8")
        errors: list[ProcessingError] = []

        prepared = _prepare_events(raw_events, test_file, errors, batch_size=10)

        TC.assertGreater(len(errors), 0)
        TC.assertGreaterEqual(len(prepared), 1)

    def test_build_prompt_insert_with_non_dict_payload(self, tmp_path: Path) -> None:
        """Test _build_prompt_insert handles non-dict payloads gracefully."""
        conn = get_connection(tmp_path / "test.sqlite")
        ensure_schema(conn)

        # Insert a file
        cursor = conn.execute("INSERT INTO files (path) VALUES (?)", ("test.jsonl",))
        file_id = int(cursor.lastrowid or 0)

        # Test with None payload
        prompt_event_none = {
            "type": "user_message",
            "timestamp": "2025-01-01T00:00:00Z",
            "payload": None,
        }
        result = _build_prompt_insert(conn, file_id, 1, prompt_event_none)
        TC.assertEqual(result.message, "")

        # Test with string payload
        prompt_event_str = {
            "type": "user_message",
            "timestamp": "2025-01-01T00:00:00Z",
            "payload": "not a dict",
        }
        result = _build_prompt_insert(conn, file_id, 2, prompt_event_str)
        TC.assertEqual(result.message, "")

        # Test with dict but missing message
        prompt_event_no_msg = {
            "type": "user_message",
            "timestamp": "2025-01-01T00:00:00Z",
            "payload": {"other_field": "value"},
        }
        result = _build_prompt_insert(conn, file_id, 3, prompt_event_no_msg)
        TC.assertEqual(result.message, "")

        # Test with None message value
        prompt_event_none_msg = {
            "type": "user_message",
            "timestamp": "2025-01-01T00:00:00Z",
            "payload": {"message": None},
        }
        result = _build_prompt_insert(conn, file_id, 4, prompt_event_none_msg)
        TC.assertEqual(result.message, "")

        conn.close()


class TestEventProcessingBranches:
    """Test conditional branches in event type handling."""

    def test_process_events_with_unknown_event_type(self, tmp_path: Path) -> None:
        """Test _process_events ignores unknown event types."""
        conn = get_connection(tmp_path / "test.sqlite")
        ensure_schema(conn)

        # Set up file and prompt
        cursor = conn.execute("INSERT INTO files (path) VALUES (?)", ("test.jsonl",))
        file_id = int(cursor.lastrowid or 0)
        cursor = conn.execute(
            "INSERT INTO sessions (file_id, session_id, session_timestamp) "
            "VALUES (?, ?, ?)",
            (file_id, "sess1", "2025-01-01T00:00:00Z"),
        )
        cursor = conn.execute(
            "INSERT INTO prompts (file_id, prompt_index, timestamp, message) "
            "VALUES (?, ?, ?, ?)",
            (file_id, 1, "2025-01-01T00:00:00Z", "Test"),
        )
        prompt_id = int(cursor.lastrowid or 0)

        # Unknown event type should be silently ignored
        events = [
            {
                "type": "unknown_event_type",
                "payload": {"data": "test"},
                "timestamp": "2025-01-01T00:00:00Z",
            },
        ]

        counts = _process_events(conn, file_id, prompt_id, events)

        TC.assertEqual(counts["token_messages"], 0)
        TC.assertEqual(counts["turn_context_messages"], 0)
        TC.assertEqual(counts["function_calls"], 0)

        conn.close()

    def test_process_events_skips_non_dict_payloads(self, tmp_path: Path) -> None:
        """Test _process_events skips events with non-dict payloads."""
        conn = get_connection(tmp_path / "test.sqlite")
        ensure_schema(conn)

        # Set up file and prompt
        cursor = conn.execute("INSERT INTO files (path) VALUES (?)", ("test.jsonl",))
        file_id = int(cursor.lastrowid or 0)
        cursor = conn.execute(
            "INSERT INTO sessions (file_id, session_id, session_timestamp) "
            "VALUES (?, ?, ?)",
            (file_id, "sess1", "2025-01-01T00:00:00Z"),
        )
        cursor = conn.execute(
            "INSERT INTO prompts (file_id, prompt_index, timestamp, message) "
            "VALUES (?, ?, ?, ?)",
            (file_id, 1, "2025-01-01T00:00:00Z", "Test"),
        )
        prompt_id = int(cursor.lastrowid or 0)

        # Event with non-dict payload should be skipped
        events: list[dict[str, Any]] = [
            {"type": "event_msg", "payload": None},
            {"type": "event_msg", "payload": "string"},
            {"type": "turn_context", "payload": []},
        ]

        counts = _process_events(conn, file_id, prompt_id, events)

        TC.assertEqual(sum(counts.values()), 0)

        conn.close()


class TestProcessEventsInBatches:
    """Test batch processing of events."""

    def test_process_events_in_batches_exact_batch_size(self) -> None:
        """Batches should be emitted at exact batch_size boundary."""
        from src.services.ingest import process_events_in_batches

        events = [{"id": i} for i in range(10)]
        batches = list(process_events_in_batches(iter(events), batch_size=5))

        TC.assertEqual(len(batches), 2)
        TC.assertEqual(len(batches[0]), 5)
        TC.assertEqual(len(batches[1]), 5)

    def test_process_events_in_batches_partial_final_batch(self) -> None:
        """Final batch can be smaller than batch_size."""
        from src.services.ingest import process_events_in_batches

        events = [{"id": i} for i in range(7)]
        batches = list(process_events_in_batches(iter(events), batch_size=5))

        TC.assertEqual(len(batches), 2)
        TC.assertEqual(len(batches[0]), 5)
        TC.assertEqual(len(batches[1]), 2)

    def test_process_events_in_batches_empty_iterator(self) -> None:
        """Empty iterator should yield no batches."""
        from src.services.ingest import process_events_in_batches

        events: list[dict[str, Any]] = []
        batches = list(process_events_in_batches(iter(events), batch_size=5))

        TC.assertEqual(len(batches), 0)

    def test_process_events_in_batches_single_item(self) -> None:
        """Single item should be in one batch."""
        from src.services.ingest import process_events_in_batches

        events = [{"id": 1}]
        batches = list(process_events_in_batches(iter(events), batch_size=5))

        TC.assertEqual(len(batches), 1)
        TC.assertEqual(len(batches[0]), 1)

    def test_process_events_in_batches_batch_size_one(self) -> None:
        """Batch size of 1 should yield individual batches."""
        from src.services.ingest import process_events_in_batches

        events = [{"id": i} for i in range(3)]
        batches = list(process_events_in_batches(iter(events), batch_size=1))

        TC.assertEqual(len(batches), 3)
        TC.assertTrue(all(len(batch) == 1 for batch in batches))


class TestEnsureFileRow:
    """Test file row creation and update logic."""

    def test_ensure_file_row_creates_new_file(self, tmp_path: Path) -> None:
        """_ensure_file_row should create a new file row if not exists."""
        from src.services.ingest import _ensure_file_row

        conn = get_connection(tmp_path / "test.sqlite")
        ensure_schema(conn)

        file_path = Path("new_session.jsonl")
        file_id = _ensure_file_row(conn, file_path)

        TC.assertIsNotNone(file_id)
        TC.assertGreater(file_id, 0)

        # Verify file was inserted
        cursor = conn.execute(
            "SELECT path FROM files WHERE id = ?",
            (file_id,),
        )
        result = cursor.fetchone()
        TC.assertIsNotNone(result)
        TC.assertEqual(result[0], str(file_path))
        conn.close()

    def test_ensure_file_row_returns_existing_file_id(self, tmp_path: Path) -> None:
        """_ensure_file_row should return existing file_id if file exists."""
        from src.services.ingest import _ensure_file_row

        conn = get_connection(tmp_path / "test.sqlite")
        ensure_schema(conn)

        file_path = Path("existing_session.jsonl")
        file_id_1 = _ensure_file_row(conn, file_path)
        file_id_2 = _ensure_file_row(conn, file_path)

        TC.assertEqual(file_id_1, file_id_2)

        # Should only have one file row
        cursor = conn.execute(
            "SELECT COUNT(*) FROM files WHERE path = ?",
            (str(file_path),),
        )
        count = cursor.fetchone()[0]
        TC.assertEqual(count, 1)
        conn.close()

    def test_ensure_file_row_clears_prompts_and_sessions(self, tmp_path: Path) -> None:
        """_ensure_file_row should delete existing prompts and sessions."""
        from src.services.ingest import _ensure_file_row

        conn = get_connection(tmp_path / "test.sqlite")
        ensure_schema(conn)

        file_path = Path("session_to_reset.jsonl")
        file_id = _ensure_file_row(conn, file_path)

        # Insert some prompt and session data
        conn.execute(
            "INSERT INTO prompts (file_id, prompt_index, timestamp, message) "
            "VALUES (?, ?, ?, ?)",
            (file_id, 1, "2025-01-01T00:00:00Z", "Test message"),
        )
        conn.execute(
            "INSERT INTO sessions (file_id, session_id, session_timestamp) "
            "VALUES (?, ?, ?)",
            (file_id, "test_session", "2025-01-01T00:00:00Z"),
        )
        conn.commit()

        # Verify data was inserted
        TC.assertEqual(conn.execute("SELECT COUNT(*) FROM prompts").fetchone()[0], 1)
        TC.assertEqual(conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 1)

        # Call _ensure_file_row again
        file_id_2 = _ensure_file_row(conn, file_path)

        # Data should be cleared
        TC.assertEqual(file_id, file_id_2)
        TC.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM prompts WHERE file_id = ?", (file_id,)
            ).fetchone()[0],
            0,
        )
        TC.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE file_id = ?", (file_id,)
            ).fetchone()[0],
            0,
        )
        conn.close()


class TestCreateAndUpdateSummary:
    """Test summary creation and count updates."""

    def test_create_empty_summary(self, tmp_path: Path) -> None:
        """_create_empty_summary should initialize all fields."""
        session_file = tmp_path / "test.jsonl"
        file_id = 42

        summary = _create_empty_summary(session_file, file_id)

        TC.assertEqual(summary["session_file"], str(session_file))
        TC.assertEqual(summary["file_id"], file_id)
        TC.assertEqual(summary["prompts"], 0)
        TC.assertEqual(summary["token_messages"], 0)
        TC.assertEqual(summary["turn_context_messages"], 0)
        TC.assertEqual(summary["agent_reasoning_messages"], 0)
        TC.assertEqual(summary["function_plan_messages"], 0)
        TC.assertEqual(summary["function_calls"], 0)
        TC.assertEqual(summary["errors"], [])

    def test_update_summary_counts_increments_prompts(self, tmp_path: Path) -> None:
        """_update_summary_counts should increment prompts by 1."""
        from src.services.ingest import _update_summary_counts

        session_file = tmp_path / "test.jsonl"
        summary = _create_empty_summary(session_file, 1)
        counts: dict[str, int] = {
            "token_messages": 2,
            "turn_context_messages": 1,
            "agent_reasoning_messages": 0,
            "function_plan_messages": 0,
            "function_calls": 1,
        }

        _update_summary_counts(summary, counts)

        TC.assertEqual(summary["prompts"], 1)
        TC.assertEqual(summary["token_messages"], 2)
        TC.assertEqual(summary["turn_context_messages"], 1)
        TC.assertEqual(summary["function_calls"], 1)

    def test_update_summary_counts_multiple_calls(self, tmp_path: Path) -> None:
        """_update_summary_counts should accumulate across multiple calls."""
        from src.services.ingest import _update_summary_counts

        session_file = tmp_path / "test.jsonl"
        summary = _create_empty_summary(session_file, 1)

        counts1 = {
            "token_messages": 1,
            "turn_context_messages": 0,
            "agent_reasoning_messages": 0,
            "function_plan_messages": 0,
            "function_calls": 0,
        }
        counts2 = {
            "token_messages": 2,
            "turn_context_messages": 1,
            "agent_reasoning_messages": 1,
            "function_plan_messages": 0,
            "function_calls": 2,
        }

        _update_summary_counts(summary, counts1)
        _update_summary_counts(summary, counts2)

        TC.assertEqual(summary["prompts"], 2)
        TC.assertEqual(summary["token_messages"], 3)
        TC.assertEqual(summary["turn_context_messages"], 1)
        TC.assertEqual(summary["agent_reasoning_messages"], 1)
        TC.assertEqual(summary["function_calls"], 2)

    def test_update_summary_handles_missing_count_keys(self, tmp_path: Path) -> None:
        """_update_summary_counts should handle missing keys gracefully."""
        from src.services.ingest import _update_summary_counts

        session_file = tmp_path / "test.jsonl"
        summary = _create_empty_summary(session_file, 1)
        counts: dict[str, int] = {}  # Empty counts dict

        _update_summary_counts(summary, counts)

        TC.assertEqual(summary["prompts"], 1)
        TC.assertEqual(summary["token_messages"], 0)
        TC.assertEqual(summary["turn_context_messages"], 0)


class TestSessionIngesterVerboseMode:
    """Test SessionIngester verbose logging behavior."""

    def test_session_ingester_verbose_mode_logs_ingestion(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """SessionIngester with verbose=True should log ingestion start."""
        conn = get_connection(tmp_path / "test.sqlite")
        ensure_schema(conn)

        session_file = tmp_path / "session.jsonl"
        session_file.write_text(
            json.dumps({"type": "event_msg", "payload": {}}) + "\n",
            encoding="utf-8",
        )

        with caplog.at_level(logging.INFO):
            _ = SessionIngester(
                conn=conn,
                session_file=session_file,
                batch_size=10,
                verbose=True,
                errors=[],
                rules=None,
            )

        TC.assertIn("Ingesting", caplog.text)
        TC.assertIn(str(session_file), caplog.text)
        conn.close()

    def test_session_ingester_non_verbose_mode_no_log(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """SessionIngester with verbose=False should not log ingestion."""
        conn = get_connection(tmp_path / "test.sqlite")
        ensure_schema(conn)

        session_file = tmp_path / "session.jsonl"
        session_file.write_text(
            json.dumps({"type": "event_msg", "payload": {}}) + "\n",
            encoding="utf-8",
        )

        with caplog.at_level(logging.INFO):
            _ = SessionIngester(
                conn=conn,
                session_file=session_file,
                batch_size=10,
                verbose=False,
                errors=[],
                rules=None,
            )

        TC.assertNotIn("Ingesting", caplog.text)
        conn.close()


class TestIngestSessionFileWithRules:
    """Test ingest_session_file with rule loading."""

    def test_ingest_session_file_with_missing_rules_path(self, tmp_path: Path) -> None:
        """ingest_session_file should handle missing rules gracefully."""
        session_file = tmp_path / "session.jsonl"
        session_file.write_text(
            json.dumps({"type": "event_msg", "payload": {}}) + "\n",
            encoding="utf-8",
        )
        db_path = tmp_path / "db.sqlite"

        summary = ingest_session_file(
            session_file,
            db_path,
            rules_path=tmp_path / "nonexistent_rules.yml",
            verbose=False,
        )

        TC.assertIsNotNone(summary)
        TC.assertIn("file_id", summary)
        TC.assertIn("errors", summary)

    def test_ingest_sessions_in_directory_with_single_file(
        self, tmp_path: Path
    ) -> None:
        """ingest_sessions_in_directory should ingest single file in directory."""
        from src.services.ingest import ingest_sessions_in_directory

        session_dir = tmp_path / "sessions" / "2025" / "01" / "01"
        session_dir.mkdir(parents=True, exist_ok=True)

        session_file = session_dir / "session.jsonl"
        session_file.write_text(
            json.dumps({"type": "event_msg", "payload": {}}) + "\n",
            encoding="utf-8",
        )

        db_path = tmp_path / "db.sqlite"

        summaries = list(
            ingest_sessions_in_directory(
                tmp_path / "sessions",
                db_path,
                limit=1,
                verbose=False,
            )
        )

        TC.assertEqual(len(summaries), 1)
        TC.assertIn("file_id", summaries[0])

    def test_ingest_sessions_in_directory_with_limit(self, tmp_path: Path) -> None:
        """ingest_sessions_in_directory should respect limit parameter."""
        from src.services.ingest import ingest_sessions_in_directory

        # Create multiple session files
        for i in range(3):
            session_dir = tmp_path / "sessions" / "2025" / f"0{i+1}" / "01"
            session_dir.mkdir(parents=True, exist_ok=True)
            session_file = session_dir / f"session_{i}.jsonl"
            session_file.write_text(
                json.dumps({"type": "event_msg", "payload": {}}) + "\n",
                encoding="utf-8",
            )

        db_path = tmp_path / "db.sqlite"

        summaries = list(
            ingest_sessions_in_directory(
                tmp_path / "sessions",
                db_path,
                limit=2,
                verbose=False,
            )
        )

        TC.assertEqual(len(summaries), 2)


class TestRuleApplicationFunctions:
    """Test rule application helper functions."""

    def test_apply_rule_applications_for_text_with_empty_text(
        self, tmp_path: Path
    ) -> None:
        """_apply_rule_applications_for_text should skip empty text."""
        db_path = tmp_path / "test.db"
        with get_connection(db_path) as conn:
            ensure_schema(conn)
            _apply_rule_applications_for_text(
                conn=conn,
                rules=[],
                file_id=1,
                prompt_id=1,
                session_file_path="test.jsonl",
                text="",
                scope="prompt",
                field_path="prompt.message",
            )

    def test_apply_rule_applications_for_event_with_unknown_event_type(
        self, tmp_path: Path
    ) -> None:
        """_apply_rule_applications_for_event should handle unknown event types."""
        conn = get_connection(tmp_path / "test.sqlite")
        ensure_schema(conn)

        cursor = conn.execute("INSERT INTO files (path) VALUES (?)", ("test.jsonl",))
        file_id = int(cursor.lastrowid or 0)

        event = {
            "type": "unknown_type",
            "payload": {"data": "test"},
        }

        rules: list[RedactionRule] = []

        _apply_rule_applications_for_event(
            conn=conn,
            rules=rules,
            file_id=file_id,
            prompt_id=1,
            session_file_path="test.jsonl",
            event=event,
        )

        conn.close()

    def test_apply_rule_applications_pre_prompt_with_empty_prelude(
        self, tmp_path: Path
    ) -> None:
        """_apply_rule_applications_pre_prompt should handle empty prelude."""
        conn = get_connection(tmp_path / "test.sqlite")
        ensure_schema(conn)

        cursor = conn.execute("INSERT INTO files (path) VALUES (?)", ("test.jsonl",))
        file_id = int(cursor.lastrowid or 0)

        rules: list[RedactionRule] = []
        prelude: list[dict[str, Any]] = []

        _apply_rule_applications_pre_prompt(
            conn=conn,
            rules=rules,
            file_id=file_id,
            session_file_path="test.jsonl",
            prelude=prelude,
        )

        conn.close()

    def test_apply_rule_applications_for_prompt_with_missing_payload(
        self, tmp_path: Path
    ) -> None:
        """_apply_rule_applications_for_prompt should handle missing payload."""
        conn = get_connection(tmp_path / "test.sqlite")
        ensure_schema(conn)

        cursor = conn.execute("INSERT INTO files (path) VALUES (?)", ("test.jsonl",))
        file_id = int(cursor.lastrowid or 0)

        prompt_event = {"type": "user_message", "payload": None}
        events: list[dict[str, Any]] = []
        rules: list[RedactionRule] = []

        _apply_rule_applications_for_prompt(
            conn=conn,
            rules=rules,
            file_id=file_id,
            prompt_id=1,
            session_file_path="test.jsonl",
            prompt_event=prompt_event,
            events=events,
        )

        conn.close()


class TestIngestSessionFileEdgeCases:
    """Test edge cases in session file ingestion."""

    def test_ingest_session_file_with_verbose_enabled(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """ingest_session_file with verbose=True should log information."""
        session_file = tmp_path / "session.jsonl"
        session_file.write_text(
            json.dumps({"type": "event_msg", "payload": {}}) + "\n",
            encoding="utf-8",
        )
        db_path = tmp_path / "db.sqlite"

        with caplog.at_level(logging.INFO):
            summary = ingest_session_file(
                session_file,
                db_path,
                verbose=True,
            )

        TC.assertIsNotNone(summary)
        TC.assertIn("file_id", summary)

    def test_ingest_session_file_multiple_times_same_file(self, tmp_path: Path) -> None:
        """ingest_session_file should handle re-ingestion of same file."""
        session_file = tmp_path / "session.jsonl"
        session_file.write_text(
            json.dumps({"type": "event_msg", "payload": {}}) + "\n",
            encoding="utf-8",
        )
        db_path = tmp_path / "db.sqlite"

        summary1 = ingest_session_file(session_file, db_path)
        TC.assertIsNotNone(summary1)

        summary2 = ingest_session_file(session_file, db_path)
        TC.assertIsNotNone(summary2)

        conn = get_connection(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM files WHERE path = ?",
            (str(session_file),),
        ).fetchone()[0]
        conn.close()

        TC.assertEqual(count, 1)

    def test_ingest_sessions_in_directory_empty_directory(self, tmp_path: Path) -> None:
        """ingest_sessions_in_directory should raise when no files found."""
        from src.services.ingest import ingest_sessions_in_directory
        from src.parsers.session_parser import SessionDiscoveryError

        empty_dir = tmp_path / "empty"
        empty_dir.mkdir(parents=True, exist_ok=True)
        db_path = tmp_path / "db.sqlite"

        with pytest.raises(SessionDiscoveryError):
            list(ingest_sessions_in_directory(empty_dir, db_path, verbose=False))


class TestDatabaseErrorPaths:
    """Test error handling in database operations."""

    # pylint: disable=too-few-public-methods
    # Justification: Single test method for database error path is sufficient
    def test_ensure_file_row_with_existing_file(self, tmp_path: Path) -> None:
        """_ensure_file_row should return existing id and clear prompts/sessi
        ons."""
        from src.services.ingest import _ensure_file_row

        conn = get_connection(tmp_path / "db.sqlite")
        ensure_schema(conn)

        session_file = tmp_path / "session.jsonl"

        # First call: creates file
        file_id_1 = _ensure_file_row(conn, session_file)
        TC.assertGreater(file_id_1, 0)

        # Insert some test data
        conn.execute(
            "INSERT INTO prompts (file_id, prompt_index) VALUES (?, ?)",
            (file_id_1, 0),
        )
        conn.commit()

        prompt_count_before = conn.execute(
            "SELECT COUNT(*) FROM prompts WHERE file_id = ?", (file_id_1,)
        ).fetchone()[0]
        TC.assertEqual(prompt_count_before, 1)

        # Second call: should clear prompts and return existing id
        file_id_2 = _ensure_file_row(conn, session_file)
        TC.assertEqual(file_id_1, file_id_2)

        prompt_count_after = conn.execute(
            "SELECT COUNT(*) FROM prompts WHERE file_id = ?", (file_id_1,)
        ).fetchone()[0]
        TC.assertEqual(prompt_count_after, 0)

        conn.close()
