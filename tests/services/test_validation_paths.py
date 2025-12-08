"""Tests for validation error paths.

Purpose: Cover edge cases and error scenarios in validation.py
Author: Codex with Claude Haiku
Date: 2025-12-06
AI-assisted: True
"""

import unittest

import pytest

from src.services.validation import (
    EventValidationError,
    validate_event,
)

TC = unittest.TestCase()


class TestValidationErrorPaths:
    """Test validation error handling for uncovered paths."""

    def test_validate_event_non_dict_top_level(self) -> None:
        """validate_event should reject non-dict events."""
        with pytest.raises(EventValidationError, match="must be a JSON object"):
            validate_event("not a dict")

    def test_validate_event_missing_type_field(self) -> None:
        """validate_event should reject events without 'type' field."""
        with pytest.raises(EventValidationError, match="must be a non-empty string"):
            validate_event({})

    def test_validate_event_empty_type_field(self) -> None:
        """validate_event should reject events with empty 'type' field."""
        with pytest.raises(EventValidationError, match="must be a non-empty string"):
            validate_event({"type": ""})

    def test_validate_event_non_string_type_field(self) -> None:
        """validate_event should reject events with non-string 'type' field."""
        with pytest.raises(EventValidationError, match="must be a non-empty string"):
            validate_event({"type": 123})

    def test_validate_event_non_string_timestamp(self) -> None:
        """validate_event should reject non-string timestamps."""
        with pytest.raises(EventValidationError, match="must be a string or null"):
            validate_event({"type": "event_msg", "timestamp": 12345})

    def test_validate_event_non_dict_metadata(self) -> None:
        """validate_event should normalize non-dict metadata to empty dict."""
        event = {"type": "event_msg", "metadata": "not a dict"}
        result = validate_event(event)

        TC.assertIsNotNone(result)
        TC.assertEqual(result["metadata"], {})

    def test_validate_event_non_dict_payload(self) -> None:
        """validate_event should reject non-dict payloads."""
        with pytest.raises(EventValidationError, match="must be a JSON object"):
            validate_event({"type": "event_msg", "payload": "not a dict"})

    def test_validate_event_valid_minimal(self) -> None:
        """validate_event should accept minimal valid event."""
        result = validate_event({"type": "event_msg"})
        TC.assertEqual(result["type"], "event_msg")
        TC.assertEqual(result["payload"], {})

    def test_validate_event_valid_complete(self) -> None:
        """validate_event should accept complete valid event."""
        event = {
            "type": "event_msg",
            "timestamp": "2025-12-06T10:00:00Z",
            "payload": {"key": "value"},
            "metadata": {"source": "test"},
        }
        result = validate_event(event)
        TC.assertEqual(result["type"], "event_msg")
        TC.assertEqual(result["timestamp"], "2025-12-06T10:00:00Z")
        TC.assertEqual(result["payload"], {"key": "value"})
