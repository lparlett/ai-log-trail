"""Ingest CoPilot chat sessions into SQLite using agent-agnostic schema.

Purpose: Parse and normalize CoPilot sessions into agent-agnostic tables.
Author: AI-assisted by Claude Haiku 4.5
Date: 2025-12-30
Related tests: tests/core/test_copilot_models_and_parser.py
"""

from __future__ import annotations

import logging
from pathlib import Path
from sqlite3 import Connection
from typing import Any

from src.agents.copilot import (
    parse_copilot_session_from_file,
    find_copilot_session_files,
    CoPilotParseError,
)
from src.agents.copilot.models import Session, Request
from src.parsers.handlers.db_agent_utils import (
    FileInsert,
    SessionInsert,
    InteractionInsert,
    AgentToolInvocationInsert,
    insert_file,
    insert_session,
    insert_interaction,
    insert_tool_invocation,
    json_dumps,
)
from src.services.sanitization import sanitize_json


logger = logging.getLogger(__name__)


def build_copilot_session_metadata(session: Session) -> dict[str, Any]:
    """Extract agent_metadata from CoPilot session object."""
    return {
        "requesterUsername": session.requesterUsername,
        "responderUsername": session.responderUsername,
        "initialLocation": session.initialLocation,
        "version": session.version,
    }


def build_copilot_request_user_input(request: Request) -> dict[str, Any]:
    """Extract user input from CoPilot request (message parts as dict).

    Builds the message structure as a dictionary (not yet JSON) to allow
    for proper sanitization of individual message parts before serialization.
    """
    # Build message as dict first to allow sanitization
    message_dict = {
        "parts": [
            {
                "text": part.text,
                "kind": part.kind,
                "range": (
                    {
                        "start": part.range.start,
                        "endExclusive": part.range.endExclusive,
                    }
                    if part.range
                    else None
                ),
                "editorRange": (
                    {
                        "startLineNumber": part.editorRange.startLineNumber,
                        "startColumn": part.editorRange.startColumn,
                        "endLineNumber": part.editorRange.endLineNumber,
                        "endColumn": part.editorRange.endColumn,
                    }
                    if part.editorRange
                    else None
                ),
            }
            for part in request.message.parts
        ]
    }
    return message_dict  # Return dict, not JSON string (caller will handle conversion)


def build_copilot_request_context(request: Request) -> dict[str, Any]:
    """Extract context from CoPilot request (variableData as JSON)."""
    variables = []
    for var in request.variableData.variables:
        variables.append(
            {
                "kind": var.kind,
                "id": var.id,
                "name": var.name,
                "value": var.value,  # Can be URI, string, or object
                "modelDescription": var.modelDescription,
            }
        )
    return {
        "variableData": {
            "variables": variables,
        }
    }


def build_copilot_response_context(request: Request) -> dict[str, Any]:
    """Extract response array from CoPilot request."""
    responses = []
    for part in request.response:
        response_obj: dict[str, Any] = {
            "kind": part.kind,
            "value": part.value,
        }
        if part.toolName:
            response_obj["toolName"] = part.toolName
        if part.toolCallId:
            response_obj["toolCallId"] = part.toolCallId
        responses.append(response_obj)
    return {"response": responses}


def ingest_copilot_session_file(
    conn: Connection, session_file: Path, sanitize: bool = True
) -> dict[str, Any]:  # pylint: disable=too-many-locals
    """Ingest a single CoPilot session file into agent-agnostic schema.

    Args:
        conn: SQLite connection with schema initialized and active transaction
        session_file: Path to CoPilot session JSON file
        sanitize: Whether to sanitize sensitive data before storage

    Returns:
        Summary dict with file_id, interaction_count, tool_invocation_count, errors

    Note:
        Transaction management (BEGIN/COMMIT/ROLLBACK) is the caller's
        responsibility. This function assumes an active transaction and does
        not commit or rollback.
    """
    summary: dict[str, Any] = {
        "session_file": str(session_file),
        "file_id": 0,
        "interaction_count": 0,
        "tool_invocation_count": 0,
        "errors": [],
    }

    try:
        # Parse the CoPilot session
        session = parse_copilot_session_from_file(session_file)
    except CoPilotParseError as e:  # pylint: disable=broad-exception-caught
        summary["errors"].append(
            {
                "severity": "CRITICAL",
                "code": "copilot_parse_error",
                "message": str(e),
                "file": str(session_file),
            }
        )
        logger.error("Failed to parse CoPilot session %s: %s", session_file, e)
        return summary

    try:
        # Insert file record
        file_insert = FileInsert(path=str(session_file), agent_type="copilot")
        file_id = insert_file(conn, file_insert)
        summary["file_id"] = file_id

        # Extract and sanitize session metadata
        session_metadata = build_copilot_session_metadata(session)
        if sanitize:
            session_metadata = sanitize_json(session_metadata)

        # Insert session record
        session_insert = SessionInsert(
            file_id=file_id,
            agent_type="copilot",
            agent_session_id=None,  # CoPilot doesn't have explicit session IDs
            agent_metadata=session_metadata,
            raw_json=json_dumps(
                {
                    "version": session.version,
                    "requesterUsername": session.requesterUsername,
                    "responderUsername": session.responderUsername,
                }
            ),
        )
        session_id = insert_session(conn, session_insert)

        # Process each request as an interaction (1-based indexing for consistency with Codex)
        for request_index, request in enumerate(session.requests, start=1):
            try:
                # Build context and response data
                user_input_dict = build_copilot_request_user_input(request)
                context = build_copilot_request_context(request)
                response = build_copilot_response_context(request)

                if sanitize:
                    # Sanitize message parts before serializing to JSON
                    user_input_dict = sanitize_json(user_input_dict)
                    if not isinstance(user_input_dict, dict):
                        user_input_dict = {}
                    # Serialize sanitized message dict to JSON string
                    user_input = json_dumps(user_input_dict)

                    context_sanitized = sanitize_json(context)
                    if isinstance(context_sanitized, dict):
                        context = context_sanitized
                    response_sanitized = sanitize_json(response)
                    if isinstance(response_sanitized, dict):
                        response = response_sanitized
                else:
                    # No sanitization, just serialize the message dict to JSON
                    user_input = json_dumps(user_input_dict)

                # Insert interaction
                interaction_insert = InteractionInsert(
                    file_id=file_id,
                    session_id=session_id,
                    agent_type="copilot",
                    interaction_index=request_index,
                    timestamp=None,  # CoPilot doesn't record request timestamps
                    agent_user_input=user_input,
                    agent_context=context,
                    agent_response=response,
                    raw_json=None,
                )
                interaction_id = insert_interaction(conn, interaction_insert)
                summary["interaction_count"] += 1

                # Process tool invocations in response
                for response_part in request.response:
                    if (
                        response_part.kind == "toolInvocation"
                        and response_part.toolName
                    ):
                        tool_insert = AgentToolInvocationInsert(
                            interaction_id=interaction_id,
                            agent_type="copilot",
                            tool_name=response_part.toolName,
                            tool_id=response_part.toolId,
                            invocation_id=response_part.toolCallId,
                            call_timestamp=None,
                            response_timestamp=None,
                            tool_arguments={},  # CoPilot tool args stored in response
                            tool_output=None,
                            tool_status="pending",
                        )
                        insert_tool_invocation(conn, tool_insert)
                        summary["tool_invocation_count"] += 1

            except (ValueError, TypeError, AttributeError, KeyError) as e:
                summary["errors"].append(
                    {
                        "severity": "ERROR",
                        "code": "interaction_processing_error",
                        "message": str(e),
                        "request_index": request_index,
                    }
                )
                logger.error(
                    "Error processing request %d in %s: %s",
                    request_index,
                    session_file,
                    e,
                )

    except (ValueError, TypeError, AttributeError, KeyError, OSError) as e:
        summary["errors"].append(
            {
                "severity": "CRITICAL",
                "code": "ingest_error",
                "message": str(e),
            }
        )
        logger.error("Failed to ingest CoPilot session %s: %s", session_file, e)

    return summary


def ingest_copilot_sessions_from_root(
    conn: Connection, copilot_root: Path, sanitize: bool = True
) -> list[dict[str, Any]]:
    """Discover and ingest all CoPilot sessions under the given root.

    Args:
        conn: SQLite connection
        copilot_root: Root path to VS Code workspaceStorage
        sanitize: Whether to sanitize before storage

    Returns:
        List of summary dicts for each ingested session
    """
    summaries: list[dict[str, Any]] = []

    try:
        session_files = find_copilot_session_files(copilot_root)
    except (OSError, ValueError) as e:
        logger.error(
            "Failed to discover CoPilot sessions under %s: %s", copilot_root, e
        )
        return [
            {
                "error": "session_discovery_failed",
                "root": str(copilot_root),
                "message": str(e),
            }
        ]

    for session_file in session_files:
        summary = ingest_copilot_session_file(conn, session_file, sanitize=sanitize)
        summaries.append(summary)

    return summaries


__all__ = [
    "ingest_copilot_session_file",
    "ingest_copilot_sessions_from_root",
]
