"""Tests for src/services/ingest_copilot.py (AI-assisted).

Tests the CoPilot-specific ingest functionality including:
- Session metadata extraction
- Request/response parsing and storage
- Tool invocation handling
- Sanitization integration
- Error handling and recovery
"""

from __future__ import annotations

import json
from pathlib import Path

from src.agents.copilot.models import (
    Session,
    Request,
    Message,
    Variable,
    VariableData,
    ResponsePart,
)
from src.services.ingest_copilot import (
    ingest_copilot_session_file,
    ingest_copilot_sessions_from_root,
    build_copilot_session_metadata,
    build_copilot_request_user_input,
    build_copilot_request_context,
    build_copilot_response_context,
)
from src.services.database import ensure_schema, get_connection


# Test metadata extraction from CoPilot sessions
def test_build_session_metadata() -> None:
    """Should extract required session metadata."""
    session = Session(
        version=3,
        requesterUsername="testuser",
        requesterAvatarIconUri=None,
        responderUsername="GitHub Copilot",
        responderAvatarIconUri=None,
        initialLocation="panel",
        requests=[],
        metadata={},
    )

    metadata = build_copilot_session_metadata(session)

    if metadata["requesterUsername"] != "testuser":
        raise AssertionError(
            f"Expected requesterUsername='testuser', got {metadata['requesterUsername']}"
        )
    if metadata["responderUsername"] != "GitHub Copilot":
        raise AssertionError(
            f"Expected responderUsername='GitHub Copilot', got {metadata['responderUsername']}"
        )
    if metadata["initialLocation"] != "panel":
        raise AssertionError(
            f"Expected initialLocation='panel', got {metadata['initialLocation']}"
        )
    if metadata["version"] != 3:
        raise AssertionError(f"Expected version=3, got {metadata['version']}")


def test_build_session_metadata_with_custom_location() -> None:
    """Should preserve custom initialLocation."""
    session = Session(
        version=3,
        requesterUsername="user",
        requesterAvatarIconUri=None,
        responderUsername="GitHub Copilot",
        responderAvatarIconUri=None,
        initialLocation="editor",
        requests=[],
        metadata={},
    )

    metadata = build_copilot_session_metadata(session)

    if metadata["initialLocation"] != "editor":
        raise AssertionError(
            f"Expected initialLocation='editor', got {metadata['initialLocation']}"
        )


# Test request data extraction
def test_build_request_user_input_simple() -> None:
    """Should build user input from message parts."""
    message = Message(
        parts=[],
        text="Hello world",
    )
    request = Request(
        requestId="req_1",
        message=message,
        variableData=VariableData(variables=[]),
        response=[],
        timestamp=None,
    )

    user_input = build_copilot_request_user_input(request)

    if not isinstance(user_input, dict):
        raise AssertionError(f"Expected dict, got {type(user_input)}")
    if "parts" not in user_input:
        raise AssertionError("Expected 'parts' key in user_input")


def test_build_request_context_with_variables() -> None:
    """Should extract variable context from request."""
    var1 = Variable(
        kind="file",
        id="f1",
        name="test.py",
        value=None,
        modelDescription="Test file",
    )
    var2 = Variable(
        kind="workspace",
        id="ws1",
        name="MyProject",
        value=None,
        modelDescription="Project root",
    )
    var_data = VariableData(variables=[var1, var2])
    request = Request(
        requestId="req_1",
        message=Message(parts=[], text="test"),
        variableData=var_data,
        response=[],
        timestamp=None,
    )

    context = build_copilot_request_context(request)

    if "variableData" not in context:
        raise AssertionError("Expected 'variableData' key in context")
    if "variables" not in context["variableData"]:
        raise AssertionError("Expected 'variables' key in variableData")
    if len(context["variableData"]["variables"]) != 2:
        raise AssertionError(
            f"Expected 2 variables, got {len(context['variableData']['variables'])}"
        )


def test_build_request_context_preserves_variable_fields() -> None:
    """Should preserve all variable fields."""
    var = Variable(
        kind="file",
        id="f1",
        name="test.py",
        value={"path": "/home/test.py"},
        modelDescription="A test file",
    )
    var_data = VariableData(variables=[var])
    request = Request(
        requestId="req_1",
        message=Message(parts=[], text="test"),
        variableData=var_data,
        response=[],
        timestamp=None,
    )

    context = build_copilot_request_context(request)
    extracted_var = context["variableData"]["variables"][0]

    if extracted_var["kind"] != "file":
        raise AssertionError(f"Expected kind='file', got {extracted_var['kind']}")
    if extracted_var["id"] != "f1":
        raise AssertionError(f"Expected id='f1', got {extracted_var['id']}")
    if extracted_var["name"] != "test.py":
        raise AssertionError(f"Expected name='test.py', got {extracted_var['name']}")
    if extracted_var["modelDescription"] != "A test file":
        raise AssertionError(
            f"Expected modelDescription='A test file', got {extracted_var['modelDescription']}"
        )


def test_build_response_context_empty() -> None:
    """Should handle empty response."""
    request = Request(
        requestId="req_1",
        message=Message(parts=[], text="test"),
        variableData=VariableData(variables=[]),
        response=[],
        timestamp=None,
    )

    response = build_copilot_response_context(request)

    if "response" not in response:
        raise AssertionError("Expected 'response' key in response")
    if response["response"]:
        raise AssertionError(
            f"Expected empty response list, got {response['response']}"
        )


def test_build_response_context_with_text_parts() -> None:
    """Should extract text response parts."""
    resp1 = ResponsePart(
        kind="text",
        value="Here is the answer",
        id=None,
        supportThemeIcons=False,
        supportHtml=False,
        baseUri=None,
        uris=None,
        toolName=None,
        invocationMessage=None,
        pastTenseMessage=None,
        isConfirmed=None,
        isComplete=False,
        source=None,
        toolCallId="",
        toolId="",
        presentation="default",
        uri=None,
        isEdit=False,
        edits=None,
        inlineReference=None,
        done=False,
    )
    request = Request(
        requestId="req_1",
        message=Message(parts=[], text="test"),
        variableData=VariableData(variables=[]),
        response=[resp1],
        timestamp=None,
    )

    response = build_copilot_response_context(request)

    if len(response["response"]) != 1:
        raise AssertionError(
            f"Expected 1 response part, got {len(response['response'])}"
        )
    if response["response"][0]["kind"] != "text":
        raise AssertionError(
            f"Expected kind='text', got {response['response'][0]['kind']}"
        )
    if response["response"][0]["value"] != "Here is the answer":
        raise AssertionError(
            f"Expected value='Here is the answer', got {response['response'][0]['value']}"
        )


def test_build_response_context_with_tool_invocation() -> None:
    """Should extract tool invocation details."""
    resp = ResponsePart(
        kind="toolInvocation",
        value=None,
        id=None,
        supportThemeIcons=False,
        supportHtml=False,
        baseUri=None,
        uris=None,
        toolName="copilot_readFile",
        invocationMessage=None,
        pastTenseMessage=None,
        isConfirmed=None,
        isComplete=True,
        source=None,
        toolCallId="tc_123",
        toolId="read_file_tool",
        presentation="default",
        uri=None,
        isEdit=False,
        edits=None,
        inlineReference=None,
        done=True,
    )
    request = Request(
        requestId="req_1",
        message=Message(parts=[], text="read file"),
        variableData=VariableData(variables=[]),
        response=[resp],
        timestamp=None,
    )

    response = build_copilot_response_context(request)

    if len(response["response"]) != 1:
        raise AssertionError(
            f"Expected 1 response part, got {len(response['response'])}"
        )
    if response["response"][0]["toolName"] != "copilot_readFile":
        raise AssertionError(
            f"Expected toolName='copilot_readFile', got {response['response'][0]['toolName']}"
        )
    if response["response"][0]["toolCallId"] != "tc_123":
        raise AssertionError(
            f"Expected toolCallId='tc_123', got {response['response'][0]['toolCallId']}"
        )


# Helper functions for CoPilot session file ingestion tests
def _make_minimal_copilot_session(tmp_path: Path) -> Path:
    """Create a minimal valid CoPilot session file."""
    session_file = tmp_path / "session.json"
    data = {
        "version": 3,
        "requesterUsername": "testuser",
        "responderUsername": "GitHub Copilot",
        "requests": [
            {
                "requestId": "req_1",
                "message": {"parts": [], "text": "Hello"},
                "variableData": {"variables": []},
                "response": [],
            }
        ],
    }
    session_file.write_text(json.dumps(data))
    return session_file


def _make_complex_copilot_session(tmp_path: Path) -> Path:
    """Create a CoPilot session with multiple requests and tool invocations."""
    session_file = tmp_path / "complex_session.json"
    data = {
        "version": 3,
        "requesterUsername": "developer",
        "responderUsername": "GitHub Copilot",
        "requests": [
            {
                "requestId": "req_1",
                "timestamp": 1609459200000,
                "message": {"parts": [], "text": "How do I read a file in Python?"},
                "variableData": {
                    "variables": [
                        {
                            "kind": "file",
                            "id": "f1",
                            "name": "test.py",
                            "value": None,
                            "modelDescription": "Current file",
                        }
                    ]
                },
                "response": [
                    {
                        "kind": "text",
                        "value": "You can use the open() function...",
                        "supportThemeIcons": False,
                        "supportHtml": False,
                    },
                    {
                        "kind": "toolInvocation",
                        "toolName": "copilot_readFile",
                        "toolCallId": "tc_1",
                        "toolId": "read_file",
                        "isComplete": True,
                    },
                ],
            },
            {
                "requestId": "req_2",
                "message": {"parts": [], "text": "What about error handling?"},
                "variableData": {"variables": []},
                "response": [
                    {
                        "kind": "text",
                        "value": "Always use try/except blocks...",
                        "supportThemeIcons": False,
                        "supportHtml": False,
                    }
                ],
            },
        ],
    }
    session_file.write_text(json.dumps(data))
    return session_file


# Test CoPilot session file ingestion
def test_ingest_minimal_session_creates_records(tmp_path: Path) -> None:
    """Should create file and session records for minimal session."""
    session_file = _make_minimal_copilot_session(tmp_path)
    db_path = tmp_path / "test.db"

    ensure_schema(get_connection(db_path))
    conn = get_connection(db_path)
    conn.execute("BEGIN IMMEDIATE")
    try:
        summary = ingest_copilot_session_file(conn, session_file)
        conn.commit()
    finally:
        conn.close()

    if summary["file_id"] <= 0:
        raise AssertionError(f"Expected file_id > 0, got {summary['file_id']}")
    if summary["interaction_count"] != 1:
        raise AssertionError(
            f"Expected interaction_count=1, got {summary['interaction_count']}"
        )


def test_ingest_session_returns_summary(tmp_path: Path) -> None:
    """Should return summary dict with required keys."""
    session_file = _make_minimal_copilot_session(tmp_path)
    db_path = tmp_path / "test.db"

    ensure_schema(get_connection(db_path))
    conn = get_connection(db_path)
    conn.execute("BEGIN IMMEDIATE")
    try:
        summary = ingest_copilot_session_file(conn, session_file)
        conn.commit()
    finally:
        conn.close()

    if "session_file" not in summary:
        raise AssertionError("Expected 'session_file' key in summary")
    if "file_id" not in summary:
        raise AssertionError("Expected 'file_id' key in summary")
    if "interaction_count" not in summary:
        raise AssertionError("Expected 'interaction_count' key in summary")
    if "tool_invocation_count" not in summary:
        raise AssertionError("Expected 'tool_invocation_count' key in summary")
    if "errors" not in summary:
        raise AssertionError("Expected 'errors' key in summary")
    if not isinstance(summary["errors"], list):
        raise AssertionError(
            f"Expected errors to be list, got {type(summary['errors'])}"
        )


def test_ingest_complex_session_processes_all_requests(tmp_path: Path) -> None:
    """Should process all requests in a session."""
    session_file = _make_complex_copilot_session(tmp_path)
    db_path = tmp_path / "test.db"

    ensure_schema(get_connection(db_path))
    conn = get_connection(db_path)
    conn.execute("BEGIN IMMEDIATE")
    try:
        summary = ingest_copilot_session_file(conn, session_file)
        conn.commit()
    finally:
        conn.close()

    if summary["interaction_count"] != 2:
        raise AssertionError(
            f"Expected interaction_count=2, got {summary['interaction_count']}"
        )


def test_ingest_session_with_tool_invocations(tmp_path: Path) -> None:
    """Should count tool invocations."""
    session_file = _make_complex_copilot_session(tmp_path)
    db_path = tmp_path / "test.db"

    ensure_schema(get_connection(db_path))
    conn = get_connection(db_path)
    conn.execute("BEGIN IMMEDIATE")
    try:
        summary = ingest_copilot_session_file(conn, session_file)
        conn.commit()
    finally:
        conn.close()

    if summary["tool_invocation_count"] < 1:
        raise AssertionError(
            f"Expected tool_invocation_count >= 1, got {summary['tool_invocation_count']}"
        )


def test_ingest_session_without_sanitization(tmp_path: Path) -> None:
    """Should ingest without sanitization when disabled."""
    session_file = _make_minimal_copilot_session(tmp_path)
    db_path = tmp_path / "test.db"

    ensure_schema(get_connection(db_path))
    conn = get_connection(db_path)
    conn.execute("BEGIN IMMEDIATE")
    try:
        summary = ingest_copilot_session_file(conn, session_file, sanitize=False)
        conn.commit()
    finally:
        conn.close()

    if summary["file_id"] <= 0:
        raise AssertionError(f"Expected file_id > 0, got {summary['file_id']}")


def test_ingest_session_with_sanitization(tmp_path: Path) -> None:
    """Should ingest with sanitization when enabled."""
    session_file = _make_minimal_copilot_session(tmp_path)
    db_path = tmp_path / "test.db"

    ensure_schema(get_connection(db_path))
    conn = get_connection(db_path)
    conn.execute("BEGIN IMMEDIATE")
    try:
        summary = ingest_copilot_session_file(conn, session_file, sanitize=True)
        conn.commit()
    finally:
        conn.close()

    if summary["file_id"] <= 0:
        raise AssertionError(f"Expected file_id > 0, got {summary['file_id']}")


def test_ingest_malformed_session_handles_error(tmp_path: Path) -> None:
    """Should handle malformed CoPilot session gracefully."""
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{not valid json}")

    db_path = tmp_path / "test.db"
    ensure_schema(get_connection(db_path))
    conn = get_connection(db_path)
    conn.execute("BEGIN IMMEDIATE")
    try:
        summary = ingest_copilot_session_file(conn, bad_file)
        conn.rollback()
    finally:
        conn.close()

    if len(summary["errors"]) <= 0:
        raise AssertionError(f"Expected at least 1 error, got {len(summary['errors'])}")
    if summary["errors"][0]["severity"] != "CRITICAL":
        raise AssertionError(
            f"Expected severity='CRITICAL', got {summary['errors'][0]['severity']}"
        )


def test_ingest_session_with_missing_optional_fields(tmp_path: Path) -> None:
    """Should handle sessions with missing optional fields."""
    session_file = tmp_path / "minimal.json"
    data = {
        "version": 3,
        "requesterUsername": "user",
        "responderUsername": "Copilot",
        "requests": [
            {
                "requestId": "req_1",
                "response": [],
            }
        ],
    }
    session_file.write_text(json.dumps(data))

    db_path = tmp_path / "test.db"
    ensure_schema(get_connection(db_path))
    conn = get_connection(db_path)
    conn.execute("BEGIN IMMEDIATE")
    try:
        summary = ingest_copilot_session_file(conn, session_file)
        conn.commit()
    finally:
        conn.close()

    # Should still process despite missing optional fields
    if summary["file_id"] <= 0:
        raise AssertionError(f"Expected file_id > 0, got {summary['file_id']}")


# Test discovering and ingesting CoPilot sessions from directory
def test_ingest_from_nonexistent_root(tmp_path: Path) -> None:
    """Should handle nonexistent root directory gracefully."""
    db_path = tmp_path / "test.db"
    nonexistent = tmp_path / "nonexistent"

    ensure_schema(get_connection(db_path))
    conn = get_connection(db_path)

    summaries = ingest_copilot_sessions_from_root(conn, nonexistent)

    # When directory doesn't exist, should return empty list (no files found)
    if not isinstance(summaries, list):
        raise AssertionError(f"Expected list, got {type(summaries)}")
