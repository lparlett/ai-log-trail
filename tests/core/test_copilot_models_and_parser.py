"""Tests for CoPilot session models and parser (AI-assisted by Claude Haiku 4.5).

Tests the CoPilot agent models and parser functionality including:
- Session structure parsing
- Request/response parsing
- Variable context handling
- URI and file reference parsing
- Error handling and validation
"""

from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path
from typing import Any

import pytest

from src.agents.copilot import (
    CoPilotParseError,
    discover_copilot_sessions,
    parse_copilot_session,
    parse_copilot_session_from_file,
)
from src.agents.copilot.models import (
    Variable,
    parse_message,
    parse_uri,
)
from src.agents.copilot.parser import (
    parse_response_part,
    parse_variable_data,
)


class TestURIParsing(unittest.TestCase):
    """Test URI parsing from session data."""

    def test_parse_uri_with_file_scheme(self) -> None:
        """Should parse file:// URIs correctly."""
        uri_data: dict[str, Any] = {
            "$mid": 1,
            "path": "/c:/Users/test/file.py",
            "scheme": "file",
            "fsPath": "c:\\Users\\test\\file.py",
        }
        uri = parse_uri(uri_data)

        self.assertIsNotNone(uri)
        if uri is None:  # pragma: no cover
            return
        self.assertEqual(uri.scheme, "file")
        self.assertEqual(uri.path, "/c:/Users/test/file.py")
        self.assertEqual(uri.fsPath, "c:\\Users\\test\\file.py")

    def test_parse_uri_with_https_scheme(self) -> None:
        """Should parse https:// URIs (e.g., avatar icons)."""
        uri_data: dict[str, Any] = {
            "$mid": 1,
            "path": "/u/93846508",
            "scheme": "https",
            "authority": "avatars.githubusercontent.com",
            "query": "v=4",
        }
        uri = parse_uri(uri_data)

        self.assertIsNotNone(uri)
        if uri is None:  # pragma: no cover
            return
        self.assertEqual(uri.scheme, "https")
        self.assertEqual(uri.authority, "avatars.githubusercontent.com")
        self.assertEqual(uri.query, "v=4")

    def test_parse_uri_with_none_returns_none(self) -> None:
        """Should return None for non-dict input."""
        self.assertIsNone(parse_uri(None))
        self.assertIsNone(parse_uri("invalid"))
        self.assertIsNone(parse_uri([]))

    def test_parse_uri_with_missing_fields(self) -> None:
        """Should use defaults for missing URI fields."""
        uri_data: dict[str, Any] = {"path": "/test"}
        uri = parse_uri(uri_data)

        self.assertIsNotNone(uri)
        if uri is None:  # pragma: no cover
            return
        self.assertEqual(uri.path, "/test")
        self.assertEqual(uri.scheme, "file")
        self.assertEqual(uri.mid, 1)


class TestMessageParsing(unittest.TestCase):
    """Test message parsing from session data."""

    def test_parse_message_with_text_parts(self) -> None:
        """Should parse messages with text parts."""
        message_data: dict[str, Any] = {
            "parts": [
                {
                    "text": "This is a question",
                    "kind": "text",
                    "range": {"start": 0, "endExclusive": 18},
                }
            ],
            "text": "This is a question",
        }
        message = parse_message(message_data)

        self.assertEqual(message.text, "This is a question")
        self.assertEqual(len(message.parts), 1)
        self.assertEqual(message.parts[0].text, "This is a question")
        self.assertEqual(message.parts[0].kind, "text")
        self.assertIsNotNone(message.parts[0].range)
        if message.parts[0].range is None:  # pragma: no cover
            return
        self.assertEqual(message.parts[0].range.start, 0)
        self.assertEqual(message.parts[0].range.endExclusive, 18)

    def test_parse_message_with_editor_range(self) -> None:
        """Should parse editor range information in message parts."""
        message_data: dict[str, Any] = {
            "parts": [
                {
                    "text": "Code snippet",
                    "kind": "text",
                    "editorRange": {
                        "startLineNumber": 10,
                        "startColumn": 5,
                        "endLineNumber": 15,
                        "endColumn": 20,
                    },
                }
            ],
            "text": "Code snippet",
        }
        message = parse_message(message_data)

        self.assertEqual(len(message.parts), 1)
        part = message.parts[0]
        self.assertIsNotNone(part.editorRange)
        if part.editorRange is None:  # pragma: no cover
            return
        self.assertEqual(part.editorRange.startLineNumber, 10)
        self.assertEqual(part.editorRange.endLineNumber, 15)

    def test_parse_empty_message(self) -> None:
        """Should handle empty messages gracefully."""
        message_data: dict[str, Any] = {"parts": [], "text": ""}
        message = parse_message(message_data)

        self.assertEqual(message.text, "")
        self.assertEqual(len(message.parts), 0)

    def test_parse_message_without_parts(self) -> None:
        """Should handle messages without parts field."""
        message_data: dict[str, Any] = {"text": "Just text"}
        message = parse_message(message_data)

        self.assertEqual(message.text, "Just text")
        self.assertEqual(len(message.parts), 0)


class TestVariableDataParsing(unittest.TestCase):
    """Test variable context parsing."""

    def test_parse_variable_file_reference(self) -> None:
        """Should parse file variable references."""
        var = Variable(
            kind="file",
            id="vscode.implicit.selection",
            name="file:test.py",
            value={
                "uri": {"$mid": 1, "path": "/c:/Users/test/file.py", "scheme": "file"}
            },
            modelDescription="User's active selection",
        )

        self.assertEqual(var.kind, "file")
        self.assertEqual(var.name, "file:test.py")
        self.assertEqual(var.modelDescription, "User's active selection")

    def test_parse_multiple_variables(self) -> None:
        """Should parse multiple variables in context."""
        var_data: dict[str, Any] = {
            "variables": [
                {
                    "kind": "file",
                    "id": "id1",
                    "name": "file1",
                    "value": {},
                },
                {
                    "kind": "workspace",
                    "id": "id2",
                    "name": "workspace",
                    "value": {},
                },
            ]
        }

        var_context = parse_variable_data(var_data)

        self.assertEqual(len(var_context.variables), 2)
        self.assertEqual(var_context.variables[0].kind, "file")
        self.assertEqual(var_context.variables[1].kind, "workspace")


class TestResponsePartParsing(unittest.TestCase):
    """Test response part parsing."""

    def test_parse_text_response_part(self) -> None:
        """Should parse text response parts."""
        response_data: dict[str, Any] = {
            "kind": "text",
            "value": "Here is my response",
            "supportThemeIcons": False,
            "supportHtml": False,
        }

        part = parse_response_part(response_data)

        self.assertEqual(part.kind, "text")
        self.assertEqual(part.value, "Here is my response")
        self.assertEqual(part.supportHtml, False)

    def test_parse_tool_invocation_response(self) -> None:
        """Should parse tool invocation response parts."""
        response_data: dict[str, Any] = {
            "kind": "toolInvocationSerialized",
            "toolName": "copilot_readFile",
            "toolCallId": "abc123",
            "toolId": "copilot_readFile",
            "isComplete": True,
            "isConfirmed": {"type": 1},
        }

        part = parse_response_part(response_data)

        self.assertEqual(part.kind, "toolInvocationSerialized")
        self.assertEqual(part.toolName, "copilot_readFile")
        self.assertEqual(part.isComplete, True)


class TestSessionParsing(unittest.TestCase):
    """Test full session parsing."""

    def test_parse_minimal_session(self) -> None:
        """Should parse a minimal valid session."""
        session_data: dict[str, Any] = {
            "version": 3,
            "requesterUsername": "testuser",
            "responderUsername": "GitHub Copilot",
            "requests": [],
        }

        session = parse_copilot_session(session_data)

        self.assertEqual(session.version, 3)
        self.assertEqual(session.requesterUsername, "testuser")
        self.assertEqual(session.responderUsername, "GitHub Copilot")
        self.assertEqual(len(session.requests), 0)

    def test_parse_session_with_requests(self) -> None:
        """Should parse sessions with multiple requests."""
        session_data: dict[str, Any] = {
            "version": 3,
            "requesterUsername": "user",
            "responderUsername": "GitHub Copilot",
            "requests": [
                {
                    "requestId": "req_1",
                    "message": {"parts": [], "text": "Question 1"},
                    "variableData": {"variables": []},
                    "response": [],
                },
                {
                    "requestId": "req_2",
                    "message": {"parts": [], "text": "Question 2"},
                    "variableData": {"variables": []},
                    "response": [],
                },
            ],
        }

        session = parse_copilot_session(session_data)

        self.assertEqual(len(session.requests), 2)
        self.assertEqual(session.requests[0].requestId, "req_1")
        self.assertEqual(session.requests[1].requestId, "req_2")

    def test_parse_session_invalid_type_raises_error(self) -> None:
        """Should raise CoPilotParseError for non-dict input."""
        with self.assertRaises(CoPilotParseError):
            parse_copilot_session([])  # type: ignore

        with self.assertRaises(CoPilotParseError):
            parse_copilot_session("invalid")  # type: ignore


class TestSessionFileDiscovery(unittest.TestCase):
    """Test discovery of CoPilot session files."""

    def test_discover_sessions_in_directory(self) -> None:
        """Should find session JSON files in workspaceStorage structure."""
        tmp_path = Path.cwd() / ".test_copilot_sessions"
        try:
            # Create a realistic workspaceStorage structure
            session_dir = tmp_path / "workspace1" / "chatSessions"
            session_dir.mkdir(parents=True, exist_ok=True)

            session_file1 = session_dir / "session_1.json"
            session_file1.write_text('{"version": 3, "requests": []}')

            session_file2 = session_dir / "session_2.json"
            session_file2.write_text('{"version": 3, "requests": []}')

            # Also test with other workspaces
            session_dir2 = tmp_path / "workspace2" / "chatSessions"
            session_dir2.mkdir(parents=True, exist_ok=True)
            session_file3 = session_dir2 / "session_3.json"
            session_file3.write_text('{"version": 3, "requests": []}')

            sessions = discover_copilot_sessions(tmp_path)

            self.assertEqual(len(sessions), 3)
            self.assertTrue(all(f.suffix == ".json" for f in sessions))
            self.assertTrue(all("chatSessions" in str(f) for f in sessions))
        finally:
            # Cleanup
            if tmp_path.exists():
                shutil.rmtree(tmp_path)

    def test_discover_sessions_empty_directory(self) -> None:
        """Should return empty list for directory with no sessions."""
        tmp_path = Path.cwd() / ".test_copilot_empty"
        try:
            tmp_path.mkdir(exist_ok=True)
            sessions = discover_copilot_sessions(tmp_path)
            self.assertEqual(len(sessions), 0)
        finally:
            if tmp_path.exists():
                shutil.rmtree(tmp_path)

    def test_discover_sessions_missing_directory(self) -> None:
        """Should handle missing directory gracefully."""
        sessions = discover_copilot_sessions(Path("/nonexistent/path"))
        self.assertEqual(len(sessions), 0)


class TestSessionFileParsing(unittest.TestCase):
    """Test parsing session files from disk."""

    def test_parse_session_from_file(self) -> None:
        """Should load and parse a session file."""
        tmp_path = Path.cwd() / ".test_copilot_parse"
        try:
            tmp_path.mkdir(exist_ok=True)
            session_data: dict[str, Any] = {
                "version": 3,
                "requesterUsername": "user",
                "responderUsername": "GitHub Copilot",
                "requests": [
                    {
                        "requestId": "req_1",
                        "message": {"parts": [], "text": "Test question"},
                        "variableData": {"variables": []},
                        "response": [{"kind": "text", "value": "Test response"}],
                    }
                ],
            }

            session_file = tmp_path / "session.json"
            session_file.write_text(json.dumps(session_data))

            session = parse_copilot_session_from_file(session_file)

            self.assertEqual(session.version, 3)
            self.assertEqual(len(session.requests), 1)
            self.assertEqual(session.requests[0].message.text, "Test question")
        finally:
            if tmp_path.exists():
                shutil.rmtree(tmp_path)

    def test_parse_session_from_file_not_found(self) -> None:
        """Should raise error for missing file."""
        tmp_path = Path.cwd() / ".test_copilot_notfound"
        tmp_path.mkdir(exist_ok=True)
        try:
            missing_file = tmp_path / "missing.json"
            with self.assertRaises(CoPilotParseError):
                parse_copilot_session_from_file(missing_file)
        finally:
            if tmp_path.exists():
                shutil.rmtree(tmp_path)

    def test_parse_session_from_file_invalid_json(self) -> None:
        """Should raise error for invalid JSON."""
        tmp_path = Path.cwd() / ".test_copilot_invalid"
        try:
            tmp_path.mkdir(exist_ok=True)
            bad_file = tmp_path / "bad.json"
            bad_file.write_text("{invalid json}")

            with self.assertRaises(CoPilotParseError):
                parse_copilot_session_from_file(bad_file)
        finally:
            if tmp_path.exists():
                shutil.rmtree(tmp_path)

    def test_parse_session_from_file_permission_denied(self) -> None:
        """Should raise error for inaccessible file (skipped on Windows)."""
        if sys.platform == "win32":
            pytest.skip("File permission tests not reliable on Windows")
            return  # type: ignore[unreachable]

        tmp_path = Path.cwd() / ".test_copilot_perm"  # type: ignore[unreachable]
        try:
            tmp_path.mkdir(exist_ok=True)
            session_file = tmp_path / "session.json"
            session_file.write_text('{"version": 3}')

            # Make file unreadable
            session_file.chmod(0o000)

            try:
                with self.assertRaises(CoPilotParseError):
                    parse_copilot_session_from_file(session_file)
            finally:
                # Restore permissions for cleanup
                session_file.chmod(0o644)
        finally:
            if tmp_path.exists():
                shutil.rmtree(tmp_path)
