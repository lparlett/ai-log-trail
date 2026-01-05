"""Semantic coverage tests for database utilities and insertion operations.

Purpose: Test the data persistence layer (db_agent_utils.py) with realistic
scenarios including cascade deletes, field preservation, and edge cases.
Author: AI-assisted
Date: 2026-01-04
Related: src/parsers/handlers/db_agent_utils.py, src/services/database.py
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterator

import pytest

from src.services.database import ensure_schema
from src.parsers.handlers.db_agent_utils import (
    FileInsert,
    SessionInsert,
    InteractionInsert,
    insert_file,
    insert_session,
    insert_interaction,
)


@pytest.fixture(name="db_conn")
def fixture_db_conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """Create temporary SQLite database with schema."""
    db_path = tmp_path / "test.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")  # Enable foreign key constraints
    ensure_schema(conn)
    yield conn
    conn.close()


class TestFileInsertion:
    """Test file record insertion and basic operations."""

    def test_insert_single_file_codex(self, db_conn: sqlite3.Connection) -> None:
        """Test inserting a Codex file record."""
        file_insert = FileInsert(path="/path/session.jsonl", agent_type="codex")
        file_id = insert_file(db_conn, file_insert)

        if file_id <= 0:
            raise AssertionError("File ID should be positive integer")

        cursor = db_conn.cursor()
        cursor.execute("SELECT path, agent_type FROM files WHERE id = ?", (file_id,))
        row = cursor.fetchone()
        if not row:
            raise AssertionError("File record not found")
        if row[0] != "/path/session.jsonl":
            raise AssertionError(f"Expected path '/path/session.jsonl', got {row[0]}")
        if row[1] != "codex":
            raise AssertionError(f"Expected agent_type 'codex', got {row[1]}")

    def test_insert_file_copilot(self, db_conn: sqlite3.Connection) -> None:
        """Test inserting a CoPilot file record."""
        file_insert = FileInsert(path="/path/copilot.json", agent_type="copilot")
        file_id = insert_file(db_conn, file_insert)

        cursor = db_conn.cursor()
        cursor.execute("SELECT agent_type FROM files WHERE id = ?", (file_id,))
        agent_type = cursor.fetchone()[0]
        if agent_type != "copilot":
            raise AssertionError(f"Expected 'copilot', got {agent_type}")

    def test_insert_file_with_special_path(self, db_conn: sqlite3.Connection) -> None:
        """Test inserting file with special characters in path."""
        special_path = "/path/with spaces & special!@#$.jsonl"
        file_insert = FileInsert(path=special_path, agent_type="codex")
        file_id = insert_file(db_conn, file_insert)

        cursor = db_conn.cursor()
        cursor.execute("SELECT path FROM files WHERE id = ?", (file_id,))
        stored_path = cursor.fetchone()[0]
        if stored_path != special_path:
            raise AssertionError(
                f"Path not preserved: expected {special_path}, got {stored_path}"
            )


class TestSessionInsertion:
    """Test session record insertion and relationships."""

    def test_insert_session_basic(self, db_conn: sqlite3.Connection) -> None:
        """Test basic session insertion."""
        file_insert = FileInsert(path="/path/file.jsonl", agent_type="codex")
        file_id = insert_file(db_conn, file_insert)

        session_insert = SessionInsert(
            file_id=file_id,
            agent_type="codex",
            agent_session_id="session-123",
            agent_metadata={"model": "gpt-4"},
        )
        session_id = insert_session(db_conn, session_insert)

        if session_id <= 0:
            raise AssertionError("Session ID should be positive")

        cursor = db_conn.cursor()
        cursor.execute(
            "SELECT agent_session_id FROM sessions WHERE id = ?", (session_id,)
        )
        stored_id = cursor.fetchone()[0]
        if stored_id != "session-123":
            raise AssertionError(f"Session ID not preserved: {stored_id}")

    def test_insert_session_preserves_metadata(
        self, db_conn: sqlite3.Connection
    ) -> None:
        """Test that complex metadata survives roundtrip."""
        file_insert = FileInsert(path="/path/file.jsonl", agent_type="codex")
        file_id = insert_file(db_conn, file_insert)

        metadata = {
            "model": "claude-3.5",
            "temperature": 0.8,
            "capabilities": ["code", "text", "analysis"],
            "nested": {"config": {"verbose": True}},
        }
        session_insert = SessionInsert(
            file_id=file_id,
            agent_type="codex",
            agent_session_id="meta-test",
            agent_metadata=metadata,
        )
        session_id = insert_session(db_conn, session_insert)

        cursor = db_conn.cursor()
        cursor.execute(
            "SELECT agent_metadata FROM sessions WHERE id = ?", (session_id,)
        )
        metadata_json = cursor.fetchone()[0]
        restored = json.loads(metadata_json)

        if restored != metadata:
            raise AssertionError(f"Metadata not preserved: {restored} != {metadata}")

    def test_insert_session_empty_metadata(self, db_conn: sqlite3.Connection) -> None:
        """Test session with empty metadata dict."""
        file_insert = FileInsert(path="/path/file.jsonl", agent_type="codex")
        file_id = insert_file(db_conn, file_insert)

        session_insert = SessionInsert(
            file_id=file_id,
            agent_type="codex",
            agent_session_id="empty",
            agent_metadata={},
        )
        session_id = insert_session(db_conn, session_insert)

        cursor = db_conn.cursor()
        cursor.execute(
            "SELECT agent_metadata FROM sessions WHERE id = ?", (session_id,)
        )
        metadata_json = cursor.fetchone()[0]
        restored = json.loads(metadata_json)

        if restored != {}:
            raise AssertionError(f"Expected empty dict, got {restored}")


class TestInteractionInsertion:
    """Test interaction record insertion with various payloads."""

    def test_insert_interaction_full_fields(self, db_conn: sqlite3.Connection) -> None:
        """Test interaction with all fields populated."""
        file_insert = FileInsert(path="/path/file.jsonl", agent_type="codex")
        file_id = insert_file(db_conn, file_insert)

        session_insert = SessionInsert(
            file_id=file_id,
            agent_type="codex",
            agent_session_id="session-1",
            agent_metadata={},
        )
        session_id = insert_session(db_conn, session_insert)

        interaction_insert = InteractionInsert(
            file_id=file_id,
            session_id=session_id,
            agent_type="codex",
            interaction_index=1,
            timestamp="2025-01-04T10:00:00Z",
            agent_user_input="What is Python?",
            agent_context={"language": "python"},
            agent_response={"answer": "Python is a programming language."},
            raw_json=json.dumps({"event_type": "user_message"}),
        )
        interaction_id = insert_interaction(db_conn, interaction_insert)

        if interaction_id <= 0:
            raise AssertionError("Interaction ID should be positive")

        cursor = db_conn.cursor()
        cursor.execute(
            "SELECT agent_user_input, agent_response FROM interactions WHERE id = ?",
            (interaction_id,),
        )
        row = cursor.fetchone()
        if row[0] != "What is Python?":
            raise AssertionError(f"User input not preserved: {row[0]}")
        # Response is stored as JSON string
        stored_response = row[1]
        response_dict = json.loads(stored_response)
        if response_dict.get("answer") != "Python is a programming language.":
            raise AssertionError(f"Response not preserved: {row[1]}")

    def test_insert_interaction_special_characters(
        self, db_conn: sqlite3.Connection
    ) -> None:
        """Test interaction with special chars and unicode."""
        file_insert = FileInsert(path="/path/file.jsonl", agent_type="codex")
        file_id = insert_file(db_conn, file_insert)

        session_insert = SessionInsert(
            file_id=file_id,
            agent_type="codex",
            agent_session_id="session-1",
            agent_metadata={},
        )
        session_id = insert_session(db_conn, session_insert)

        user_input = "Test with \"quotes\", 'apostrophes', and émojis 🚀"
        interaction_insert = InteractionInsert(
            file_id=file_id,
            session_id=session_id,
            agent_type="codex",
            interaction_index=1,
            timestamp="2025-01-04T10:00:00Z",
            agent_user_input=user_input,
            agent_context={},
            agent_response={"text": "Response with unicode: こんにちは"},
            raw_json=None,
        )
        interaction_id = insert_interaction(db_conn, interaction_insert)

        cursor = db_conn.cursor()
        cursor.execute(
            "SELECT agent_user_input FROM interactions WHERE id = ?", (interaction_id,)
        )
        stored_input = cursor.fetchone()[0]

        if stored_input != user_input:
            raise AssertionError(f"Special chars not preserved: {stored_input}")

    def test_insert_interaction_large_payload(
        self, db_conn: sqlite3.Connection
    ) -> None:
        """Test interaction with large JSON payload."""
        file_insert = FileInsert(path="/path/file.jsonl", agent_type="codex")
        file_id = insert_file(db_conn, file_insert)

        session_insert = SessionInsert(
            file_id=file_id,
            agent_type="codex",
            agent_session_id="session-1",
            agent_metadata={},
        )
        session_id = insert_session(db_conn, session_insert)

        large_payload = {
            "content": "x" * 50000,
            "nested": {"data": [{"item": i} for i in range(1000)]},
        }
        interaction_insert = InteractionInsert(
            file_id=file_id,
            session_id=session_id,
            agent_type="codex",
            interaction_index=1,
            timestamp="2025-01-04T10:00:00Z",
            agent_user_input="Test",
            agent_context={},
            agent_response={"text": "Response"},
            raw_json=json.dumps(large_payload),
        )
        interaction_id = insert_interaction(db_conn, interaction_insert)

        cursor = db_conn.cursor()
        cursor.execute(
            "SELECT raw_json FROM interactions WHERE id = ?", (interaction_id,)
        )
        stored_json = cursor.fetchone()[0]
        restored = json.loads(stored_json)

        if len(restored["content"]) != 50000:
            raise AssertionError("Large payload not preserved")

    def test_insert_multiple_interactions_sequential_indexing(
        self, db_conn: sqlite3.Connection
    ) -> None:
        """Test multiple interactions maintain correct indexing."""
        file_insert = FileInsert(path="/path/file.jsonl", agent_type="codex")
        file_id = insert_file(db_conn, file_insert)

        session_insert = SessionInsert(
            file_id=file_id,
            agent_type="codex",
            agent_session_id="session-1",
            agent_metadata={},
        )
        session_id = insert_session(db_conn, session_insert)

        for idx in range(1, 6):
            interaction_insert = InteractionInsert(
                file_id=file_id,
                session_id=session_id,
                agent_type="codex",
                interaction_index=idx,
                timestamp=f"2025-01-04T10:00:{idx:02d}Z",
                agent_user_input=f"Question {idx}",
                agent_context={},
                agent_response={"text": f"Answer {idx}"},
                raw_json=None,
            )
            insert_interaction(db_conn, interaction_insert)

        cursor = db_conn.cursor()
        cursor.execute(
            "SELECT interaction_index FROM interactions WHERE file_id = ? "
            "ORDER BY interaction_index",
            (file_id,),
        )
        indices = [row[0] for row in cursor.fetchall()]

        if indices != [1, 2, 3, 4, 5]:
            raise AssertionError(f"Expected sequential indices, got {indices}")

    def test_insert_interaction_minimal_fields(
        self, db_conn: sqlite3.Connection
    ) -> None:
        """Test interaction with only required fields."""
        file_insert = FileInsert(path="/path/file.jsonl", agent_type="codex")
        file_id = insert_file(db_conn, file_insert)

        session_insert = SessionInsert(
            file_id=file_id,
            agent_type="codex",
            agent_session_id="session-1",
            agent_metadata={},
        )
        session_id = insert_session(db_conn, session_insert)

        interaction_insert = InteractionInsert(
            file_id=file_id,
            session_id=session_id,
            agent_type="codex",
            interaction_index=1,
            timestamp=None,
            agent_user_input="",
            agent_context={},
            agent_response={},
            raw_json=None,
        )
        interaction_id = insert_interaction(db_conn, interaction_insert)

        if interaction_id <= 0:
            raise AssertionError("Should handle minimal interaction")


class TestCascadeDelete:
    """Test cascade delete behavior maintains referential integrity."""

    def test_delete_file_cascades_to_sessions(
        self, db_conn: sqlite3.Connection
    ) -> None:
        """Test that deleting file removes sessions."""
        file_insert = FileInsert(path="/path/file.jsonl", agent_type="codex")
        file_id = insert_file(db_conn, file_insert)

        session_insert = SessionInsert(
            file_id=file_id,
            agent_type="codex",
            agent_session_id="session-1",
            agent_metadata={},
        )
        insert_session(db_conn, session_insert)

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM files WHERE id = ?", (file_id,))
        db_conn.commit()

        cursor.execute("SELECT COUNT(*) FROM sessions WHERE file_id = ?", (file_id,))
        count = cursor.fetchone()[0]

        if count != 0:
            raise AssertionError(
                f"Expected cascade delete, but {count} sessions remain"
            )

    def test_delete_file_cascades_to_interactions(
        self, db_conn: sqlite3.Connection
    ) -> None:
        """Test that deleting file removes interactions."""
        file_insert = FileInsert(path="/path/file.jsonl", agent_type="codex")
        file_id = insert_file(db_conn, file_insert)

        session_insert = SessionInsert(
            file_id=file_id,
            agent_type="codex",
            agent_session_id="session-1",
            agent_metadata={},
        )
        session_id = insert_session(db_conn, session_insert)

        interaction_insert = InteractionInsert(
            file_id=file_id,
            session_id=session_id,
            agent_type="codex",
            interaction_index=1,
            timestamp="2025-01-04T10:00:00Z",
            agent_user_input="Test",
            agent_context={},
            agent_response={"text": "Response"},
            raw_json=None,
        )
        insert_interaction(db_conn, interaction_insert)

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM files WHERE id = ?", (file_id,))
        db_conn.commit()

        cursor.execute(
            "SELECT COUNT(*) FROM interactions WHERE file_id = ?", (file_id,)
        )
        count = cursor.fetchone()[0]

        if count != 0:
            raise AssertionError(
                f"Expected cascade delete of interactions, but {count} remain"
            )

    def test_delete_session_cascades_to_interactions(
        self, db_conn: sqlite3.Connection
    ) -> None:
        """Test that deleting session removes interactions."""
        file_insert = FileInsert(path="/path/file.jsonl", agent_type="codex")
        file_id = insert_file(db_conn, file_insert)

        session_insert = SessionInsert(
            file_id=file_id,
            agent_type="codex",
            agent_session_id="session-1",
            agent_metadata={},
        )
        session_id = insert_session(db_conn, session_insert)

        interaction_insert = InteractionInsert(
            file_id=file_id,
            session_id=session_id,
            agent_type="codex",
            interaction_index=1,
            timestamp="2025-01-04T10:00:00Z",
            agent_user_input="Test",
            agent_context={},
            agent_response={"text": "Response"},
            raw_json=None,
        )
        insert_interaction(db_conn, interaction_insert)

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        db_conn.commit()

        cursor.execute(
            "SELECT COUNT(*) FROM interactions WHERE session_id = ?", (session_id,)
        )
        count = cursor.fetchone()[0]

        if count != 0:
            raise AssertionError(
                f"Expected cascade delete of interactions, but {count} remain"
            )
