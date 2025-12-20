"""Tests for group_session CLI and session_parser utilities (AI-assisted by Codex GPT-5).

Tests session event parsing, rendering, and grouping functionality for
working with Codex session logs and user message prompts/responses.
"""

# pylint: disable=import-error,protected-access

from __future__ import annotations

from pathlib import Path

import unittest

import pytest

from cli import group_session
from src.parsers import session_parser

TC = unittest.TestCase()


def test_describe_event_handles_message_payload() -> None:
    """describe_event should include payload type and timestamp."""
    event = {
        "type": "event_msg",
        "timestamp": "2025-10-31T10:00:00Z",
        "payload": {"type": "agent_message", "message": "Hello world"},
    }
    desc = group_session.describe_event(event)
    TC.assertIn("event_msg (agent_message) @ 2025-10-31T10:00:00Z", desc)
    TC.assertIn("Hello world", desc)


def test_render_prelude_and_groups(capsys: pytest.CaptureFixture[str]) -> None:
    """_render_groups should handle empty and populated groups."""
    captured: list[str] = []
    # no groups path
    group_session._render_groups([], captured)  # pylint: disable=protected-access
    TC.assertIn("No user messages found", captured[-1])

    # populated path
    captured.clear()
    groups = [
        {
            "user": {"timestamp": "t1", "payload": {"message": "Hi"}},
            "events": [
                {
                    "type": "event_msg",
                    "timestamp": "t2",
                    "payload": {"type": "ai_response", "message": "Hey"},
                }  # noqa: E501
            ],
        }
    ]
    group_session._render_groups(groups, captured)  # pylint: disable=protected-access
    out = capsys.readouterr().out
    TC.assertIn("Prompt 1", out)
    TC.assertIn("ai_response", out)


def test_group_by_user_messages_splits_prelude_and_groups() -> None:
    """Ensure grouping yields prelude and grouped events correctly."""
    events = [
        {"type": "session_meta", "payload": {}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "Hi"}},
        {"type": "event_msg", "payload": {"type": "ai_response", "message": "Hello"}},
    ]
    prelude, groups = session_parser.group_by_user_messages(events)
    TC.assertEqual(len(prelude), 1)
    TC.assertEqual(len(groups), 1)
    TC.assertEqual(groups[0]["user"]["payload"]["message"], "Hi")
    TC.assertEqual(groups[0]["events"][0]["payload"]["message"], "Hello")


def test_describe_response_item_branches() -> None:
    """_describe_payload should render response and function call details."""
    payload = {
        "type": "response_item",
        "timestamp": "t1",
        "payload": {"type": "function_call_output", "output": "done"},
    }
    desc = group_session.describe_event(payload)
    TC.assertTrue("function_call_output" in desc or "output" in desc)


def test_find_first_session_file_returns_earliest(tmp_path: Path) -> None:
    """find_first_session_file should select the earliest file by path order."""
    # create nested structure year/month/day with files
    day1 = tmp_path / "2024" / "01" / "01"
    day2 = tmp_path / "2024" / "02" / "01"
    for path in (day1, day2):
        path.mkdir(parents=True, exist_ok=True)
    first = day1 / "a.jsonl"
    second = day2 / "b.jsonl"
    first.write_text("{}", encoding="utf-8")
    second.write_text("{}", encoding="utf-8")

    found = session_parser.find_first_session_file(tmp_path)
    TC.assertEqual(found, first)


def test_describe_event_token_and_turn_context(tmp_path: Path) -> None:
    """describe_event should cover token_count and turn_context payloads."""

    token_event = {
        "type": "event_msg",
        "timestamp": "t0",
        "payload": {
            "type": "token_count",
            "rate_limits": {
                "primary": {"used_percent": 10, "window_minutes": 60, "resets_at": 123}
            },
        },
    }
    desc = group_session.describe_event(token_event)
    TC.assertIn("primary", desc)
    TC.assertIn("10%", desc)

    turn_ctx_event = {
        "type": "turn_context",
        "timestamp": "t1",
        "payload": {"cwd": str(tmp_path / "work")},
    }
    ctx_desc = group_session.describe_event(turn_ctx_event)
    work_path = str(tmp_path / "work")
    TC.assertIn(f"cwd: {work_path}", ctx_desc)


def test_render_prelude_and_prompt_group_empty_events(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Prelude rendering and empty group events should be printed and captured."""

    prelude = [
        {
            "type": "event_msg",
            "timestamp": "t0",
            "payload": {"type": "agent_message", "message": "Prelude hello"},
        }
    ]
    captured: list[str] = []
    group_session._render_prelude(prelude, captured)  # pylint: disable=protected-access
    out = capsys.readouterr().out
    TC.assertIn("-- Session Prelude --", out)
    TC.assertIn("Prelude hello", out)

    captured.clear()
    group = {
        "user": {"timestamp": "t1", "payload": {"message": "Hi there"}},
        "events": [],
    }
    group_session._render_prompt_group(
        1, group, captured
    )  # pylint: disable=protected-access
    out = capsys.readouterr().out
    TC.assertIn("Prompt 1", out)
    TC.assertIn("No subsequent events recorded.", out)


def test_describe_event_handles_unknown_payloads() -> None:
    """describe_event should degrade gracefully on missing/unknown payload types."""

    unknown_payload = {"type": "event_msg", "timestamp": "t0", "payload": {}}
    desc_unknown = group_session.describe_event(unknown_payload)
    TC.assertIn("event_msg", desc_unknown)

    missing_payload = {"type": "turn_context", "timestamp": "t1"}
    desc_missing = group_session.describe_event(missing_payload)
    TC.assertIn("turn_context", desc_missing)

    none_payload = {"type": "event_msg", "timestamp": "t2", "payload": None}
    desc_none = group_session.describe_event(none_payload)
    TC.assertIn("event_msg", desc_none)
