"""Tests for export_session CLI module (AI-assisted by Codex GPT-5).

Covers core export functionality, argument parsing, redaction application,
output formatting, and edge cases for the export_session command-line interface.
"""

# pylint: disable=protected-access

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable

from pytest import MonkeyPatch

import cli.export_session as export_cli
from src.services.config import DatabaseConfig, OutputPaths, SessionsConfig
from src.services.database import ensure_schema, get_connection


TC = unittest.TestCase()


def _fake_config(tmp_path: Path) -> SessionsConfig:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    return SessionsConfig(
        sessions_root=tmp_path / "sessions",
        ingest_batch_size=10,
        database=DatabaseConfig(sqlite_path=tmp_path / "db.sqlite"),
        outputs=OutputPaths(reports_dir=reports_dir),
    )


def _connection_factory(db_path: Path) -> Callable[[DatabaseConfig], Any]:
    def _factory(_config: DatabaseConfig) -> Any:
        conn = get_connection(db_path)
        ensure_schema(conn)
        return conn

    return _factory


def _write_session(tmp_path: Path) -> None:
    session_root = tmp_path / "sessions" / "2025" / "01" / "01"
    session_root.mkdir(parents=True, exist_ok=True)
    events = [
        {
            "type": "event_msg",
            "timestamp": "t0",
            "payload": {"type": "user_message", "message": "secret prompt text"},
        },
        {
            "type": "event_msg",
            "timestamp": "t1",
            "payload": {"type": "agent_reasoning", "text": "shows secret content"},
        },
    ]
    lines = "\n".join(json.dumps(event) for event in events)
    (session_root / "session.jsonl").write_text(lines + "\n", encoding="utf-8")


def _write_rules(tmp_path: Path) -> Path:
    rules_file = tmp_path / "rules.json"
    rules = [
        {
            "id": "mask-secret",
            "type": "literal",
            "pattern": "secret",
            "scope": "global",
            "replacement": "<REDACTED>",
        }
    ]
    rules_file.write_text(json.dumps(rules), encoding="utf-8")
    return rules_file


def test_export_applies_redactions(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """Export should apply redactions by default."""

    _write_session(tmp_path)
    rules_file = _write_rules(tmp_path)
    config = _fake_config(tmp_path)
    conn_factory = _connection_factory(config.database.sqlite_path)

    monkeypatch.setattr(export_cli, "load_config", lambda: config)
    monkeypatch.setattr(export_cli, "get_connection_for_config", conn_factory)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prog",
            "--rules-file",
            str(rules_file),
        ],
    )

    export_cli.main()
    export_path = config.outputs.reports_dir / "export.txt"
    contents = export_path.read_text(encoding="utf-8")
    TC.assertIn("<REDACTED>", contents)
    TC.assertNotIn("secret prompt text", contents)
    TC.assertNotIn("secret content", contents)


class TestBuildParser:
    """Test argument parser construction."""

    def test_build_parser_has_output_option(self) -> None:
        """Parser should have --output option."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir) / "export.txt"
            parser = export_cli.build_parser()
            args = parser.parse_args(["--output", str(tmp_path)])
            TC.assertEqual(args.output, tmp_path)

    def test_build_parser_has_rules_file_option(self) -> None:
        """Parser should have --rules-file option."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir) / "rules.json"
            parser = export_cli.build_parser()
            args = parser.parse_args(["--rules-file", str(tmp_path)])
            TC.assertEqual(args.rules_file, tmp_path)

    def test_build_parser_has_no_redact_option(self) -> None:
        """Parser should have --no-redact option."""
        parser = export_cli.build_parser()
        args = parser.parse_args(["--no-redact"])
        TC.assertTrue(args.no_redact)

    def test_build_parser_has_allow_db_fallback_option(self) -> None:
        """Parser should have --allow-db-fallback option."""
        parser = export_cli.build_parser()
        args = parser.parse_args(["--allow-db-fallback"])
        TC.assertTrue(args.allow_db_fallback)


class TestScopeMatches:
    """Test scope matching logic."""

    def test_scope_matches_global_matches_all(self) -> None:
        """Global scope should match any context scope."""
        TC.assertTrue(export_cli._scope_matches("global", "prompt"))
        TC.assertTrue(export_cli._scope_matches("global", "action"))
        TC.assertTrue(export_cli._scope_matches("global", "anything"))

    def test_scope_matches_exact_match(self) -> None:
        """Same scopes should match for supported scopes."""
        TC.assertTrue(export_cli._scope_matches("prompt", "prompt"))
        TC.assertTrue(export_cli._scope_matches("field", "field"))

    def test_scope_matches_no_match(self) -> None:
        """Different scopes should not match."""
        TC.assertFalse(export_cli._scope_matches("prompt", "action"))
        TC.assertFalse(export_cli._scope_matches("action", "event"))
        TC.assertFalse(export_cli._scope_matches("event", "prompt"))


class TestLookupFileId:
    """Test file ID lookup."""

    def test_lookup_file_id_nonexistent(self, tmp_path: Path) -> None:
        """Lookup should return None for nonexistent file."""
        conn = get_connection(tmp_path / "db.sqlite")
        ensure_schema(conn)

        file_id = export_cli._lookup_file_id(conn, Path("/nonexistent/session.jsonl"))

        TC.assertIsNone(file_id)

    def test_lookup_file_id_with_file(self, tmp_path: Path) -> None:
        """Lookup should return ID for existing file."""
        conn = get_connection(tmp_path / "db.sqlite")
        ensure_schema(conn)

        session_path = Path("/test/session.jsonl")
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO files (path, ingested_at) VALUES (?, datetime('now'))",
            (str(session_path),),
        )
        conn.commit()
        expected_id = cursor.lastrowid

        file_id = export_cli._lookup_file_id(conn, session_path)

        TC.assertEqual(file_id, expected_id)


class TestLookupPromptId:
    """Test prompt ID lookup."""

    def test_lookup_prompt_id_nonexistent(self, tmp_path: Path) -> None:
        """Lookup should return None for nonexistent prompt."""
        conn = get_connection(tmp_path / "db.sqlite")
        ensure_schema(conn)

        prompt_id = export_cli._lookup_prompt_id(conn, None, 1)

        TC.assertIsNone(prompt_id)

    def test_lookup_prompt_id_with_file_and_index(self, tmp_path: Path) -> None:
        """Lookup should return ID for existing prompt."""
        conn = get_connection(tmp_path / "db.sqlite")
        ensure_schema(conn)

        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO files (path, ingested_at) VALUES (?, datetime('now'))",
            ("/test/session.jsonl",),
        )
        file_id = cursor.lastrowid

        cursor.execute(
            "INSERT INTO prompts (file_id, prompt_index) VALUES (?, ?)",
            (file_id, 1),
        )
        expected_id = cursor.lastrowid
        conn.commit()

        prompt_id = export_cli._lookup_prompt_id(conn, file_id, 1)

        TC.assertEqual(prompt_id, expected_id)


class TestIndent:
    """Test indentation helper."""

    def test_indent_single_line(self) -> None:
        """Should add prefix to text."""
        result = export_cli._indent("hello", ">> ")
        TC.assertEqual(result, ">> hello")

    def test_indent_with_different_prefix(self) -> None:
        """Should use provided prefix."""
        result = export_cli._indent("text", "***")
        TC.assertEqual(result, "***text")

    def test_indent_empty_string(self) -> None:
        """Should handle empty string."""
        result = export_cli._indent("", "  ")
        TC.assertEqual(result, "  ")


class TestWriteOutput:
    """Test output writing."""

    def test_write_output_creates_file(self, tmp_path: Path) -> None:
        """Should create output file."""
        output_path = tmp_path / "output.txt"
        lines = ["line 1", "line 2", "line 3"]

        export_cli._write_output(output_path, lines)

        TC.assertTrue(output_path.exists())
        contents = output_path.read_text(encoding="utf-8")
        TC.assertIn("line 1", contents)
        TC.assertIn("line 2", contents)
        TC.assertIn("line 3", contents)

    def test_write_output_creates_parent_directories(self, tmp_path: Path) -> None:
        """Should create parent directories if needed."""
        output_path = tmp_path / "subdir" / "deep" / "output.txt"
        lines = ["test line"]

        export_cli._write_output(output_path, lines)

        TC.assertTrue(output_path.exists())
        TC.assertTrue(output_path.parent.exists())

    def test_write_output_empty_lines(self, tmp_path: Path) -> None:
        """Should handle empty lines list."""
        output_path = tmp_path / "output.txt"
        lines: list[str] = []

        export_cli._write_output(output_path, lines)

        TC.assertTrue(output_path.exists())


class TestApplyAllRedactions:
    # pylint: disable=too-few-public-methods
    # Justification: Single-test class for organizing related redaction application
    # tests without bloating the module namespace.
    """Test redaction application."""

    def test_apply_all_redactions_no_rules(self, tmp_path: Path) -> None:
        """Should return unchanged text with no rules."""
        conn = get_connection(tmp_path / "db.sqlite")
        ensure_schema(conn)

        text, counts, manual = export_cli._apply_all_redactions(
            "secret password here",
            rules=[],
            conn=conn,
            file_id=None,
            prompt_id=None,
            session_file_path="/test.jsonl",
            scope="global",
            field_path="test",
        )

        TC.assertEqual(text, "secret password here")
        TC.assertEqual(len(counts), 0)
        TC.assertEqual(len(manual), 0)


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
            sessions_root=tmp_path / "sessions",
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
