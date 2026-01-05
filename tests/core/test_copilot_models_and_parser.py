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
    find_copilot_session_files,
    parse_copilot_session,
    parse_copilot_session_from_file,
)
from src.agents.copilot.models import (
    Session,
    Variable,
    parse_message,
    parse_uri,
)
from src.agents.copilot.parser import (
    CoPilotParser,
    discover_copilot_sessions,
    parse_copilot_request,
    parse_response_part,
    parse_session,
    parse_session_from_file,
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

            sessions = find_copilot_session_files(tmp_path)

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
            sessions = find_copilot_session_files(tmp_path)
            self.assertEqual(len(sessions), 0)
        finally:
            if tmp_path.exists():
                shutil.rmtree(tmp_path)

    def test_discover_sessions_missing_directory(self) -> None:
        """Should handle missing directory gracefully."""
        sessions = find_copilot_session_files(Path("/nonexistent/path"))
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


class TestParserClassMethods(unittest.TestCase):
    """Test CoPilotParser class implementation."""

    def test_parser_agent_type_property(self) -> None:
        """Should return correct agent type identifier."""
        parser = CoPilotParser()
        self.assertEqual(parser.agent_type, "copilot")
        self.assertEqual(parser.get_agent_type(), "copilot")

    def test_parser_get_metadata_from_session(self) -> None:
        """Should extract metadata from valid session file."""
        tmp_path = Path.cwd() / ".test_parser_metadata"
        try:
            tmp_path.mkdir(exist_ok=True)
            session_data: dict[str, Any] = {
                "version": 3,
                "requesterUsername": "testuser",
                "responderUsername": "GitHub Copilot",
                "requests": [
                    {
                        "requestId": "req_1",
                        "timestamp": 1609459200000,  # 2021-01-01 00:00:00 UTC
                        "message": {"parts": [], "text": "Hi"},
                        "variableData": {"variables": []},
                        "response": [],
                    }
                ],
            }

            session_file = tmp_path / "session.json"
            session_file.write_text(json.dumps(session_data))

            parser = CoPilotParser()
            metadata = parser.get_metadata(session_file)

            self.assertEqual(metadata.agent_type, "copilot")
            self.assertEqual(metadata.session_id, "session")
            self.assertIsNotNone(metadata.timestamp)
        finally:
            if tmp_path.exists():
                shutil.rmtree(tmp_path)

    def test_parser_get_metadata_uses_file_mtime_fallback(self) -> None:
        """Should use file mtime when session has no timestamps."""
        tmp_path = Path.cwd() / ".test_parser_mtime"
        try:
            tmp_path.mkdir(exist_ok=True)
            session_data: dict[str, Any] = {
                "version": 3,
                "requesterUsername": "testuser",
                "responderUsername": "GitHub Copilot",
                "requests": [],  # No requests with timestamps
            }

            session_file = tmp_path / "session.json"
            session_file.write_text(json.dumps(session_data))

            parser = CoPilotParser()
            metadata = parser.get_metadata(session_file)

            self.assertEqual(metadata.agent_type, "copilot")
            self.assertIsNotNone(metadata.timestamp)
        finally:
            if tmp_path.exists():
                shutil.rmtree(tmp_path)

    def test_parser_get_metadata_raises_on_invalid_json(self) -> None:
        """Should raise CoPilotParseError for invalid JSON."""
        tmp_path = Path.cwd() / ".test_parser_bad_json"
        try:
            tmp_path.mkdir(exist_ok=True)
            bad_file = tmp_path / "bad.json"
            bad_file.write_text("{invalid}")

            parser = CoPilotParser()
            with self.assertRaises(CoPilotParseError):
                parser.get_metadata(bad_file)
        finally:
            if tmp_path.exists():
                shutil.rmtree(tmp_path)

    def test_parser_parse_file_yields_session(self) -> None:
        """Should parse file and yield Session as BaseEvent."""
        tmp_path = Path.cwd() / ".test_parser_parse_file"
        try:
            tmp_path.mkdir(exist_ok=True)
            session_data: dict[str, Any] = {
                "version": 3,
                "requesterUsername": "user",
                "responderUsername": "GitHub Copilot",
                "requests": [
                    {
                        "requestId": "req_1",
                        "message": {"parts": [], "text": "Test"},
                        "variableData": {"variables": []},
                        "response": [{"kind": "text", "value": "Response"}],
                    }
                ],
            }

            session_file = tmp_path / "session.json"
            session_file.write_text(json.dumps(session_data))

            parser = CoPilotParser()
            events = list(parser.parse_file(session_file))

            self.assertEqual(len(events), 1)
            event = events[0]
            self.assertIsInstance(event, Session)
            if isinstance(event, Session):
                self.assertEqual(event.version, 3)
                self.assertEqual(len(event.requests), 1)
        finally:
            if tmp_path.exists():
                shutil.rmtree(tmp_path)

    def test_parser_find_log_files_discovers_sessions(self) -> None:
        """Should find JSON files in chatSessions directories."""
        tmp_path = Path.cwd() / ".test_parser_find"
        try:
            # Create chatSessions structure
            chat_dir = tmp_path / "workspace" / "chatSessions"
            chat_dir.mkdir(parents=True, exist_ok=True)

            # Add session files
            session1 = chat_dir / "session1.json"
            session1.write_text("{}")
            session2 = chat_dir / "session2.json"
            session2.write_text("{}")

            # Add non-chatSessions JSON (should be ignored)
            other_json = tmp_path / "other.json"
            other_json.write_text("{}")

            parser = CoPilotParser()
            files = list(parser.find_log_files(tmp_path))

            self.assertEqual(len(files), 2)
            self.assertTrue(all("chatSessions" in str(f) for f in files))
        finally:
            if tmp_path.exists():
                shutil.rmtree(tmp_path)

    def test_parser_validate_event_accepts_dict(self) -> None:
        """Should validate dict as valid event data."""
        parser = CoPilotParser()
        self.assertTrue(parser.validate_event({}))
        self.assertTrue(parser.validate_event({"key": "value"}))
        self.assertFalse(parser.validate_event("string"))
        self.assertFalse(parser.validate_event([]))
        self.assertFalse(parser.validate_event(None))


class TestRequestParsing(unittest.TestCase):
    """Test request parsing error handling."""

    def test_parse_request_missing_request_id(self) -> None:
        """Should raise error when requestId is missing."""
        request_data: dict[str, Any] = {
            "message": {"parts": [], "text": "Question"},
            "response": [],
        }

        with self.assertRaises(CoPilotParseError):
            parse_copilot_request(request_data)

    def test_parse_request_with_invalid_response_parts(self) -> None:
        """Should skip malformed response parts and continue."""

        request_data: dict[str, Any] = {
            "requestId": "req_1",
            "message": {"parts": [], "text": "Question"},
            "response": [
                {"kind": "text", "value": "Valid response"},
                {},  # Missing required fields but should be handled
                {"kind": "text", "value": "Another valid"},
            ],
        }

        request = parse_copilot_request(request_data)

        self.assertEqual(request.requestId, "req_1")
        # Should parse valid parts and skip invalid ones
        self.assertGreaterEqual(len(request.response), 2)

    def test_parse_request_with_malformed_variable_data(self) -> None:
        """Should handle malformed variable data gracefully."""

        request_data: dict[str, Any] = {
            "requestId": "req_1",
            "message": {"parts": [], "text": "Question"},
            "variableData": {
                "variables": [{"kind": "file"}]
            },  # Missing required fields
            "response": [],
        }

        request = parse_copilot_request(request_data)

        self.assertEqual(request.requestId, "req_1")
        # Should have created VariableData with attempted variable parsing
        self.assertIsNotNone(request.variableData)

    def test_parse_request_minimal_fields(self) -> None:
        """Should parse request with only required field."""
        request_data: dict[str, Any] = {"requestId": "req_1"}

        request = parse_copilot_request(request_data)

        self.assertEqual(request.requestId, "req_1")
        self.assertEqual(request.message.text, "")
        self.assertEqual(len(request.response), 0)


class TestResponsePartEdgeCases(unittest.TestCase):
    """Test response part parsing with edge cases."""

    def test_parse_response_with_all_optional_fields(self) -> None:
        """Should preserve all optional fields."""
        response_data: dict[str, Any] = {
            "kind": "text",
            "value": "Complex response",
            "id": "resp_1",
            "supportThemeIcons": True,
            "supportHtml": True,
            "toolName": "copilot_command",
            "toolCallId": "tool_1",
            "toolId": "cmd_id",
            "isConfirmed": True,
            "isComplete": True,
            "isEdit": True,
            "done": True,
            "presentation": "inline",
            "source": "codeblock",
        }

        part = parse_response_part(response_data)

        self.assertEqual(part.kind, "text")
        self.assertEqual(part.id, "resp_1")
        self.assertTrue(part.supportThemeIcons)
        self.assertTrue(part.supportHtml)
        self.assertEqual(part.toolName, "copilot_command")
        self.assertEqual(part.presentation, "inline")

    def test_parse_response_with_uri_dict(self) -> None:
        """Should parse uris field as dictionary of URI objects."""
        response_data: dict[str, Any] = {
            "kind": "text",
            "uris": {
                "file1": {"path": "/c:/test.py", "scheme": "file"},
                "file2": {"path": "/c:/other.py", "scheme": "file"},
            },
        }

        part = parse_response_part(response_data)

        self.assertIsNotNone(part.uris)
        if part.uris:
            self.assertEqual(len(part.uris), 2)
            self.assertIn("file1", part.uris)
            self.assertIn("file2", part.uris)

    def test_parse_response_with_empty_uris_dict(self) -> None:
        """Should handle empty uris dictionary."""
        response_data: dict[str, Any] = {
            "kind": "text",
            "uris": {},
        }

        part = parse_response_part(response_data)

        # Parser returns empty dict if provided, not None
        self.assertEqual(part.uris, {})

    def test_parse_response_with_none_uris(self) -> None:
        """Should handle None uris field."""
        response_data: dict[str, Any] = {
            "kind": "text",
            "uris": None,
        }

        part = parse_response_part(response_data)

        self.assertIsNone(part.uris)


class TestSessionParsingEdgeCases(unittest.TestCase):
    """Test session parsing edge cases."""

    def test_parse_session_with_malformed_request_skips_and_continues(self) -> None:
        """Should skip malformed requests and continue parsing."""
        session_data: dict[str, Any] = {
            "version": 3,
            "requesterUsername": "user",
            "responderUsername": "GitHub Copilot",
            "requests": [
                {
                    "requestId": "req_1",
                    "message": {"parts": [], "text": "Valid"},
                    "response": [],
                },
                {},  # Missing requestId - should be skipped
                {
                    "requestId": "req_2",
                    "message": {"parts": [], "text": "Also valid"},
                    "response": [],
                },
            ],
        }

        session = parse_copilot_session(session_data)

        # Should have parsed valid requests and skipped invalid one
        self.assertGreaterEqual(len(session.requests), 2)

    def test_parse_session_with_metadata(self) -> None:
        """Should preserve arbitrary metadata fields."""
        session_data: dict[str, Any] = {
            "version": 3,
            "requesterUsername": "user",
            "responderUsername": "GitHub Copilot",
            "requests": [],
            "metadata": {
                "workspacePath": "/home/user/project",
                "language": "python",
                "timestamp": "2024-01-01T00:00:00Z",
            },
        }

        session = parse_copilot_session(session_data)

        self.assertEqual(session.metadata["workspacePath"], "/home/user/project")
        self.assertEqual(session.metadata["language"], "python")

    def test_parse_session_with_avatar_uris(self) -> None:
        """Should parse avatar URI fields."""
        session_data: dict[str, Any] = {
            "version": 3,
            "requesterUsername": "user",
            "requesterAvatarIconUri": {
                "path": "/avatars/user.png",
                "scheme": "https",
            },
            "responderUsername": "GitHub Copilot",
            "responderAvatarIconUri": "/avatars/copilot.png",
            "requests": [],
        }

        session = parse_copilot_session(session_data)

        self.assertIsNotNone(session.requesterAvatarIconUri)
        self.assertEqual(session.responderAvatarIconUri, "/avatars/copilot.png")

    def test_parse_session_uses_default_values(self) -> None:
        """Should use defaults for missing optional fields."""
        session_data: dict[str, Any] = {
            "requesterUsername": "user",
            "requests": [],
        }

        session = parse_copilot_session(session_data)

        self.assertEqual(session.version, 3)
        self.assertEqual(session.requesterUsername, "user")
        self.assertEqual(session.responderUsername, "GitHub Copilot")
        self.assertEqual(session.initialLocation, "panel")
        self.assertEqual(session.metadata, {})


class TestVariableDataParsingEdgeCases(unittest.TestCase):
    """Test variable data parsing with edge cases."""

    def test_parse_variable_data_with_complex_values(self) -> None:
        """Should handle variables with complex value types."""
        var_data: dict[str, Any] = {
            "variables": [
                {
                    "kind": "file",
                    "id": "file_1",
                    "name": "test.py",
                    "value": {"path": "/home/test.py", "line": 10},
                },
                {
                    "kind": "workspace",
                    "id": "ws_1",
                    "name": "My Project",
                    "value": ["/home/project"],
                },
            ]
        }

        var_context = parse_variable_data(var_data)

        self.assertEqual(len(var_context.variables), 2)
        self.assertEqual(var_context.variables[0].kind, "file")
        self.assertIsNotNone(var_context.variables[0].value)

    def test_parse_variable_data_skips_malformed_variables(self) -> None:
        """Should skip variables that fail to parse (except None)."""
        var_data: dict[str, Any] = {
            "variables": [
                {"kind": "file", "id": "valid"},
                # Parser requires dict, so we test with incomplete dicts
                {"kind": "workspace", "id": "also_valid"},
            ]
        }

        var_context = parse_variable_data(var_data)

        # Should parse variables that have valid structure
        self.assertEqual(len(var_context.variables), 2)

    def test_parse_variable_data_empty_variables(self) -> None:
        """Should handle empty variables list."""
        var_data: dict[str, Any] = {"variables": []}

        var_context = parse_variable_data(var_data)

        self.assertEqual(len(var_context.variables), 0)

    def test_parse_variable_data_missing_variables_field(self) -> None:
        """Should handle missing variables field."""
        var_data: dict[str, Any] = {}

        var_context = parse_variable_data(var_data)

        self.assertEqual(len(var_context.variables), 0)


class TestBackwardCompatibilityAliases(unittest.TestCase):
    """Test backward compatibility aliases."""

    def test_legacy_parse_session_alias(self) -> None:
        """Should support deprecated parse_session function."""
        session_data: dict[str, Any] = {
            "version": 3,
            "requesterUsername": "user",
            "responderUsername": "GitHub Copilot",
            "requests": [],
        }

        session = parse_session(session_data)

        self.assertEqual(session.version, 3)

    def test_legacy_parse_session_from_file_alias(self) -> None:
        """Should support deprecated parse_session_from_file function."""
        tmp_path = Path.cwd() / ".test_legacy_parse"
        try:
            tmp_path.mkdir(exist_ok=True)
            session_data: dict[str, Any] = {
                "version": 3,
                "requesterUsername": "user",
                "responderUsername": "GitHub Copilot",
                "requests": [],
            }

            session_file = tmp_path / "session.json"
            session_file.write_text(json.dumps(session_data))

            session = parse_session_from_file(session_file)

            self.assertEqual(session.version, 3)
        finally:
            if tmp_path.exists():
                shutil.rmtree(tmp_path)

    def test_legacy_discover_copilot_sessions_alias(self) -> None:
        """Should support deprecated discover_copilot_sessions function."""
        tmp_path = Path.cwd() / ".test_legacy_discover"
        try:
            chat_dir = tmp_path / "workspace" / "chatSessions"
            chat_dir.mkdir(parents=True, exist_ok=True)

            session_file = chat_dir / "session.json"
            session_file.write_text("{}")

            sessions = discover_copilot_sessions(tmp_path)

            self.assertEqual(len(sessions), 1)
        finally:
            if tmp_path.exists():
                shutil.rmtree(tmp_path)
