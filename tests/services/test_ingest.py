"""Tests for ingest pipeline functionality.

Purpose: Test ingest pipeline code paths and coverage
Author: Codex with Claude Haiku
Date: 2025-12-07
AI-assisted: True
"""

import sqlite3
import unittest
from pathlib import Path
from typing import Any

import pytest

from src.services.database import ensure_schema, get_connection
from src.services.ingest import (
    ProcessingError,
    ErrorSeverity,
    ProcessingErrorAction,
    _ensure_file_row,
    serialize_processing_error,
    process_events_in_batches,
    sanitize_json_for_storage,
)

TC = unittest.TestCase()


class TestProcessingErrorSerialization:
    """Test error serialization for completeness."""

    def test_serialize_processing_error_with_all_fields(self) -> None:
        """serialize_processing_error should include all error fields."""
        error = ProcessingError(
            severity=ErrorSeverity.ERROR,
            code="test_error",
            message="Test error message",
            recommended_action=ProcessingErrorAction.ABORT,
            file_path=Path("test.jsonl"),
            line_number=42,
            context={"test_key": "test_value"},
        )

        result = serialize_processing_error(error)

        TC.assertEqual(result["severity"], "ERROR")
        TC.assertEqual(result["code"], "test_error")
        TC.assertEqual(result["message"], "Test error message")
        TC.assertEqual(result["recommended_action"], "ABORT")
        TC.assertEqual(result["file_path"], "test.jsonl")
        TC.assertEqual(result["line_number"], 42)
        TC.assertIsNotNone(result["context"])

    def test_serialize_processing_error_with_none_context(self) -> None:
        """serialize_processing_error should handle None context."""
        error = ProcessingError(
            severity=ErrorSeverity.WARNING,
            code="warn_error",
            message="Warning",
            recommended_action=ProcessingErrorAction.CONTINUE,
            context=None,
        )

        result = serialize_processing_error(error)
        TC.assertIsNone(result["context"])

    def test_serialize_processing_error_with_none_file_path(self) -> None:
        """serialize_processing_error should handle None file_path."""
        error = ProcessingError(
            severity=ErrorSeverity.CRITICAL,
            code="critical_error",
            message="Critical error",
            recommended_action=ProcessingErrorAction.RETRY,
            file_path=None,
        )

        result = serialize_processing_error(error)
        TC.assertIsNone(result["file_path"])


class TestProcessEventsInBatches:
    """Test batch processing of events."""

    def test_process_events_in_batches_exact_size(self) -> None:
        """process_events_in_batches should yield full batches."""
        events = [{"id": i} for i in range(10)]
        batches = list(process_events_in_batches(iter(events), batch_size=5))

        TC.assertEqual(len(batches), 2)
        TC.assertEqual(len(batches[0]), 5)
        TC.assertEqual(len(batches[1]), 5)

    def test_process_events_in_batches_partial_final(self) -> None:
        """process_events_in_batches should yield partial final batch."""
        events = [{"id": i} for i in range(12)]
        batches = list(process_events_in_batches(iter(events), batch_size=5))

        TC.assertEqual(len(batches), 3)
        TC.assertEqual(len(batches[0]), 5)
        TC.assertEqual(len(batches[1]), 5)
        TC.assertEqual(len(batches[2]), 2)

    def test_process_events_in_batches_empty(self) -> None:
        """process_events_in_batches should handle empty event stream."""
        events: list[dict[str, Any]] = []
        batches = list(process_events_in_batches(iter(events), batch_size=5))

        TC.assertEqual(len(batches), 0)

    def test_process_events_in_batches_single_event(self) -> None:
        """process_events_in_batches should yield single event in batch."""
        events = [{"id": 0}]
        batches = list(process_events_in_batches(iter(events), batch_size=5))

        TC.assertEqual(len(batches), 1)
        TC.assertEqual(len(batches[0]), 1)


class TestEnsureFileRow:
    """Test file row creation and reuse."""

    def test_ensure_file_row_creates_new_row(self, tmp_path: Path) -> None:
        """_ensure_file_row should create new file row when not exists."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        ensure_schema(conn)

        session_file = tmp_path / "test_session.jsonl"
        file_id = _ensure_file_row(conn, session_file)

        TC.assertGreater(file_id, 0)
        cursor = conn.cursor()
        cursor.execute("SELECT path FROM files WHERE id = ?", (file_id,))
        row = cursor.fetchone()
        TC.assertEqual(row[0], str(session_file))
        conn.close()

    def test_ensure_file_row_reuses_existing(self, tmp_path: Path) -> None:
        """_ensure_file_row should reuse and reset existing file row."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        ensure_schema(conn)

        session_file = tmp_path / "test_session.jsonl"

        # Create first file row
        file_id_1 = _ensure_file_row(conn, session_file)

        # Insert a prompt
        conn.execute(
            "INSERT INTO prompts (file_id, prompt_index, timestamp, message, raw_json) "
            "VALUES (?, 1, 't0', 'test', '{}')",
            (file_id_1,),
        )
        conn.commit()

        # Ensure again - should reuse and reset
        file_id_2 = _ensure_file_row(conn, session_file)

        TC.assertEqual(file_id_1, file_id_2)
        # Verify prompts were deleted
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM prompts WHERE file_id = ?", (file_id_2,))
        count = cursor.fetchone()[0]
        TC.assertEqual(count, 0)
        conn.close()


class TestSanitizeJsonForStorage:
    """Test JSON sanitization for storage."""

    def test_sanitize_json_preserves_valid_json(self) -> None:
        """sanitize_json_for_storage should preserve valid JSON data."""
        data = {
            "key": "value",
            "nested": {"inner": "data"},
            "list": [1, 2, 3],
        }

        result = sanitize_json_for_storage(data)

        TC.assertEqual(result, data)

    def test_sanitize_json_handles_complex_types(self) -> None:
        """sanitize_json_for_storage should handle complex nested structures."""
        data = {
            "string": "test",
            "number": 42,
            "float": 3.14,
            "bool": True,
            "null": None,
            "list": [1, "two", 3.0, None],
            "dict": {"nested": {"deep": "value"}},
        }

        result = sanitize_json_for_storage(data)

        TC.assertEqual(result["string"], "test")
        TC.assertEqual(result["number"], 42)
        TC.assertTrue(result["bool"])
        TC.assertIsNone(result["null"])
