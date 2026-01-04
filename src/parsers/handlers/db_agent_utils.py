"""Database utility helpers for agent-agnostic session ingestion.

Purpose: Shared extract/insert helpers for any agent (Codex, CoPilot, etc).
Author: AI-assisted by Claude Haiku 4.5
Date: 2025-12-30
Related tables: files, sessions, interactions, agent_events, agent_tool_invocations
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from sqlite3 import Connection


def json_dumps(data: Any) -> str:
    """Serialize payloads to JSON without forcing ASCII."""
    return json.dumps(data, ensure_ascii=False)


@dataclass
class FileInsert:
    """Payload for files table insertion."""

    path: str
    agent_type: str  # 'codex' or 'copilot'


@dataclass
class SessionInsert:  # pylint: disable=too-many-instance-attributes
    """Payload for sessions table insertion."""

    file_id: int
    agent_type: str  # 'codex' or 'copilot'
    agent_session_id: str | None
    agent_metadata: dict[str, Any]  # JSON: sandbox, approval, requester info, etc.
    raw_json: str | None = None


@dataclass
class InteractionInsert:  # pylint: disable=too-many-instance-attributes
    """Payload for interactions table insertion (replaces PromptInsert)."""

    file_id: int
    session_id: int
    agent_type: str  # 'codex' or 'copilot'
    interaction_index: int
    timestamp: str | None
    agent_user_input: str | None  # Codex: prompt text; CoPilot: message JSON
    agent_context: dict[
        str, Any
    ]  # Codex: active_file, open_tabs; CoPilot: variableData
    agent_response: dict[str, Any]  # Codex: empty for now; CoPilot: response array
    raw_json: str | None = None


@dataclass
class AgentEventInsert:
    """Payload for agent_events table insertion."""

    interaction_id: int
    event_type: (
        str  # 'token_usage', 'agent_reasoning', 'context_change', 'function_plan'
    )
    timestamp: str | None
    payload: dict[str, Any]  # Event-specific data (JSON)
    raw_json: str | None = None


@dataclass
class AgentToolInvocationInsert:  # pylint: disable=too-many-instance-attributes
    """Payload for agent_tool_invocations table insertion."""

    interaction_id: int
    agent_type: str
    tool_name: str
    tool_id: str | None
    invocation_id: str | None
    call_timestamp: str | None
    response_timestamp: str | None
    tool_arguments: dict[str, Any] | None
    tool_output: str | None
    tool_status: str | None  # 'pending', 'success', 'error'
    raw_input_json: str | None = None
    raw_output_json: str | None = None


def insert_file(conn: Connection, file_insert: FileInsert) -> int:
    """Insert or update a file record. Return file_id."""
    cursor = conn.execute(
        "SELECT id FROM files WHERE path = ?",
        (file_insert.path,),
    )
    row = cursor.fetchone()
    if row:
        file_id = int(row[0])
        # Update timestamp and clean up dependent rows for re-ingest
        conn.execute(
            "UPDATE files SET ingested_at = CURRENT_TIMESTAMP WHERE id = ?",
            (file_id,),
        )
        # Clean up old data from previous ingest
        conn.execute("DELETE FROM interactions WHERE file_id = ?", (file_id,))
        conn.execute("DELETE FROM sessions WHERE file_id = ?", (file_id,))
        return file_id
    cursor = conn.execute(
        "INSERT INTO files (path, agent_type) VALUES (?, ?)",
        (file_insert.path, file_insert.agent_type),
    )
    if cursor.lastrowid is None:
        raise ValueError("Failed to retrieve lastrowid from files insert.")
    return int(cursor.lastrowid)


def insert_session(conn: Connection, session_insert: SessionInsert) -> int:
    """Insert a session record. Return session_id."""
    cursor = conn.execute(
        """INSERT INTO sessions
           (file_id, agent_type, agent_session_id, agent_metadata, raw_json)
           VALUES (?, ?, ?, ?, ?)""",
        (
            session_insert.file_id,
            session_insert.agent_type,
            session_insert.agent_session_id,
            json_dumps(session_insert.agent_metadata),
            session_insert.raw_json,
        ),
    )
    if cursor.lastrowid is None:
        raise ValueError("Failed to retrieve lastrowid from sessions insert.")
    return int(cursor.lastrowid)


def insert_interaction(conn: Connection, interaction_insert: InteractionInsert) -> int:
    """Insert an interaction record. Return interaction_id."""
    cursor = conn.execute(
        """INSERT INTO interactions
           (file_id, session_id, agent_type, interaction_index, timestamp,
            agent_user_input, agent_context, agent_response, raw_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            interaction_insert.file_id,
            interaction_insert.session_id,
            interaction_insert.agent_type,
            interaction_insert.interaction_index,
            interaction_insert.timestamp,
            interaction_insert.agent_user_input,
            json_dumps(interaction_insert.agent_context),
            json_dumps(interaction_insert.agent_response),
            interaction_insert.raw_json,
        ),
    )
    if cursor.lastrowid is None:
        raise ValueError("Failed to retrieve lastrowid from interactions insert.")
    return int(cursor.lastrowid)


def insert_agent_event(conn: Connection, event_insert: AgentEventInsert) -> int:
    """Insert an agent_events record. Return event_id."""
    cursor = conn.execute(
        """INSERT INTO agent_events
           (interaction_id, event_type, timestamp, payload, raw_json)
           VALUES (?, ?, ?, ?, ?)""",
        (
            event_insert.interaction_id,
            event_insert.event_type,
            event_insert.timestamp,
            json_dumps(event_insert.payload),
            event_insert.raw_json,
        ),
    )
    if cursor.lastrowid is None:
        raise ValueError("Failed to retrieve lastrowid from agent_events insert.")
    return int(cursor.lastrowid)


def insert_tool_invocation(
    conn: Connection, tool_insert: AgentToolInvocationInsert
) -> int:
    """Insert an agent_tool_invocations record. Return invocation_id."""
    cursor = conn.execute(
        """INSERT INTO agent_tool_invocations
           (interaction_id, agent_type, tool_name, tool_id, invocation_id,
            call_timestamp, response_timestamp, tool_arguments, tool_output,
            tool_status, raw_input_json, raw_output_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            tool_insert.interaction_id,
            tool_insert.agent_type,
            tool_insert.tool_name,
            tool_insert.tool_id,
            tool_insert.invocation_id,
            tool_insert.call_timestamp,
            tool_insert.response_timestamp,
            (
                json_dumps(tool_insert.tool_arguments)
                if tool_insert.tool_arguments
                else None
            ),
            tool_insert.tool_output,
            tool_insert.tool_status,
            tool_insert.raw_input_json,
            tool_insert.raw_output_json,
        ),
    )
    if cursor.lastrowid is None:
        raise ValueError(
            "Failed to retrieve lastrowid from agent_tool_invocations insert."
        )
    return int(cursor.lastrowid)


__all__ = [
    "json_dumps",
    "FileInsert",
    "SessionInsert",
    "InteractionInsert",
    "AgentEventInsert",
    "AgentToolInvocationInsert",
    "insert_file",
    "insert_session",
    "insert_interaction",
    "insert_agent_event",
    "insert_tool_invocation",
]
