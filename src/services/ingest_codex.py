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

import json
import logging
from pathlib import Path
from sqlite3 import Connection
from typing import Any

from src.parsers.handlers.db_agent_utils import (
    FileInsert,
    SessionInsert,
    InteractionInsert,
    insert_file,
    insert_session,
    insert_interaction,
)
from src.services.redaction_rules import RedactionRule, sync_rules_to_db
from src.services.sanitization import sanitize_json


def _batch_load_session_events(
    file_path: Path,
    batch_size: int = 1000,
) -> Any:
    """Load JSONL events in batches to manage memory for large files.

    Args:
        file_path: Path to Codex JSONL session file
        batch_size: Number of events per batch

    Yields:
        List of event dicts, up to batch_size at a time
    """
    batch: list[dict[str, Any]] = []
    with file_path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                batch.append(json.loads(raw_line))
                if len(batch) >= batch_size:
                    yield batch
                    batch = []
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Failed to parse JSON on line {line_number} of {file_path}: {exc}"
                ) from exc
    # Yield remaining events
    if batch:
        yield batch


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

    # 4. Process events into interactions in batches
    interaction_index = 0
    for batch in _batch_load_session_events(session_file, batch_size):
        for event in batch:
            if not isinstance(event, dict):
                continue

            # Sanitize entire event before storing (prevents secret leaks in raw_json)
            sanitized_event = sanitize_json(event)
            if not isinstance(sanitized_event, dict):
                continue

            interaction_index += 1

            # Sanitize event payload (already done above, but kept for clarity)
            payload = sanitized_event.get("payload", {})
            if isinstance(payload, dict):
                payload = sanitize_json(payload)

            # Create interaction record with sanitized raw event stored as JSON
            # Note: Codex event types (e.g., 'event_msg', 'session_meta') don't map
            # to agent_events CHECK constraint, so we store raw events in raw_json
            raw_event_json = json.dumps(sanitized_event) if sanitized_event else None

            interaction_insert = InteractionInsert(
                file_id=file_id,
                session_id=session_id,
                agent_type="codex",
                interaction_index=interaction_index,
                timestamp=event.get("timestamp"),
                agent_user_input=event.get("user_input", ""),
                agent_context={},
                agent_response=event.get("response", ""),
                raw_json=raw_event_json,
            )
            insert_interaction(conn, interaction_insert)

    # Return summary
    return {
        "session_file": str(session_file),
        "file_id": file_id,
        "prompts": interaction_index,
        "token_messages": 0,
        "turn_context_messages": 0,
        "agent_reasoning_messages": 0,
        "function_plan_messages": 0,
        "function_calls": 0,
        "errors": [],
    }
