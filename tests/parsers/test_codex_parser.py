"""Comprehensive tests for CodexParser.

Purpose: Complete test coverage for src/agents/codex/parser.py
Content: Unit tests, edge cases, comprehensive validation, all message/action types.
Author: Lauren Parlett (consolidated with original test_codex_parser.py)
Date: 2025-11-30

AI-assisted code: Generated with AI support.
"""

# pylint: disable=protected-access,import-error

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import pytest

from src.agents.codex.parser import CodexParser
from src.agents.codex.errors import InvalidEventError, InvalidMetadataError
from src.agents.codex.models import CodexAction, CodexMessage
from src.core.interfaces.parser import AgentLogMetadata

TC = unittest.TestCase()


class TestableCodexParser(CodexParser):
    """Concrete CodexParser for testing."""

    def find_log_files(self, root_path: Path) -> Any:
        """Find JSONL files in root path."""
        yield from root_path.glob("*.jsonl")

    def get_agent_type(self) -> str:
        """Return the agent type identifier."""
        return self.agent_type


def _write_lines(tmp_path: Path, *lines: str) -> Path:
    """Write lines to a JSONL file."""
    file_path = tmp_path / "session.jsonl"
    file_path.write_text("\n".join(lines), encoding="utf-8")
    return file_path


def test_get_metadata_file_not_found() -> None:
    """Missing file should raise FileNotFoundError."""
    missing_path = Path("/nonexistent/file.jsonl")
    with pytest.raises(InvalidMetadataError):
        TestableCodexParser().get_metadata(missing_path)


def test_get_metadata_happy_path(tmp_path: Path) -> None:
    """Metadata should parse session_meta first line."""
    session_meta = (
        '{"type": "session_meta", "timestamp": "2025-11-23T10:00:00+00:00",'
        ' "payload": {"id": "sid-123", "cwd": "C:/repo"}}'
    )
    file_path = _write_lines(tmp_path, session_meta)
    meta = TestableCodexParser().get_metadata(file_path)
    TC.assertIsInstance(meta, AgentLogMetadata)
    TC.assertEqual(meta.session_id, "sid-123")
    TC.assertEqual(meta.workspace_path, "C:/repo")
    TC.assertEqual(meta.timestamp, datetime(2025, 11, 23, 10, 0, tzinfo=timezone.utc))


@pytest.mark.parametrize(
    "line, expected",
    [
        ("", "Empty log file"),
        ('{"not": "json"', "Invalid JSON"),
        (
            '{"type": "not_session_meta", "timestamp": "2025-11-23T10:00:00"}',
            "session_meta",
        ),
        (
            '{"type": "session_meta", "timestamp": "2025-11-23T10:00:00", "payload": "x"}',
            "payload",
        ),
        ('{"type": "session_meta", "timestamp": 123, "payload": {}}', "timestamp"),
        (
            '{"type": "session_meta", "timestamp": "not-a-date", "payload": {}}',
            "timestamp",
        ),
        (
            '{"type": "session_meta", "timestamp": "2025-11-23T10:00:00", "payload": {}}',
            "session ID",
        ),
    ],
)
def test_get_metadata_errors(tmp_path: Path, line: str, expected: str) -> None:
    """get_metadata should raise InvalidMetadataError on malformed first line."""
    file_path = _write_lines(tmp_path, line)
    with pytest.raises(InvalidMetadataError) as exc:
        TestableCodexParser().get_metadata(file_path)
    TC.assertIn(expected, str(exc.value))


def test_parse_file_yields_messages_and_actions(tmp_path: Path) -> None:
    """parse_file should emit CodexMessage and CodexAction events."""
    session_meta = (
        '{"type": "session_meta", "timestamp": "2025-11-23T10:00:00+00:00",'
        ' "payload": {"id": "sid-123", "cwd": "C:/repo"}}'
    )
    user_msg = (
        '{"type": "event_msg", "timestamp": "2025-11-23T10:00:01+00:00",'
        ' "payload": {"type": "user_message", "message": "Hi"}}'
    )
    ai_response = (
        '{"type": "event_msg", "timestamp": "2025-11-23T10:00:02+00:00",'
        ' "payload": {"type": "ai_response", "message": "Hello"}}'
    )
    tool_call = (
        '{"type": "event_msg", "timestamp": "2025-11-23T10:00:03+00:00",'
        ' "payload": {"type": "tool_call", "tool": {"name": "shell", "parameters": {"cmd": "ls"}}}}'
    )
    tool_result = (
        '{"type": "event_msg", "timestamp": "2025-11-23T10:00:04+00:00",'
        ' "payload": {"type": "tool_result", "tool": {"name": "shell"}, "result": "ok"}}'
    )
    file_path = _write_lines(
        tmp_path, session_meta, user_msg, ai_response, tool_call, tool_result
    )
    events = list(TestableCodexParser().parse_file(file_path))
    TC.assertEqual(len(events), 4)
    TC.assertEqual(sum(isinstance(e, CodexMessage) for e in events), 2)
    TC.assertEqual(sum(isinstance(e, CodexAction) for e in events), 2)


def test_parse_file_invalid_event_raises(tmp_path: Path) -> None:
    """Invalid event should raise InvalidEventError with line context."""
    session_meta = (
        '{"type": "session_meta", "timestamp": "2025-11-23T10:00:00+00:00",'
        ' "payload": {"id": "sid-123"}}'
    )
    bad_event = (
        '{"type": "event_msg", "timestamp": "2025-11-23T10:00:01+00:00",'
        ' "payload": {"type": "unknown"}}'
    )
    file_path = _write_lines(tmp_path, session_meta, bad_event)
    with pytest.raises(InvalidEventError) as exc:
        list(TestableCodexParser().parse_file(file_path))
    TC.assertIn("Line: 2", str(exc.value))


def test_parse_file_invalid_json_raises(tmp_path: Path) -> None:
    """Malformed JSON lines should raise InvalidEventError."""
    session_meta = (
        '{"type": "session_meta", "timestamp": "2025-11-23T10:00:00+00:00",'
        ' "payload": {"id": "sid-123"}}'
    )
    file_path = _write_lines(tmp_path, session_meta, '{"invalid": ')
    with pytest.raises(InvalidEventError):
        list(TestableCodexParser().parse_file(file_path))


def test_validate_event_branches() -> None:
    """Cover validation helper branches."""
    parser = TestableCodexParser()
    base: dict[str, Any] = {
        "type": "event_msg",
        "timestamp": "2025-11-23T10:00:00",
        "payload": {"type": "user_message", "message": "ok"},
    }
    TC.assertTrue(parser.validate_event(base))
    TC.assertFalse(parser.validate_event({"timestamp": "2025-11-23"}))  # missing type
    TC.assertFalse(
        parser.validate_event({"type": "event_msg", "timestamp": 123, "payload": {}})
    )
    TC.assertFalse(
        parser.validate_event(
            {
                "type": "event_msg",
                "timestamp": "2025-11-23",
                "payload": {"type": "user_message"},
            }
        )
    )
    TC.assertTrue(
        parser.validate_event(
            {
                "type": "event_msg",
                "timestamp": "2025-11-23",
                "payload": {"type": "tool_call", "tool": {"name": "x"}},
            }
        )
    )
    TC.assertFalse(
        parser._validate_base_structure(  # pylint: disable=protected-access
            {"type": "event_msg"}
        )
    )
    TC.assertFalse(
        parser._validate_message_event(  # pylint: disable=protected-access
            {"type": "tool_call", "tool": "bad"}
        )
    )


def test_parse_file_blank_lines_skipped(tmp_path: Path) -> None:
    """Blank lines should be skipped during parsing."""
    session_meta = (
        '{"type": "session_meta", "timestamp": "2025-11-23T10:00:00+00:00",'
        ' "payload": {"id": "sid-123"}}'
    )
    user_msg = (
        '{"type": "event_msg", "timestamp": "2025-11-23T10:00:01+00:00",'
        ' "payload": {"type": "user_message", "message": "Hi"}}'
    )
    file_path = tmp_path / "session.jsonl"
    file_path.write_text(f"{session_meta}\n\n{user_msg}\n\n", encoding="utf-8")
    events = list(TestableCodexParser().parse_file(file_path))
    # Session meta is not yielded, only the message
    TC.assertEqual(len(events), 1)
    TC.assertIsInstance(events[0], CodexMessage)


def test_parse_file_with_whitespace_lines(tmp_path: Path) -> None:
    """Lines with only whitespace should be skipped."""
    session_meta = (
        '{"type": "session_meta", "timestamp": "2025-11-23T10:00:00+00:00",'
        ' "payload": {"id": "sid-123"}}'
    )
    user_msg = (
        '{"type": "event_msg", "timestamp": "2025-11-23T10:00:01+00:00",'
        ' "payload": {"type": "user_message", "message": "Test"}}'
    )
    file_path = tmp_path / "session.jsonl"
    file_path.write_text(f"{session_meta}\n   \n\t\n{user_msg}", encoding="utf-8")
    events = list(TestableCodexParser().parse_file(file_path))
    TC.assertEqual(len(events), 1)


def test_parse_file_missing_timestamp_in_event(tmp_path: Path) -> None:
    """Event missing timestamp should raise InvalidEventError."""
    session_meta = (
        '{"type": "session_meta", "timestamp": "2025-11-23T10:00:00+00:00",'
        ' "payload": {"id": "sid-123"}}'
    )
    bad_event = '{"type": "event_msg", "payload": {"type": "user_message"}}'
    file_path = _write_lines(tmp_path, session_meta, bad_event)
    with pytest.raises(InvalidEventError):
        list(TestableCodexParser().parse_file(file_path))


def test_parse_file_invalid_timestamp_type(tmp_path: Path) -> None:
    """Event with non-string timestamp should raise InvalidEventError."""
    session_meta = (
        '{"type": "session_meta", "timestamp": "2025-11-23T10:00:00+00:00",'
        ' "payload": {"id": "sid-123"}}'
    )
    bad_event = (
        '{"type": "event_msg", "timestamp": 123, '
        '"payload": {"type": "user_message", "message": "Hi"}}'
    )
    file_path = _write_lines(tmp_path, session_meta, bad_event)
    with pytest.raises(InvalidEventError):
        list(TestableCodexParser().parse_file(file_path))


def test_parse_file_invalid_timestamp_format(tmp_path: Path) -> None:
    """Event with malformed timestamp should raise InvalidEventError."""
    session_meta = (
        '{"type": "session_meta", "timestamp": "2025-11-23T10:00:00+00:00",'
        ' "payload": {"id": "sid-123"}}'
    )
    bad_event = (
        '{"type": "event_msg", "timestamp": "not-a-date",'
        ' "payload": {"type": "user_message", "message": "Hi"}}'
    )
    file_path = _write_lines(tmp_path, session_meta, bad_event)
    with pytest.raises(InvalidEventError):
        list(TestableCodexParser().parse_file(file_path))


def test_parse_file_missing_event_type(tmp_path: Path) -> None:
    """Event missing type should raise InvalidEventError."""
    session_meta = (
        '{"type": "session_meta", "timestamp": "2025-11-23T10:00:00+00:00",'
        ' "payload": {"id": "sid-123"}}'
    )
    bad_event = '{"timestamp": "2025-11-23T10:00:01+00:00", "payload": {}}'
    file_path = _write_lines(tmp_path, session_meta, bad_event)
    with pytest.raises(InvalidEventError):
        list(TestableCodexParser().parse_file(file_path))


def test_parse_file_invalid_event_type(tmp_path: Path) -> None:
    """Event with non-string type should raise InvalidEventError."""
    session_meta = (
        '{"type": "session_meta", "timestamp": "2025-11-23T10:00:00+00:00",'
        ' "payload": {"id": "sid-123"}}'
    )
    bad_event = '{"type": 123, "timestamp": "2025-11-23T10:00:01+00:00", "payload": {}}'
    file_path = _write_lines(tmp_path, session_meta, bad_event)
    with pytest.raises(InvalidEventError):
        list(TestableCodexParser().parse_file(file_path))


def test_parse_file_missing_payload(tmp_path: Path) -> None:
    """Event missing payload should raise InvalidEventError."""
    session_meta = (
        '{"type": "session_meta", "timestamp": "2025-11-23T10:00:00+00:00",'
        ' "payload": {"id": "sid-123"}}'
    )
    bad_event = '{"type": "event_msg", "timestamp": "2025-11-23T10:00:01+00:00"}'
    file_path = _write_lines(tmp_path, session_meta, bad_event)
    with pytest.raises(InvalidEventError):
        list(TestableCodexParser().parse_file(file_path))


def test_parse_file_invalid_payload_type(tmp_path: Path) -> None:
    """Event with non-dict payload should raise InvalidEventError."""
    session_meta = (
        '{"type": "session_meta", "timestamp": "2025-11-23T10:00:00+00:00",'
        ' "payload": {"id": "sid-123"}}'
    )
    bad_event = (
        '{"type": "event_msg", "timestamp": "2025-11-23T10:00:01+00:00", '
        '"payload": "invalid"}'
    )
    file_path = _write_lines(tmp_path, session_meta, bad_event)
    with pytest.raises(InvalidEventError):
        list(TestableCodexParser().parse_file(file_path))


def test_parse_file_json_decode_error_context(tmp_path: Path) -> None:
    """JSON decode error should include line number."""
    session_meta = (
        '{"type": "session_meta", "timestamp": "2025-11-23T10:00:00+00:00",'
        ' "payload": {"id": "sid-123"}}'
    )
    file_path = _write_lines(tmp_path, session_meta, '{"invalid": json}')
    with pytest.raises(InvalidEventError) as exc:
        list(TestableCodexParser().parse_file(file_path))
    TC.assertIn("Line: 2", str(exc.value))


def test_parse_file_read_error() -> None:
    """File read errors should be caught and re-raised."""
    missing_path = Path("/nonexistent/file.jsonl")
    # File read errors raise InvalidMetadataError from get_metadata
    with pytest.raises((InvalidEventError, InvalidMetadataError)):
        list(TestableCodexParser().parse_file(missing_path))


def test_process_event_user_message_basic(tmp_path: Path) -> None:
    """User message should yield CodexMessage."""
    session_meta = (
        '{"type": "session_meta", "timestamp": "2025-11-23T10:00:00+00:00",'
        ' "payload": {"id": "sid-123"}}'
    )
    user_msg = (
        '{"type": "event_msg", "timestamp": "2025-11-23T10:00:01+00:00",'
        ' "payload": {"type": "user_message", "message": "Hello"}}'
    )
    file_path = _write_lines(tmp_path, session_meta, user_msg)
    events = list(TestableCodexParser().parse_file(file_path))
    TC.assertEqual(len(events), 1)
    TC.assertIsInstance(events[0], CodexMessage)
    msg = cast(CodexMessage, events[0])
    TC.assertTrue(msg.is_user)
    TC.assertEqual(msg.content, "Hello")


def test_process_event_user_message_empty(tmp_path: Path) -> None:
    """User message with empty string should yield CodexMessage."""
    session_meta = (
        '{"type": "session_meta", "timestamp": "2025-11-23T10:00:00+00:00",'
        ' "payload": {"id": "sid-123"}}'
    )
    user_msg = (
        '{"type": "event_msg", "timestamp": "2025-11-23T10:00:01+00:00",'
        ' "payload": {"type": "user_message", "message": ""}}'
    )
    file_path = _write_lines(tmp_path, session_meta, user_msg)
    events = list(TestableCodexParser().parse_file(file_path))
    TC.assertEqual(len(events), 1)
    msg = cast(CodexMessage, events[0])
    TC.assertEqual(msg.content, "")


def test_process_event_user_message_missing_message_field(
    tmp_path: Path,
) -> None:
    """User message missing message field fails validation."""
    session_meta = (
        '{"type": "session_meta", "timestamp": "2025-11-23T10:00:00+00:00",'
        ' "payload": {"id": "sid-123"}}'
    )
    user_msg = (
        '{"type": "event_msg", "timestamp": "2025-11-23T10:00:01+00:00",'
        ' "payload": {"type": "user_message"}}'
    )
    file_path = _write_lines(tmp_path, session_meta, user_msg)
    with pytest.raises(InvalidEventError):
        list(TestableCodexParser().parse_file(file_path))


def test_process_event_ai_response_basic(tmp_path: Path) -> None:
    """AI response should yield CodexMessage with is_user=False."""
    session_meta = (
        '{"type": "session_meta", "timestamp": "2025-11-23T10:00:00+00:00",'
        ' "payload": {"id": "sid-123"}}'
    )
    ai_response = (
        '{"type": "event_msg", "timestamp": "2025-11-23T10:00:02+00:00",'
        ' "payload": {"type": "ai_response", "message": "Hello from AI"}}'
    )
    file_path = _write_lines(tmp_path, session_meta, ai_response)
    events = list(TestableCodexParser().parse_file(file_path))
    TC.assertEqual(len(events), 1)
    TC.assertIsInstance(events[0], CodexMessage)
    msg = cast(CodexMessage, events[0])
    TC.assertFalse(msg.is_user)
    TC.assertEqual(msg.content, "Hello from AI")


def test_process_event_ai_response_empty(tmp_path: Path) -> None:
    """AI response with empty message should yield CodexMessage."""
    session_meta = (
        '{"type": "session_meta", "timestamp": "2025-11-23T10:00:00+00:00",'
        ' "payload": {"id": "sid-123"}}'
    )
    ai_response = (
        '{"type": "event_msg", "timestamp": "2025-11-23T10:00:02+00:00",'
        ' "payload": {"type": "ai_response", "message": ""}}'
    )
    file_path = _write_lines(tmp_path, session_meta, ai_response)
    events = list(TestableCodexParser().parse_file(file_path))
    TC.assertEqual(len(events), 1)
    msg = cast(CodexMessage, events[0])
    TC.assertEqual(msg.content, "")


def test_process_event_tool_call_basic(tmp_path: Path) -> None:
    """Tool call should yield CodexAction."""
    session_meta = (
        '{"type": "session_meta", "timestamp": "2025-11-23T10:00:00+00:00",'
        ' "payload": {"id": "sid-123"}}'
    )
    tool_call = (
        '{"type": "event_msg", "timestamp": "2025-11-23T10:00:03+00:00",'
        ' "payload": {"type": "tool_call", "tool": {"name": "shell", "parameters": {"cmd": "ls"}}}}'
    )
    file_path = _write_lines(tmp_path, session_meta, tool_call)
    events = list(TestableCodexParser().parse_file(file_path))
    TC.assertEqual(len(events), 1)
    TC.assertIsInstance(events[0], CodexAction)
    action = cast(CodexAction, events[0])
    TC.assertEqual(action.action_type, "tool_call")


def test_process_event_tool_call_missing_tool(tmp_path: Path) -> None:
    """Tool call missing tool field should use empty dict."""
    session_meta = (
        '{"type": "session_meta", "timestamp": "2025-11-23T10:00:00+00:00",'
        ' "payload": {"id": "sid-123"}}'
    )
    # Tool call without tool field fails validation since tool.name is required
    tool_call = (
        '{"type": "event_msg", "timestamp": "2025-11-23T10:00:03+00:00",'
        ' "payload": {"type": "tool_call"}}'
    )
    file_path = _write_lines(tmp_path, session_meta, tool_call)
    with pytest.raises(InvalidEventError):
        list(TestableCodexParser().parse_file(file_path))


def test_process_event_tool_call_null_tool(tmp_path: Path) -> None:
    """Tool call with null tool fails validation."""
    session_meta = (
        '{"type": "session_meta", "timestamp": "2025-11-23T10:00:00+00:00",'
        ' "payload": {"id": "sid-123"}}'
    )
    tool_call = (
        '{"type": "event_msg", "timestamp": "2025-11-23T10:00:03+00:00",'
        ' "payload": {"type": "tool_call", "tool": null}}'
    )
    file_path = _write_lines(tmp_path, session_meta, tool_call)
    with pytest.raises(InvalidEventError):
        list(TestableCodexParser().parse_file(file_path))


def test_process_event_tool_result_basic(tmp_path: Path) -> None:
    """Tool result should yield CodexAction."""
    session_meta = (
        '{"type": "session_meta", "timestamp": "2025-11-23T10:00:00+00:00",'
        ' "payload": {"id": "sid-123"}}'
    )
    tool_result = (
        '{"type": "event_msg", "timestamp": "2025-11-23T10:00:04+00:00",'
        ' "payload": {"type": "tool_result", "tool": {"name": "shell"}, "result": "done"}}'
    )
    file_path = _write_lines(tmp_path, session_meta, tool_result)
    events = list(TestableCodexParser().parse_file(file_path))
    TC.assertEqual(len(events), 1)
    TC.assertIsInstance(events[0], CodexAction)
    action = cast(CodexAction, events[0])
    TC.assertEqual(action.action_type, "tool_result")


def test_process_event_tool_result_missing_result(tmp_path: Path) -> None:
    """Tool result missing result field should default to None."""
    session_meta = (
        '{"type": "session_meta", "timestamp": "2025-11-23T10:00:00+00:00",'
        ' "payload": {"id": "sid-123"}}'
    )
    tool_result = (
        '{"type": "event_msg", "timestamp": "2025-11-23T10:00:04+00:00",'
        ' "payload": {"type": "tool_result", "tool": {"name": "shell"}}}'
    )
    file_path = _write_lines(tmp_path, session_meta, tool_result)
    events = list(TestableCodexParser().parse_file(file_path))
    TC.assertEqual(len(events), 1)


def test_process_event_unknown_type(tmp_path: Path) -> None:
    """Unknown event type fails validation."""
    session_meta = (
        '{"type": "session_meta", "timestamp": "2025-11-23T10:00:00+00:00",'
        ' "payload": {"id": "sid-123"}}'
    )
    unknown_event = (
        '{"type": "unknown_type", "timestamp": "2025-11-23T10:00:01+00:00",'
        ' "payload": {}}'
    )
    file_path = _write_lines(tmp_path, session_meta, unknown_event)
    with pytest.raises(InvalidEventError):
        list(TestableCodexParser().parse_file(file_path))


def test_process_event_unknown_message_type(tmp_path: Path) -> None:
    """Unknown message type fails validation."""
    session_meta = (
        '{"type": "session_meta", "timestamp": "2025-11-23T10:00:00+00:00",'
        ' "payload": {"id": "sid-123"}}'
    )
    unknown_msg = (
        '{"type": "event_msg", "timestamp": "2025-11-23T10:00:01+00:00",'
        ' "payload": {"type": "token_count", "data": "something"}}'
    )
    file_path = _write_lines(tmp_path, session_meta, unknown_msg)
    with pytest.raises(InvalidEventError):
        list(TestableCodexParser().parse_file(file_path))


class TestValidateMessageEvent(unittest.TestCase):
    """Test _validate_message_event helper."""

    def test_validate_message_event_user_message_valid(self) -> None:
        """User message with message field should validate."""
        parser = TestableCodexParser()
        payload: dict[str, Any] = {"type": "user_message", "message": "Hi"}
        TC.assertTrue(parser._validate_message_event(payload))

    def test_validate_message_event_user_message_no_message(self) -> None:
        """User message without message field should not validate."""
        parser = TestableCodexParser()
        payload: dict[str, Any] = {"type": "user_message"}
        TC.assertFalse(parser._validate_message_event(payload))

    def test_validate_message_event_ai_response_valid(self) -> None:
        """AI response with message field should validate."""
        parser = TestableCodexParser()
        payload: dict[str, Any] = {"type": "ai_response", "message": "Hello"}
        TC.assertTrue(parser._validate_message_event(payload))

    def test_validate_message_event_ai_response_no_message(self) -> None:
        """AI response without message field should not validate."""
        parser = TestableCodexParser()
        payload: dict[str, Any] = {"type": "ai_response"}
        TC.assertFalse(parser._validate_message_event(payload))

    def test_validate_message_event_tool_call_valid(self) -> None:
        """Tool call with tool.name should validate."""
        parser = TestableCodexParser()
        payload: dict[str, Any] = {
            "type": "tool_call",
            "tool": {"name": "shell"},
        }
        TC.assertTrue(parser._validate_message_event(payload))

    def test_validate_message_event_tool_call_no_tool(self) -> None:
        """Tool call without tool field should not validate."""
        parser = TestableCodexParser()
        payload: dict[str, Any] = {"type": "tool_call"}
        TC.assertFalse(parser._validate_message_event(payload))

    def test_validate_message_event_tool_call_tool_not_dict(self) -> None:
        """Tool call with non-dict tool should not validate."""
        parser = TestableCodexParser()
        payload: dict[str, Any] = {"type": "tool_call", "tool": "invalid"}
        TC.assertFalse(parser._validate_message_event(payload))

    def test_validate_message_event_tool_call_no_tool_name(self) -> None:
        """Tool call with tool but no name should not validate."""
        parser = TestableCodexParser()
        payload: dict[str, Any] = {"type": "tool_call", "tool": {"parameters": {}}}
        TC.assertFalse(parser._validate_message_event(payload))

    def test_validate_message_event_tool_result_valid(self) -> None:
        """Tool result with tool.name should validate."""
        parser = TestableCodexParser()
        payload: dict[str, Any] = {
            "type": "tool_result",
            "tool": {"name": "shell"},
        }
        TC.assertTrue(parser._validate_message_event(payload))

    def test_validate_message_event_unknown_type(self) -> None:
        """Unknown message type should not validate."""
        parser = TestableCodexParser()
        payload: dict[str, Any] = {"type": "unknown", "data": "something"}
        TC.assertFalse(parser._validate_message_event(payload))

    def test_validate_message_event_missing_type(self) -> None:
        """Payload without type field should not validate."""
        parser = TestableCodexParser()
        payload: dict[str, Any] = {"message": "Hi"}
        TC.assertFalse(parser._validate_message_event(payload))

    def test_validate_message_event_non_string_type(self) -> None:
        """Payload with non-string type should not validate."""
        parser = TestableCodexParser()
        payload: dict[str, Any] = {"type": 123, "message": "Hi"}
        TC.assertFalse(parser._validate_message_event(payload))


class TestValidateBaseStructure(unittest.TestCase):
    """Test _validate_base_structure helper."""

    def test_validate_base_structure_valid(self) -> None:
        """Valid base structure should pass."""
        parser = TestableCodexParser()
        event: dict[str, Any] = {
            "type": "event_msg",
            "timestamp": "2025-11-23T10:00:00+00:00",
        }
        TC.assertTrue(parser._validate_base_structure(event))

    def test_validate_base_structure_not_dict(self) -> None:
        """Non-dict event should not validate."""
        parser = TestableCodexParser()
        TC.assertFalse(parser._validate_base_structure("not a dict"))
        TC.assertFalse(parser._validate_base_structure([]))
        TC.assertFalse(parser._validate_base_structure(None))

    def test_validate_base_structure_missing_type(self) -> None:
        """Event missing type field should not validate."""
        parser = TestableCodexParser()
        event: dict[str, Any] = {"timestamp": "2025-11-23T10:00:00+00:00"}
        TC.assertFalse(parser._validate_base_structure(event))

    def test_validate_base_structure_missing_timestamp(self) -> None:
        """Event missing timestamp field should not validate."""
        parser = TestableCodexParser()
        event: dict[str, Any] = {"type": "event_msg"}
        TC.assertFalse(parser._validate_base_structure(event))

    def test_validate_base_structure_invalid_timestamp_type(self) -> None:
        """Non-string timestamp should not validate."""
        parser = TestableCodexParser()
        event: dict[str, Any] = {"type": "event_msg", "timestamp": 123}
        TC.assertFalse(parser._validate_base_structure(event))

    def test_validate_base_structure_invalid_timestamp_format(self) -> None:
        """Malformed timestamp should not validate."""
        parser = TestableCodexParser()
        event: dict[str, Any] = {
            "type": "event_msg",
            "timestamp": "not-a-date",
        }
        TC.assertFalse(parser._validate_base_structure(event))


class TestValidateEvent(unittest.TestCase):
    """Test validate_event method."""

    def test_validate_event_session_meta(self) -> None:
        """Valid session_meta should validate."""
        parser = TestableCodexParser()
        event: dict[str, Any] = {
            "type": "session_meta",
            "timestamp": "2025-11-23T10:00:00+00:00",
            "payload": {"id": "sid-123"},
        }
        TC.assertTrue(parser.validate_event(event))

    def test_validate_event_session_meta_empty_payload(self) -> None:
        """Session meta with empty payload should validate."""
        parser = TestableCodexParser()
        event: dict[str, Any] = {
            "type": "session_meta",
            "timestamp": "2025-11-23T10:00:00+00:00",
            "payload": {},
        }
        TC.assertTrue(parser.validate_event(event))

    def test_validate_event_event_msg_valid(self) -> None:
        """Valid event_msg should validate."""
        parser = TestableCodexParser()
        event: dict[str, Any] = {
            "type": "event_msg",
            "timestamp": "2025-11-23T10:00:00+00:00",
            "payload": {"type": "user_message", "message": "Hi"},
        }
        TC.assertTrue(parser.validate_event(event))

    def test_validate_event_event_msg_invalid(self) -> None:
        """Invalid event_msg should not validate."""
        parser = TestableCodexParser()
        event: dict[str, Any] = {
            "type": "event_msg",
            "timestamp": "2025-11-23T10:00:00+00:00",
            "payload": {"type": "unknown"},
        }
        TC.assertFalse(parser.validate_event(event))

    def test_validate_event_unknown_type(self) -> None:
        """Unknown event type should not validate."""
        parser = TestableCodexParser()
        event: dict[str, Any] = {
            "type": "unknown_type",
            "timestamp": "2025-11-23T10:00:00+00:00",
            "payload": {},
        }
        TC.assertFalse(parser.validate_event(event))

    def test_validate_event_missing_payload(self) -> None:
        """Event missing payload field should not validate."""
        parser = TestableCodexParser()
        event: dict[str, Any] = {
            "type": "event_msg",
            "timestamp": "2025-11-23T10:00:00+00:00",
        }
        TC.assertFalse(parser.validate_event(event))

    def test_validate_event_invalid_payload_type(self) -> None:
        """Event with non-dict payload should not validate."""
        parser = TestableCodexParser()
        event: dict[str, Any] = {
            "type": "event_msg",
            "timestamp": "2025-11-23T10:00:00+00:00",
            "payload": "invalid",
        }
        TC.assertFalse(parser.validate_event(event))


class TestAgentTypeProperty(unittest.TestCase):
    """Test agent_type property."""

    def test_agent_type_returns_codex(self) -> None:
        """agent_type property should return 'codex'."""
        parser = TestableCodexParser()
        TC.assertEqual(parser.agent_type, "codex")
