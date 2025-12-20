"""Tests for parser interface definitions (AI-assisted by Codex GPT-5)."""

# pylint: disable=import-error,too-few-public-methods

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Iterator, cast

import unittest
import pytest

from src.core.interfaces.parser import AgentLogMetadata, ILogParser
from src.core.models.base_event import BaseEvent
from src.core.models.event_data import BaseEventData, EventCategory, EventPriority


class DummyEvent(BaseEvent):
    """Minimal concrete event for testing."""

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary representation."""
        raw = getattr(self._data, "raw_data", None)
        if isinstance(raw, dict):
            return raw
        return {}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BaseEvent:
        """Construct event from dictionary representation."""
        event_data = BaseEventData(
            agent_type=data.get("agent_type", "dummy"),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            event_type=data.get("event_type", "dummy"),
            event_category=EventCategory.SYSTEM,
            priority=EventPriority.MEDIUM,
            session_id=data.get("session_id"),
            raw_data=data,
        )
        return cls(event_data)


class DummyParser(ILogParser):
    """Concrete parser implementation used for interface tests."""

    @property
    def agent_type(self) -> str:
        """Return the agent type identifier."""
        return "dummy"

    def get_metadata(self, file_path: Path) -> AgentLogMetadata:
        """Extract metadata from file path."""
        return AgentLogMetadata(
            agent_type=self.agent_type,
            session_id=file_path.stem,
            timestamp=datetime(2025, 11, 23, tzinfo=timezone.utc),
            workspace_path=str(file_path.parent),
        )

    def parse_file(self, file_path: Path) -> Iterator[BaseEvent]:
        """Parse file and yield BaseEvent instances."""
        data = BaseEventData(
            agent_type=self.agent_type,
            timestamp=datetime(2025, 11, 23, tzinfo=timezone.utc),
            event_type="parsed",
            event_category=EventCategory.SYSTEM,
            priority=EventPriority.MEDIUM,
            session_id=file_path.stem,
            raw_data={"path": str(file_path)},
        )
        yield DummyEvent(data)

    def find_log_files(self, root_path: Path) -> Generator[Path, None, None]:
        """Find and yield JSONL files in root path, sorted."""
        yield from sorted(root_path.glob("*.jsonl"))

    def validate_event(self, event_data: dict[str, Any]) -> bool:
        """Check if event data is valid based on 'valid' key."""
        return bool(event_data.get("valid"))

    def get_agent_type(self) -> str:
        """Return the agent type identifier."""
        return self.agent_type


TC = unittest.TestCase()


def test_agent_log_metadata_frozen() -> None:
    """AgentLogMetadata should be immutable and carry optional fields."""
    meta = AgentLogMetadata(
        agent_type="dummy",
        session_id="abc",
        timestamp=datetime(2025, 11, 23, tzinfo=timezone.utc),
    )
    with pytest.raises(FrozenInstanceError):
        meta.agent_type = "changed"  # type: ignore[misc]


def test_ilogparser_requires_abstracts() -> None:
    """Instantiating ILogParser without implementations should fail."""

    class PartialParser(ILogParser):  # pylint: disable=abstract-method
        """Partial parser stub lacking full implementation."""

        @property
        def agent_type(self) -> str:  # pragma: no cover - abstract enforcement
            """Return agent type (stub)."""
            return "partial"

    with pytest.raises(TypeError):
        PartialParser()  # type: ignore[abstract]  # pylint: disable=abstract-class-instantiated


def test_dummy_parser_metadata_and_agent_type(tmp_path: Path) -> None:
    """Verify metadata extraction and agent type helpers."""
    parser = DummyParser()
    file_path = tmp_path / "session-1.jsonl"
    file_path.write_text("{}", encoding="utf-8")
    meta = parser.get_metadata(file_path)
    TC.assertEqual(meta.agent_type, "dummy")
    TC.assertEqual(meta.session_id, "session-1")
    TC.assertEqual(parser.agent_type, parser.get_agent_type())


def test_dummy_parser_parse_and_validation(tmp_path: Path) -> None:
    """Ensure parse_file yields BaseEvent and validate_event respects flag."""
    parser = DummyParser()
    file_path = tmp_path / "session-2.jsonl"
    file_path.write_text("{}", encoding="utf-8")
    events = list(parser.parse_file(file_path))
    TC.assertEqual(len(events), 1)
    TC.assertIsInstance(events[0], BaseEvent)
    TC.assertTrue(parser.validate_event({"valid": True}))
    TC.assertFalse(parser.validate_event({}))


def test_dummy_parser_find_log_files_sorted(tmp_path: Path) -> None:
    """find_log_files should yield JSONL files in sorted order."""
    file_b = tmp_path / "b.jsonl"
    file_a = tmp_path / "a.jsonl"
    file_a.write_text("a", encoding="utf-8")
    file_b.write_text("b", encoding="utf-8")
    parser = DummyParser()
    found = list(parser.find_log_files(tmp_path))
    TC.assertEqual(found, [file_a, file_b])


def test_dummy_parser_find_log_files_empty(tmp_path: Path) -> None:
    """find_log_files should return empty when no files exist."""
    parser = DummyParser()
    found = list(parser.find_log_files(tmp_path))
    TC.assertEqual(found, [])


def test_dummy_event_to_dict_handles_non_dict_raw() -> None:
    """DummyEvent.to_dict should fall back to empty dict when raw_data is not a dict."""
    data = BaseEventData(
        agent_type="dummy",
        timestamp=datetime(2025, 11, 23, tzinfo=timezone.utc),
        event_type="parsed",
        event_category=EventCategory.SYSTEM,
        priority=EventPriority.MEDIUM,
        session_id="session-x",
        raw_data={"value": "not-a-dict"},
    )
    event = DummyEvent(data)
    TC.assertEqual(event.to_dict(), {"value": "not-a-dict"})


def test_dummy_event_to_dict_returns_empty_when_raw_missing() -> None:
    """DummyEvent.to_dict should return empty dict when raw_data is not a dict."""

    data = BaseEventData(
        agent_type="dummy",
        timestamp=datetime(2025, 11, 23, tzinfo=timezone.utc),
        event_type="parsed",
        event_category=EventCategory.SYSTEM,
        priority=EventPriority.MEDIUM,
        session_id="session-y",
        raw_data=cast(Any, "not-dict"),
    )
    event = DummyEvent(data)
    TC.assertEqual(event.to_dict(), {})


def test_dummy_event_from_dict_builds_event() -> None:
    """DummyEvent.from_dict should hydrate BaseEventData from a dict."""

    payload = {
        "agent_type": "dummy",
        "timestamp": "2025-11-23T00:00:00+00:00",
        "event_type": "custom",
        "session_id": "sid-123",
    }
    event = DummyEvent.from_dict(payload)
    TC.assertIsInstance(event, DummyEvent)
    data = event.to_dict()
    TC.assertEqual(data.get("session_id"), "sid-123")
    TC.assertEqual(data.get("event_type", "custom"), "custom")


def test_dummy_parser_validate_event_falsey() -> None:
    """validate_event should return False when 'valid' flag missing/false."""

    parser = DummyParser()
    TC.assertFalse(parser.validate_event({}))
    TC.assertFalse(parser.validate_event({"valid": False}))
