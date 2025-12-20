"""Tests for core model functionality."""

# pylint: disable=duplicate-code,import-error,attribute-defined-outside-init
# Tests intentionally mirror event serialization patterns to validate parity.

from __future__ import annotations

import unittest
from datetime import datetime
from typing import Any

import pytest

from src.core.models.event_data import BaseEventData, EventCategory, EventPriority
from src.core.models.base_event import BaseEvent


class TestEvent(BaseEvent):
    """A concrete test implementation of BaseEvent."""

    __test__ = False  # Prevent pytest from treating this helper as a test class

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary."""
        return {
            "agent_type": self.agent_type,
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type,
            "event_category": self.event_category.value,
            "priority": self.priority.value,
            "session_id": self.session_id,
            "raw_data": self.raw_data,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestEvent:
        """Create event from dictionary."""
        return cls(
            BaseEventData(
                agent_type=data["agent_type"],
                timestamp=datetime.fromisoformat(data["timestamp"]),
                event_type=data["event_type"],
                event_category=EventCategory(data["event_category"]),
                priority=EventPriority(data["priority"]),
                session_id=data["session_id"],
                raw_data=data.get("raw_data"),
            )
        )


def test_base_event_data_initialization(sample_timestamp: datetime) -> None:
    """Test BaseEventData initialization with valid data."""
    test_case = unittest.TestCase()
    data = BaseEventData(
        agent_type="test",
        timestamp=sample_timestamp,
        event_type="test.event",
        event_category=EventCategory.SYSTEM,
        priority=EventPriority.MEDIUM,
        session_id="test-123",
        raw_data={"test": "data"},
    )

    test_case.assertEqual(data.agent_type, "test")
    test_case.assertEqual(data.timestamp, sample_timestamp)
    test_case.assertEqual(data.event_type, "test.event")
    test_case.assertEqual(data.event_category, EventCategory.SYSTEM)
    test_case.assertEqual(data.priority, EventPriority.MEDIUM)
    test_case.assertEqual(data.session_id, "test-123")
    test_case.assertEqual(data.raw_data, {"test": "data"})


def test_base_event_data_validation() -> None:
    """Test BaseEventData validation rules."""
    with pytest.raises(ValueError, match="agent_type.*empty"):
        BaseEventData(
            agent_type="",  # Empty string should fail
            timestamp=datetime.now(),
            event_type="test",
            event_category=EventCategory.SYSTEM,
            session_id="test",
        )

    with pytest.raises(ValueError, match="event_type.*empty"):
        BaseEventData(
            agent_type="test",
            timestamp=datetime.now(),
            event_type="",  # Empty string should fail
            event_category=EventCategory.SYSTEM,
            session_id="test",
        )


def test_base_event_initialization(sample_event_data: BaseEventData) -> None:
    """Test BaseEvent initialization and property access."""
    test_case = unittest.TestCase()
    event = TestEvent(sample_event_data)

    test_case.assertEqual(event.agent_type, sample_event_data.agent_type)
    test_case.assertEqual(event.timestamp, sample_event_data.timestamp)
    test_case.assertEqual(event.event_type, sample_event_data.event_type)
    test_case.assertEqual(event.event_category, sample_event_data.event_category)
    test_case.assertEqual(event.priority, sample_event_data.priority)
    test_case.assertEqual(event.session_id, sample_event_data.session_id)
    test_case.assertEqual(event.raw_data, sample_event_data.raw_data)


def test_base_event_immutability(sample_event_data: BaseEventData) -> None:
    """Test that BaseEvent properties are immutable."""
    event = TestEvent(sample_event_data)

    with pytest.raises(AttributeError):
        event.agent_type = "new_type"  # type: ignore

    with pytest.raises(AttributeError):
        event.timestamp = datetime.now()  # type: ignore

    with pytest.raises(AttributeError):
        event.event_type = "new.type"  # type: ignore


def test_base_event_to_dict(sample_event_data: BaseEventData) -> None:
    """Test conversion of BaseEvent to dictionary."""
    test_case = unittest.TestCase()
    event = TestEvent(sample_event_data)
    data = event.to_dict()

    test_case.assertIsInstance(data, dict)
    test_case.assertEqual(data["agent_type"], event.agent_type)
    test_case.assertEqual(data["timestamp"], event.timestamp.isoformat())
    test_case.assertEqual(data["event_type"], event.event_type)
    test_case.assertEqual(data["event_category"], event.event_category.value)
    test_case.assertEqual(data["priority"], event.priority.value)
    test_case.assertEqual(data["session_id"], event.session_id)
    test_case.assertEqual(data["raw_data"], event.raw_data)
