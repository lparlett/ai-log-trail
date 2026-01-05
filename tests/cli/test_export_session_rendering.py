"""Tests for export_session rendering and output (AI-assisted).

Covers event rendering, output formatting, and various payload structures
for the export_session command-line interface.
"""

# pylint: disable=protected-access

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

import cli.export_session as export_cli
from src.services.config import DatabaseConfig, OutputPaths, SessionsConfig
from src.services.database import ensure_schema, get_connection


TC = unittest.TestCase()


class TestRenderExport:
    # pylint: disable=too-few-public-methods
    # Justification: Single-test class for organizing export rendering tests
    # without bloating the module namespace.
    """Test full export rendering."""

    def _fake_config(self, tmp_path: Path) -> SessionsConfig:
        """Create a fake config."""
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        return SessionsConfig(
            codex_root=tmp_path / "sessions",
            ingest_batch_size=10,
            database=DatabaseConfig(sqlite_path=tmp_path / "db.sqlite"),
            outputs=OutputPaths(reports_dir=reports_dir),
        )

    def _write_session(self, tmp_path: Path) -> None:
        """Write a test session file."""
        session_root = tmp_path / "sessions" / "2025" / "01" / "01"
        session_root.mkdir(parents=True, exist_ok=True)
        events = [
            {
                "type": "event_msg",
                "timestamp": "t0",
                "payload": {"type": "user_message", "message": "hello"},
            },
        ]
        lines = "\n".join(json.dumps(event) for event in events)
        (session_root / "session.jsonl").write_text(lines + "\n", encoding="utf-8")

    def test_render_export_with_session(self, tmp_path: Path) -> None:
        """Should render export from session file."""
        self._write_session(tmp_path)
        config = self._fake_config(tmp_path)
        conn = get_connection(config.database.sqlite_path)
        ensure_schema(conn)

        lines, _ = export_cli._render_export(config, [], conn)

        TC.assertGreater(len(lines), 0)
        joined_lines = "\n".join(lines)
        TC.assertIn("Session file:", joined_lines)

    def test_render_event_with_various_payload_types(self, tmp_path: Path) -> None:
        """Should handle different event payload types."""
        config = self._fake_config(tmp_path)
        conn = get_connection(config.database.sqlite_path)
        ensure_schema(conn)
        rules: list[Any] = []

        # Test with token_count event
        event: dict[str, Any] = {
            "type": "event_msg",
            "timestamp": "t0",
            "payload": {"type": "token_count", "primary": "0.5", "secondary": "0.2"},
        }
        lines, _, _ = export_cli._render_event(
            event,
            rules,
            conn=conn,
            file_id=None,
            prompt_id=None,
            session_file_path="/test.jsonl",
        )
        TC.assertGreater(len(lines), 0)

    def test_render_response_message_event(self, tmp_path: Path) -> None:
        """Should render response_item message events."""
        config = self._fake_config(tmp_path)
        conn = get_connection(config.database.sqlite_path)
        ensure_schema(conn)
        rules: list[Any] = []

        event: dict[str, Any] = {
            "type": "response_item",
            "timestamp": "t0",
            "payload": {
                "type": "message",
                "content": [{"text": "This is a response"}],
            },
        }
        lines, _, _ = export_cli._render_event(
            event,
            rules,
            conn=conn,
            file_id=None,
            prompt_id=None,
            session_file_path="/test.jsonl",
        )
        TC.assertGreater(len(lines), 0)

    def test_render_function_call_event(self, tmp_path: Path) -> None:
        """Should render response_item function_call events."""
        config = self._fake_config(tmp_path)
        conn = get_connection(config.database.sqlite_path)
        ensure_schema(conn)
        rules: list[Any] = []

        event: dict[str, Any] = {
            "type": "response_item",
            "timestamp": "t0",
            "payload": {
                "type": "function_call",
                "name": "shell",
                "arguments": '{"command": "ls"}',
            },
        }
        lines, _, _ = export_cli._render_event(
            event,
            rules,
            conn=conn,
            file_id=None,
            prompt_id=None,
            session_file_path="/test.jsonl",
        )
        TC.assertGreater(len(lines), 0)

    def test_render_function_call_output_event(self, tmp_path: Path) -> None:
        """Should render function_call_output events."""
        config = self._fake_config(tmp_path)
        conn = get_connection(config.database.sqlite_path)
        ensure_schema(conn)
        rules: list[Any] = []

        event: dict[str, Any] = {
            "type": "response_item",
            "timestamp": "t0",
            "payload": {
                "type": "function_call_output",
                "output": '{"result": "success"}',
            },
        }
        lines, _, _ = export_cli._render_event(
            event,
            rules,
            conn=conn,
            file_id=None,
            prompt_id=None,
            session_file_path="/test.jsonl",
        )
        TC.assertGreater(len(lines), 0)

    def test_render_turn_context_event(self, tmp_path: Path) -> None:
        """Should render turn_context events."""
        config = self._fake_config(tmp_path)
        conn = get_connection(config.database.sqlite_path)
        ensure_schema(conn)
        rules: list[Any] = []

        event: dict[str, Any] = {
            "type": "turn_context",
            "timestamp": "t0",
            "payload": {"cwd": "/home/user/project"},
        }
        lines, _, _ = export_cli._render_event(
            event,
            rules,
            conn=conn,
            file_id=None,
            prompt_id=None,
            session_file_path="/test.jsonl",
        )
        TC.assertGreater(len(lines), 0)

    def test_write_output_creates_file(self, tmp_path: Path) -> None:
        """Should write output to a file."""
        output_file = tmp_path / "output.txt"
        lines = ["line 1", "line 2", "line 3"]

        export_cli._write_output(output_file, lines)

        TC.assertTrue(output_file.exists())
        content = output_file.read_text(encoding="utf-8")
        TC.assertIn("line 1", content)
        TC.assertIn("line 2", content)
        TC.assertIn("line 3", content)

    def test_scope_matches_global(self) -> None:
        """Should match 'global' scope against any context scope."""
        TC.assertTrue(export_cli._scope_matches("global", "interaction"))
        TC.assertTrue(export_cli._scope_matches("global", "field"))
        TC.assertTrue(export_cli._scope_matches("global", "global"))

    def test_scope_matches_specific(self) -> None:
        """Should match specific scopes only to same scope."""
        TC.assertTrue(export_cli._scope_matches("interaction", "interaction"))
        TC.assertFalse(export_cli._scope_matches("interaction", "field"))
        TC.assertTrue(export_cli._scope_matches("field", "field"))
        TC.assertFalse(export_cli._scope_matches("field", "interaction"))


class TestRenderExportErrorPaths:
    """Test error handling in _render_export function."""

    def test_render_export_session_discovery_error(
        self, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """Should handle SessionDiscoveryError gracefully."""
        from src.parsers.session_parser import (  # pylint: disable=import-outside-toplevel
            SessionDiscoveryError,
        )

        config = SessionsConfig(
            codex_root=tmp_path / "sessions",
            database=DatabaseConfig(sqlite_path=tmp_path / "db.sqlite"),
            outputs=OutputPaths(reports_dir=tmp_path),
        )
        conn = get_connection(config.database.sqlite_path)
        ensure_schema(conn)

        def _raise_discovery_error(*args: Any, **kwargs: Any) -> None:
            raise SessionDiscoveryError("No sessions found")

        monkeypatch.setattr(
            export_cli, "find_first_session_file", _raise_discovery_error
        )

        lines, summary = export_cli._render_export(config, [], conn)
        conn.close()

        TC.assertGreater(len(lines), 0)
        TC.assertIn("Session discovery error", lines[0])
        TC.assertEqual(summary, [])

    def test_render_export_with_empty_groups(self, tmp_path: Path) -> None:
        """Should render export with empty user groups."""
        config = SessionsConfig(
            codex_root=tmp_path / "sessions",
            database=DatabaseConfig(sqlite_path=tmp_path / "db.sqlite"),
            outputs=OutputPaths(reports_dir=tmp_path),
        )
        conn = get_connection(config.database.sqlite_path)
        ensure_schema(conn)

        # Create session with events but no user messages
        session_root = tmp_path / "sessions" / "2025" / "01" / "01"
        session_root.mkdir(parents=True, exist_ok=True)
        events = [
            {
                "type": "turn_context",
                "timestamp": "t0",
                "payload": {"cwd": "/home/user"},
            }
        ]
        lines_text = "\n".join(json.dumps(event) for event in events)
        (session_root / "session.jsonl").write_text(lines_text + "\n", encoding="utf-8")

        lines, _ = export_cli._render_export(config, [], conn)
        conn.close()

        TC.assertGreater(len(lines), 0)
        TC.assertIn("Session file:", lines[0])


class TestRenderEventVariations:
    """Test _render_event with various payload structures."""

    def test_render_event_payload_not_dict(self, tmp_path: Path) -> None:
        """Should handle non-dict payload gracefully."""
        conn = get_connection(tmp_path / "db.sqlite")
        ensure_schema(conn)

        event: dict[str, Any] = {
            "type": "unknown_event",
            "timestamp": "t0",
            "payload": "not_a_dict",
        }
        lines, rule_counts, manual_counts = export_cli._render_event(
            event,
            [],
            conn=conn,
            file_id=None,
            prompt_id=None,
            session_file_path="/test.jsonl",
        )
        conn.close()

        TC.assertGreater(len(lines), 0)
        TC.assertEqual(len(rule_counts), 0)
        TC.assertEqual(len(manual_counts), 0)

    def test_render_event_missing_timestamp(self, tmp_path: Path) -> None:
        """Should handle missing timestamp in event."""
        conn = get_connection(tmp_path / "db.sqlite")
        ensure_schema(conn)

        event: dict[str, Any] = {
            "type": "event_msg",
            "payload": {"type": "agent_reasoning", "text": "test"},
        }
        lines, _, _ = export_cli._render_event(
            event,
            [],
            conn=conn,
            file_id=None,
            prompt_id=None,
            session_file_path="/test.jsonl",
        )
        conn.close()

        TC.assertGreater(len(lines), 0)
        TC.assertIn("?", lines[0])

    def test_render_event_agent_message_empty_text(self, tmp_path: Path) -> None:
        """Should skip agent_message with empty text."""
        conn = get_connection(tmp_path / "db.sqlite")
        ensure_schema(conn)

        event: dict[str, Any] = {
            "type": "event_msg",
            "timestamp": "t0",
            "payload": {"type": "agent_message", "message": ""},
        }
        lines, _, _ = export_cli._render_event(
            event,
            [],
            conn=conn,
            file_id=None,
            prompt_id=None,
            session_file_path="/test.jsonl",
        )
        conn.close()

        # Should only have header, not expanded message
        TC.assertEqual(len(lines), 1)

    def test_render_event_response_message_non_list_content(
        self, tmp_path: Path
    ) -> None:
        """Should handle response_item with non-list content."""
        conn = get_connection(tmp_path / "db.sqlite")
        ensure_schema(conn)

        event: dict[str, Any] = {
            "type": "response_item",
            "timestamp": "t0",
            "payload": {"type": "message", "content": "not_a_list"},
        }
        lines, _, _ = export_cli._render_event(
            event,
            [],
            conn=conn,
            file_id=None,
            prompt_id=None,
            session_file_path="/test.jsonl",
        )
        conn.close()

        TC.assertEqual(len(lines), 1)

    def test_render_event_agent_message_text(self, tmp_path: Path) -> None:
        """Should render agent_message with text."""
        conn = get_connection(tmp_path / "db.sqlite")
        ensure_schema(conn)

        event: dict[str, Any] = {
            "type": "event_msg",
            "timestamp": "t0",
            "payload": {"type": "agent_message", "message": "Agent response here"},
        }
        lines, _, _ = export_cli._render_event(
            event,
            [],
            conn=conn,
            file_id=None,
            prompt_id=None,
            session_file_path="/test.jsonl",
        )
        conn.close()

        TC.assertTrue(any("Agent response here" in line for line in lines))

    def test_render_event_function_call_empty_arguments(self, tmp_path: Path) -> None:
        """Should handle function_call with empty arguments."""
        conn = get_connection(tmp_path / "db.sqlite")
        ensure_schema(conn)

        event: dict[str, Any] = {
            "type": "response_item",
            "timestamp": "t0",
            "payload": {"type": "function_call", "name": "test_fn", "arguments": ""},
        }
        lines, _, _ = export_cli._render_event(
            event,
            [],
            conn=conn,
            file_id=None,
            prompt_id=None,
            session_file_path="/test.jsonl",
        )
        conn.close()

        # Should have function name but not arguments
        TC.assertTrue(any("function: test_fn" in line for line in lines))

    def test_render_event_turn_context_with_cwd(self, tmp_path: Path) -> None:
        """Should render turn_context with cwd."""
        conn = get_connection(tmp_path / "db.sqlite")
        ensure_schema(conn)

        event: dict[str, Any] = {
            "type": "turn_context",
            "timestamp": "t0",
            "payload": {"cwd": "/home/user/project"},
        }
        lines, _, _ = export_cli._render_event(
            event,
            [],
            conn=conn,
            file_id=None,
            prompt_id=None,
            session_file_path="/test.jsonl",
        )
        conn.close()

        TC.assertTrue(any("cwd:" in line for line in lines))

    def test_render_event_turn_context_no_cwd(self, tmp_path: Path) -> None:
        """Should handle turn_context without cwd."""
        conn = get_connection(tmp_path / "db.sqlite")
        ensure_schema(conn)

        event: dict[str, Any] = {
            "type": "turn_context",
            "timestamp": "t0",
            "payload": {},
        }
        lines, _, _ = export_cli._render_event(
            event,
            [],
            conn=conn,
            file_id=None,
            prompt_id=None,
            session_file_path="/test.jsonl",
        )
        conn.close()

        TC.assertEqual(len(lines), 1)


def test_render_event_with_redaction_counts(tmp_path: Path) -> None:
    """Should handle rendering with redaction rules applied."""
    from src.services.redaction_rules import (  # pylint: disable=import-outside-toplevel
        RedactionRule,
        RuleOptions,
    )

    config = SessionsConfig(
        codex_root=tmp_path / "sessions",
        database=DatabaseConfig(sqlite_path=tmp_path / "db.sqlite"),
        outputs=OutputPaths(reports_dir=tmp_path),
    )
    conn = get_connection(config.database.sqlite_path)
    ensure_schema(conn)

    # Create session file
    session_root = tmp_path / "sessions" / "2025" / "01" / "01"
    session_root.mkdir(parents=True, exist_ok=True)
    events = [
        {
            "type": "event_msg",
            "timestamp": "t0",
            "payload": {"type": "user_message", "message": "test message"},
        },
    ]
    lines_text = "\n".join(json.dumps(event) for event in events)
    (session_root / "session.jsonl").write_text(lines_text + "\n", encoding="utf-8")

    # Create redaction rule object (even if no matches, tests the code path)
    rule = RedactionRule(
        id="test-rule",
        type="literal",
        pattern="nothing",
        options=RuleOptions(scope="global"),
    )

    lines, _ = export_cli._render_export(config, [rule], conn)
    conn.close()

    # Should produce output
    TC.assertGreater(len(lines), 0)
    TC.assertIn("Session file:", lines[0])
