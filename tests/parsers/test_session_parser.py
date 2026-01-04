"""Tests for session_parser module (AI-assisted).

Purpose: Test all functions, branches, and edge cases in session_parser.
Content: Session discovery, file loading, event parsing, and user message grouping.
Author: Lauren Parlett with Codex (consolidated with helpers)
Date: 2025-11-30
AI-assisted: Claude Haiku 4.5
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

import pytest

from src.parsers.session_parser import (
    SessionDiscoveryError,
    iter_sorted_directories,
    find_first_session_file,
    iter_session_files,
    load_session_events,
    group_by_user_messages,
)


TC = unittest.TestCase()


class TestIterSortedDirectories:
    """Test directory iteration and sorting."""

    def test_iter_sorted_directories_basic(self, tmp_path: Path) -> None:
        """iter_sorted_directories should yield directories in sorted order."""
        # Create directories with names that test sorting
        (tmp_path / "2025").mkdir()
        (tmp_path / "2024").mkdir()
        (tmp_path / "2026").mkdir()

        dirs = list(iter_sorted_directories(tmp_path))
        dir_names = [d.name for d in dirs]

        TC.assertEqual(dir_names, ["2024", "2025", "2026"])

    def test_iter_sorted_directories_ignores_files(self, tmp_path: Path) -> None:
        """iter_sorted_directories should skip files."""
        (tmp_path / "subdir").mkdir()
        (tmp_path / "file.txt").write_text("content", encoding="utf-8")

        dirs = list(iter_sorted_directories(tmp_path))

        TC.assertEqual(len(dirs), 1)
        TC.assertEqual(dirs[0].name, "subdir")

    def test_iter_sorted_directories_empty(self, tmp_path: Path) -> None:
        """iter_sorted_directories should yield nothing for empty directory."""
        dirs = list(iter_sorted_directories(tmp_path))
        TC.assertEqual(dirs, [])

    def test_iter_sorted_directories_numeric_sorting(self, tmp_path: Path) -> None:
        """Directories should be sorted lexicographically."""
        for i in [10, 2, 1, 20, 3]:
            (tmp_path / str(i)).mkdir()

        dirs = list(iter_sorted_directories(tmp_path))
        dir_names = [d.name for d in dirs]

        # Lexicographic sort: "1", "10", "2", "20", "3"
        TC.assertEqual(dir_names, ["1", "10", "2", "20", "3"])

    def test_iter_sorted_directories_mixed_names(self, tmp_path: Path) -> None:
        """Directories with mixed naming should be sorted correctly."""
        names = ["z_dir", "a_dir", "m_dir"]
        for name in names:
            (tmp_path / name).mkdir()

        dirs = list(iter_sorted_directories(tmp_path))
        dir_names = [d.name for d in dirs]

        TC.assertEqual(dir_names, ["a_dir", "m_dir", "z_dir"])


class TestFindFirstSessionFile:
    """Test finding the earliest session file."""

    def test_find_first_session_file_nested_structure(self, tmp_path: Path) -> None:
        """find_first_session_file should find earliest file in nested hierarchy."""
        # Create year/month/day structure
        sessions_dir = tmp_path / "sessions"
        year_dir = sessions_dir / "2025"
        month_dir = year_dir / "01"
        day_dir = month_dir / "01"
        day_dir.mkdir(parents=True, exist_ok=True)

        session_file = day_dir / "session.jsonl"
        session_file.write_text("{}\n", encoding="utf-8")

        result = find_first_session_file(sessions_dir)

        TC.assertEqual(result.name, "session.jsonl")
        TC.assertTrue(result.exists())

    def test_find_first_session_file_multiple_years(self, tmp_path: Path) -> None:
        """find_first_session_file should return earliest year."""
        sessions_dir = tmp_path / "sessions"

        # Create files in 2025 and 2024
        (sessions_dir / "2025" / "01" / "01").mkdir(parents=True, exist_ok=True)
        (sessions_dir / "2025" / "01" / "01" / "session_2025.jsonl").write_text(
            "{}\n", encoding="utf-8"
        )

        (sessions_dir / "2024" / "12" / "31").mkdir(parents=True, exist_ok=True)
        (sessions_dir / "2024" / "12" / "31" / "session_2024.jsonl").write_text(
            "{}\n", encoding="utf-8"
        )

        result = find_first_session_file(sessions_dir)

        # Should find 2024 (earlier year)
        TC.assertIn("2024", str(result))

    def test_find_first_session_file_multiple_months(self, tmp_path: Path) -> None:
        """find_first_session_file should return earliest month within year."""
        sessions_dir = tmp_path / "sessions"

        # Create files in months 03 and 01
        (sessions_dir / "2025" / "03" / "01").mkdir(parents=True, exist_ok=True)
        (sessions_dir / "2025" / "03" / "01" / "session_03.jsonl").write_text(
            "{}\n", encoding="utf-8"
        )

        (sessions_dir / "2025" / "01" / "01").mkdir(parents=True, exist_ok=True)
        (sessions_dir / "2025" / "01" / "01" / "session_01.jsonl").write_text(
            "{}\n", encoding="utf-8"
        )

        result = find_first_session_file(sessions_dir)

        # Should find 01 (earlier month)
        TC.assertIn("01", str(result))

    def test_find_first_session_file_multiple_days(self, tmp_path: Path) -> None:
        """find_first_session_file should return earliest day within month."""
        sessions_dir = tmp_path / "sessions"

        # Create files on days 15 and 05
        (sessions_dir / "2025" / "01" / "15").mkdir(parents=True, exist_ok=True)
        (sessions_dir / "2025" / "01" / "15" / "session_15.jsonl").write_text(
            "{}\n", encoding="utf-8"
        )

        (sessions_dir / "2025" / "01" / "05").mkdir(parents=True, exist_ok=True)
        (sessions_dir / "2025" / "01" / "05" / "session_05.jsonl").write_text(
            "{}\n", encoding="utf-8"
        )

        result = find_first_session_file(sessions_dir)

        # Should find 05 (earlier day)
        TC.assertIn("05", str(result))

    def test_find_first_session_file_multiple_files_same_day(
        self, tmp_path: Path
    ) -> None:
        """find_first_session_file should return first file alphabetically on same day."""
        sessions_dir = tmp_path / "sessions"
        day_dir = sessions_dir / "2025" / "01" / "01"
        day_dir.mkdir(parents=True, exist_ok=True)

        (day_dir / "z_session.jsonl").write_text("{}\n", encoding="utf-8")
        (day_dir / "a_session.jsonl").write_text("{}\n", encoding="utf-8")
        (day_dir / "m_session.jsonl").write_text("{}\n", encoding="utf-8")

        result = find_first_session_file(sessions_dir)

        # Should find alphabetically first file
        TC.assertEqual(result.name, "a_session.jsonl")

    def test_find_first_session_file_no_files_raises_error(
        self, tmp_path: Path
    ) -> None:
        """find_first_session_file should raise when no files found."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        with pytest.raises(SessionDiscoveryError):
            find_first_session_file(sessions_dir)

    def test_find_first_session_file_empty_root_raises_error(
        self, tmp_path: Path
    ) -> None:
        """find_first_session_file should raise when root directory doesn't exist."""
        nonexistent = tmp_path / "nonexistent"

        # This will raise when trying to iterate
        with pytest.raises(Exception):  # FileNotFoundError or similar
            find_first_session_file(nonexistent)


class TestIterSessionFiles:
    """Test iterating all session files."""

    def test_iter_session_files_single_file(self, tmp_path: Path) -> None:
        """iter_session_files should yield single file."""
        sessions_dir = tmp_path / "sessions"
        day_dir = sessions_dir / "2025" / "01" / "01"
        day_dir.mkdir(parents=True, exist_ok=True)

        session_file = day_dir / "session.jsonl"
        session_file.write_text("{}\n", encoding="utf-8")

        files = list(iter_session_files(sessions_dir))

        TC.assertEqual(len(files), 1)
        TC.assertEqual(files[0].name, "session.jsonl")

    def test_iter_session_files_multiple_files_sorted(self, tmp_path: Path) -> None:
        """iter_session_files should yield files in chronological order."""
        sessions_dir = tmp_path / "sessions"

        # Create structure: 2025/01/(01, 02), 2025/02/01
        (sessions_dir / "2025" / "01" / "01").mkdir(parents=True, exist_ok=True)
        (sessions_dir / "2025" / "01" / "01" / "file_01_01.jsonl").write_text(
            "{}\n", encoding="utf-8"
        )

        (sessions_dir / "2025" / "01" / "02").mkdir(parents=True, exist_ok=True)
        (sessions_dir / "2025" / "01" / "02" / "file_01_02.jsonl").write_text(
            "{}\n", encoding="utf-8"
        )

        (sessions_dir / "2025" / "02" / "01").mkdir(parents=True, exist_ok=True)
        (sessions_dir / "2025" / "02" / "01" / "file_02_01.jsonl").write_text(
            "{}\n", encoding="utf-8"
        )

        files = list(iter_session_files(sessions_dir))

        TC.assertEqual(len(files), 3)
        TC.assertIn("file_01_01.jsonl", files[0].name)
        TC.assertIn("file_01_02.jsonl", files[1].name)
        TC.assertIn("file_02_01.jsonl", files[2].name)

    def test_iter_session_files_multiple_files_same_day_sorted(
        self, tmp_path: Path
    ) -> None:
        """iter_session_files should sort files within same day."""
        sessions_dir = tmp_path / "sessions"
        day_dir = sessions_dir / "2025" / "01" / "01"
        day_dir.mkdir(parents=True, exist_ok=True)

        (day_dir / "z_session.jsonl").write_text("{}\n", encoding="utf-8")
        (day_dir / "a_session.jsonl").write_text("{}\n", encoding="utf-8")
        (day_dir / "m_session.jsonl").write_text("{}\n", encoding="utf-8")

        files = list(iter_session_files(sessions_dir))

        file_names = [f.name for f in files]
        TC.assertEqual(
            file_names, ["a_session.jsonl", "m_session.jsonl", "z_session.jsonl"]
        )

    def test_iter_session_files_ignores_directories(self, tmp_path: Path) -> None:
        """iter_session_files should skip directories, only yield files."""
        sessions_dir = tmp_path / "sessions"
        day_dir = sessions_dir / "2025" / "01" / "01"
        day_dir.mkdir(parents=True, exist_ok=True)

        (day_dir / "session.jsonl").write_text("{}\n", encoding="utf-8")
        (day_dir / "subdir").mkdir()

        files = list(iter_session_files(sessions_dir))

        TC.assertEqual(len(files), 1)
        TC.assertEqual(files[0].name, "session.jsonl")

    def test_iter_session_files_empty_directory(self, tmp_path: Path) -> None:
        """iter_session_files should yield nothing for empty directory."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        files = list(iter_session_files(sessions_dir))

        TC.assertEqual(files, [])


class TestLoadSessionEvents:
    """Test loading JSONL session events."""

    def test_load_session_events_single_event(self, tmp_path: Path) -> None:
        """load_session_events should load single event."""
        session_file = tmp_path / "session.jsonl"
        session_file.write_text(
            '{"type": "event_msg", "payload": {}}\n', encoding="utf-8"
        )

        events = load_session_events(session_file)

        TC.assertEqual(len(events), 1)
        TC.assertEqual(events[0]["type"], "event_msg")

    def test_load_session_events_multiple_events(self, tmp_path: Path) -> None:
        """load_session_events should load multiple events."""
        session_file = tmp_path / "session.jsonl"
        content = (
            '{"type": "event_msg", "id": 1}\n'
            '{"type": "response_item", "id": 2}\n'
            '{"type": "turn_context", "id": 3}\n'
        )
        session_file.write_text(content, encoding="utf-8")

        events = load_session_events(session_file)

        TC.assertEqual(len(events), 3)
        TC.assertEqual(events[0]["id"], 1)
        TC.assertEqual(events[1]["id"], 2)
        TC.assertEqual(events[2]["id"], 3)

    def test_load_session_events_skips_blank_lines(self, tmp_path: Path) -> None:
        """load_session_events should skip empty lines."""
        session_file = tmp_path / "session.jsonl"
        content = (
            '{"type": "event_msg", "id": 1}\n'
            "\n"
            "  \n"
            '{"type": "response_item", "id": 2}\n'
            "\n"
        )
        session_file.write_text(content, encoding="utf-8")

        events = load_session_events(session_file)

        TC.assertEqual(len(events), 2)
        TC.assertEqual(events[0]["id"], 1)
        TC.assertEqual(events[1]["id"], 2)

    def test_load_session_events_invalid_json_raises_error(
        self, tmp_path: Path
    ) -> None:
        """load_session_events should raise ValueError on invalid JSON."""
        session_file = tmp_path / "session.jsonl"
        session_file.write_text('{"invalid": json}\n', encoding="utf-8")

        with pytest.raises(ValueError) as exc_info:
            load_session_events(session_file)

        TC.assertIn("Failed to parse JSON", str(exc_info.value))
        TC.assertIn("line 1", str(exc_info.value))

    def test_load_session_events_invalid_json_on_line_n_reports_line(
        self, tmp_path: Path
    ) -> None:
        """load_session_events should report correct line number on error."""
        session_file = tmp_path / "session.jsonl"
        content = "".join(
            [
                '{"valid": "json"}\n',
                '{"valid": "json"}\n',
                '{"invalid": json}\n',
            ]
        )
        session_file.write_text(content, encoding="utf-8")

        with pytest.raises(ValueError) as exc_info:
            load_session_events(session_file)

        TC.assertIn("line 3", str(exc_info.value))

    def test_load_session_events_complex_nested_json(self, tmp_path: Path) -> None:
        """load_session_events should handle complex nested JSON."""
        session_file = tmp_path / "session.jsonl"
        event = {
            "type": "event_msg",
            "payload": {
                "type": "user_message",
                "message": "Hello",
                "metadata": {
                    "nested": {
                        "deeply": ["list", "of", "values"],
                        "bool": True,
                        "null": None,
                    }
                },
            },
        }
        session_file.write_text(json.dumps(event) + "\n", encoding="utf-8")

        events = load_session_events(session_file)

        TC.assertEqual(len(events), 1)
        TC.assertEqual(
            events[0]["payload"]["metadata"]["nested"]["deeply"],
            ["list", "of", "values"],
        )

    def test_load_session_events_unicode_content(self, tmp_path: Path) -> None:
        """load_session_events should handle Unicode content."""
        session_file = tmp_path / "session.jsonl"
        event = {
            "type": "event_msg",
            "message": "Hello 世界 🌍 Ñoño",
        }
        session_file.write_text(
            json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8"
        )

        events = load_session_events(session_file)

        TC.assertEqual(len(events), 1)
        TC.assertIn("世界", events[0]["message"])
        TC.assertIn("🌍", events[0]["message"])

    def test_load_session_events_empty_file(self, tmp_path: Path) -> None:
        """load_session_events should return empty list for empty file."""
        session_file = tmp_path / "session.jsonl"
        session_file.write_text("", encoding="utf-8")

        events = load_session_events(session_file)

        TC.assertEqual(events, [])

    def test_load_session_events_only_blank_lines(self, tmp_path: Path) -> None:
        """load_session_events should return empty list for only blank lines."""
        session_file = tmp_path / "session.jsonl"
        session_file.write_text("\n\n  \n\t\n", encoding="utf-8")

        events = load_session_events(session_file)

        TC.assertEqual(events, [])

    def test_load_session_events_handles_trailing_partial_json(
        self, tmp_path: Path
    ) -> None:
        """load_session_events should fail on malformed JSON lines."""
        log_file = tmp_path / "bad.jsonl"
        log_file.write_text('{"ok": true}\n{"incomplete": ', encoding="utf-8")
        with pytest.raises(ValueError):
            load_session_events(log_file)


# ============================================================================
# Helper function tests from test_session_parser_helpers.py
# ============================================================================


def test_group_by_user_messages_splits_prelude_and_multiple_groups() -> None:
    """Group events around user messages and preserve prelude."""
    events: list[dict[str, Any]] = [
        {"type": "session_meta", "payload": {"id": "s1"}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "First"}},
        {"type": "event_msg", "payload": {"type": "agent_message", "message": "A1"}},
        {"type": "response_item", "payload": {"type": "message", "text": "B1"}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "Second"}},
        {"type": "event_msg", "payload": {"type": "agent_message", "message": "A2"}},
    ]

    prelude, groups = group_by_user_messages(events)

    TC.assertEqual(len(prelude), 1)
    TC.assertEqual(len(groups), 2)

    first_group = groups[0]
    second_group = groups[1]

    TC.assertEqual(first_group["user"]["payload"]["message"], "First")
    TC.assertEqual(len(first_group["events"]), 2)
    TC.assertEqual(second_group["user"]["payload"]["message"], "Second")
    TC.assertEqual(len(second_group["events"]), 1)


def test_group_by_user_messages_handles_missing_payloads() -> None:
    """Non-dict payloads should be treated as non-user events and go to prelude."""

    events: list[dict[str, Any]] = [
        {"type": None, "payload": "not-a-dict"},
        {"type": "event_msg", "payload": "still-not-a-dict"},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "Go"}},
        {"type": "turn_context", "payload": {"cwd": "/workspace"}},
        {"payload": {"type": "agent_message", "message": "missing type"}},
    ]

    prelude, groups = group_by_user_messages(events)

    TC.assertIn({"type": None, "payload": "not-a-dict"}, prelude)
    TC.assertIn({"type": "event_msg", "payload": "still-not-a-dict"}, prelude)
    TC.assertEqual(len(groups), 1)
    TC.assertEqual(groups[0]["user"]["payload"]["message"], "Go")
    TC.assertEqual(groups[0]["events"][0]["type"], "turn_context")


def test_group_by_user_messages_handles_empty_events_list() -> None:
    """Empty event list should return empty prelude and groups."""

    prelude, groups = group_by_user_messages([])
    TC.assertEqual(prelude, [])
    TC.assertEqual(groups, [])


class TestGroupByUserMessages:
    """Test grouping events by user messages (comprehensive edge cases)."""

    def test_group_by_user_messages_no_user_messages(self) -> None:
        """All events before first user message should be in prelude."""
        events = [
            {"type": "session_meta", "payload": {}},
            {"type": "system_message", "payload": {}},
        ]

        prelude, groups = group_by_user_messages(events)

        TC.assertEqual(len(prelude), 2)
        TC.assertEqual(len(groups), 0)

    def test_group_by_user_messages_only_user_messages(self) -> None:
        """Only user messages with no trailing events."""
        events = [
            {"type": "event_msg", "payload": {"type": "user_message", "message": "Q1"}},
            {"type": "event_msg", "payload": {"type": "user_message", "message": "Q2"}},
        ]

        prelude, groups = group_by_user_messages(events)

        TC.assertEqual(len(prelude), 0)
        TC.assertEqual(len(groups), 2)
        TC.assertEqual(groups[0]["events"], [])
        TC.assertEqual(groups[1]["events"], [])

    def test_group_by_user_messages_payload_not_dict(self) -> None:
        """Non-dict payloads should not trigger grouping."""
        events: list[dict[str, Any]] = [
            {"type": "event_msg", "payload": None},
            {"type": "event_msg", "payload": "string"},
            {
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "Real"},
            },
        ]

        prelude, groups = group_by_user_messages(events)

        TC.assertEqual(len(prelude), 2)
        TC.assertEqual(len(groups), 1)

    def test_group_by_user_messages_missing_type_field(self) -> None:
        """Events missing 'type' field should be handled."""
        events: list[dict[str, Any]] = [
            {"payload": {"type": "user_message", "message": "Q"}},
            {"type": "event_msg", "payload": {"type": "user_message", "message": "Q2"}},
        ]

        prelude, groups = group_by_user_messages(events)

        TC.assertEqual(len(prelude), 1)
        TC.assertEqual(len(groups), 1)

    def test_group_by_user_messages_events_after_last_group(self) -> None:
        """Events after last user message should be grouped."""
        events = [
            {"type": "event_msg", "payload": {"type": "user_message", "message": "Q"}},
            {
                "type": "event_msg",
                "payload": {"type": "agent_message", "message": "A1"},
            },
            {"type": "response_item", "payload": {}},
            {"type": "turn_context", "payload": {}},
        ]

        _, groups = group_by_user_messages(events)

        TC.assertEqual(len(groups), 1)
        TC.assertEqual(len(groups[0]["events"]), 3)

    def test_group_by_user_messages_consecutive_user_messages(self) -> None:
        """Consecutive user messages should each start new groups."""
        events = [
            {"type": "event_msg", "payload": {"type": "user_message", "message": "Q1"}},
            {"type": "event_msg", "payload": {"type": "user_message", "message": "Q2"}},
            {"type": "event_msg", "payload": {"type": "user_message", "message": "Q3"}},
        ]

        _, groups = group_by_user_messages(events)

        TC.assertEqual(len(groups), 3)
        TC.assertEqual(groups[0]["user"]["payload"]["message"], "Q1")
        TC.assertEqual(groups[1]["user"]["payload"]["message"], "Q2")
        TC.assertEqual(groups[2]["user"]["payload"]["message"], "Q3")

    def test_group_by_user_messages_multiple_event_types_in_group(self) -> None:
        """Group should collect all event types between user messages."""
        events = [
            {"type": "event_msg", "payload": {"type": "user_message", "message": "Q"}},
            {"type": "event_msg", "payload": {"type": "agent_message"}},
            {"type": "response_item", "payload": {"type": "message"}},
            {"type": "response_item", "payload": {"type": "function_call"}},
            {"type": "turn_context", "payload": {}},
            {"type": "event_msg", "payload": {"type": "user_message", "message": "Q2"}},
        ]

        _, groups = group_by_user_messages(events)

        TC.assertEqual(len(groups), 2)
        TC.assertEqual(len(groups[0]["events"]), 4)
        TC.assertEqual(groups[0]["events"][0]["type"], "event_msg")
        TC.assertEqual(groups[0]["events"][1]["type"], "response_item")
        TC.assertEqual(groups[0]["events"][2]["type"], "response_item")
        TC.assertEqual(groups[0]["events"][3]["type"], "turn_context")

    def test_group_by_user_messages_generator_input(self) -> None:
        """group_by_user_messages should work with generators."""

        def event_generator() -> Any:
            yield {
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "Q"},
            }
            yield {"type": "response_item", "payload": {}}

        _, groups = group_by_user_messages(event_generator())

        TC.assertEqual(len(groups), 1)
        TC.assertEqual(len(groups[0]["events"]), 1)
