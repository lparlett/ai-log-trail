"""Ingest Codex session logs into agent-agnostic SQLite schema.

Purpose: Parse Codex session JSONL events and persist to agent-agnostic tables.
Architecture: Currently uses generic load_session_events() for raw JSONL loading.
    For enhanced parsing with validation, can be upgraded to use CodexParser from
    src/agents/codex/parser.py (returns typed CodexMessage/CodexAction objects).
Author: AI-assisted
Date: 2025-12-30
Related: ingest.py (router), ingest_copilot.py (CoPilot counterpart)
"""

from __future__ import annotations

import logging
from pathlib import Path
from sqlite3 import Connection
from typing import Any

from src.parsers.session_parser import load_session_events
from src.parsers.handlers.db_agent_utils import (
    FileInsert,
    SessionInsert,
    InteractionInsert,
    AgentEventInsert,
    insert_file,
    insert_session,
    insert_interaction,
    insert_agent_event,
)
from src.services.redaction_rules import RedactionRule, sync_rules_to_db
from src.services.sanitization import sanitize_json

logger = logging.getLogger(__name__)


def ingest_codex_session_file(  # pylint: disable=unused-argument
    conn: Connection,
    session_file: Path,
    verbose: bool = False,
    batch_size: int = 1000,
    rules: list[RedactionRule] | None = None,
) -> dict[str, Any]:
    """Ingest a single Codex session file into agent-agnostic schema.

    Args:
        conn: SQLite connection with proper schema
        session_file: Path to Codex JSONL session file
        verbose: Enable debug logging
        batch_size: Events batch size for memory management
        rules: Optional redaction rules to apply

    Returns:
        Summary dict with file_id, counts, and other metadata
    """
    if verbose:
        logger.info("Ingesting Codex session: %s", session_file)

    # 1. Create or reuse file record
    file_insert = FileInsert(path=str(session_file), agent_type="codex")
    file_id = insert_file(conn, file_insert)

    # 2. Sync redaction rules if provided
    if rules:
        sync_rules_to_db(conn, rules)

    # 3. Create session record with empty metadata
    session_insert = SessionInsert(
        file_id=file_id,
        agent_type="codex",
        agent_session_id="default",
        agent_metadata={},
    )
    session_id = insert_session(conn, session_insert)

    # 4. Process events into interactions
    events = list(load_session_events(session_file))
    for interaction_index, event in enumerate(events, start=1):
        if not isinstance(event, dict):
            continue  # type: ignore[unreachable]

        # Sanitize event payload
        payload = event.get("payload", {})
        if isinstance(payload, dict):
            payload = sanitize_json(payload)

        # Create interaction record
        interaction_insert = InteractionInsert(
            file_id=file_id,
            session_id=session_id,
            agent_type="codex",
            interaction_index=interaction_index,
            timestamp=event.get("timestamp"),
            agent_user_input=event.get("user_input", ""),
            agent_context={},
            agent_response=event.get("response", ""),
        )
        interaction_id = insert_interaction(conn, interaction_insert)

        # Create agent_event record for the raw event
        agent_event_insert = AgentEventInsert(
            interaction_id=interaction_id,
            event_type=event.get("type", "unknown"),
            timestamp=event.get("timestamp"),
            payload=payload,
        )
        insert_agent_event(conn, agent_event_insert)

    # Return summary
    return {
        "session_file": str(session_file),
        "file_id": file_id,
        "prompts": len(events),
        "token_messages": 0,
        "turn_context_messages": 0,
        "agent_reasoning_messages": 0,
        "function_plan_messages": 0,
        "function_calls": 0,
        "errors": [],
    }
