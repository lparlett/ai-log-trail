"""Test fixtures and configuration."""

# pylint: disable=import-error

from __future__ import annotations

# pylint: disable=wrong-import-position,redefined-outer-name
# Imports occur after sys.path manipulation to ensure local modules resolve;
# fixtures intentionally reuse names across scopes for pytest convenience.

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

# Ensure project root is on sys.path before local imports
ROOT_DIR = Path(__file__).parent.parent.resolve()
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pytest

from src.core.models.event_data import BaseEventData, EventCategory, EventPriority
from src.agents.codex.models import CodexMessage
from src.services.database import ensure_schema


@pytest.fixture
def sample_timestamp() -> datetime:
    """Get a fixed timestamp for testing."""
    return datetime(2025, 10, 31, 10, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def sample_event_data(
    sample_timestamp: datetime,
) -> BaseEventData:  # pylint: disable=redefined-outer-name
    """Create a sample BaseEventData for testing."""
    return BaseEventData(
        agent_type="codex",
        timestamp=sample_timestamp,
        event_type="test.event",
        event_category=EventCategory.SYSTEM,
        priority=EventPriority.MEDIUM,
        session_id="test-session-001",
        raw_data={"test": "data"},
    )


@pytest.fixture
def sample_codex_message(
    sample_timestamp: datetime,
) -> CodexMessage:  # pylint: disable=redefined-outer-name
    """Create a sample CodexMessage for testing."""
    return CodexMessage.create(
        CodexMessage.build_data(
            content="Test message",
            timestamp=sample_timestamp,
            is_user=True,
            session_id="test-session-001",
            raw_data={"test": "data"},
        )
    )


@pytest.fixture
def sample_session_file(tmp_path: Path) -> Path:
    """Create a temporary copy of the sample session file."""
    source = Path("tests/fixtures/codex_sample_session.jsonl")
    dest = tmp_path / "test_session.jsonl"
    dest.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return dest


@pytest.fixture
def db_connection(tmp_path: Path) -> Generator[sqlite3.Connection, None, None]:
    """Create a temporary SQLite database with schema."""
    db_path = tmp_path / "test.sqlite"
    conn = sqlite3.connect(db_path)
    ensure_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def sample_raw_event() -> dict[str, Any]:
    """Create a sample raw event dictionary."""
    return {
        "type": "event_msg",
        "timestamp": "2025-10-31T10:00:00Z",
        "payload": {"type": "user_message", "message": "Test message"},
    }


# === Database migration test fixtures ===


# Old schema definition for testing migration scenarios
# The current schema uses agent-agnostic tables (interactions, agent_events, etc.)
# instead of the legacy Codex-specific structure (prompts, messages, turn_context_messages).
# Old fixtures (old_schema_sqlite_db, migrated_sqlite_db) have been removed as they are
# no longer relevant to the current codebase.


@pytest.fixture
def fresh_sqlite_db(tmp_path: Path) -> Generator[sqlite3.Connection, None, None]:
    """Create a fresh SQLite database with current schema."""
    db_path = tmp_path / "fresh.sqlite"
    conn = sqlite3.connect(db_path)
    ensure_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def ingest_event_factory() -> dict[str, Any]:
    """Factory for creating synthetic ingest events with various payload types."""

    def make_event(
        event_type: str = "event_msg",
        payload_type: str = "user_message",
        timestamp: str | None = None,
        **payload_kwargs: Any,
    ) -> dict[str, Any]:
        """Create a synthetic event for testing.

        Args:
            event_type: The event type (e.g., 'event_msg')
            payload_type: The payload type (e.g., 'user_message', 'code_action')
            timestamp: ISO 8601 timestamp (defaults to fixed test timestamp)
            **payload_kwargs: Additional fields to include in the payload

        Returns:
            A dictionary representing a complete event
        """
        if timestamp is None:
            timestamp = "2025-10-31T10:00:00Z"

        payload = {"type": payload_type, **payload_kwargs}

        return {
            "type": event_type,
            "timestamp": timestamp,
            "payload": payload,
        }

    return {"make_event": make_event}
