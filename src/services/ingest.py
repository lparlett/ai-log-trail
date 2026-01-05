"""Agent-aware session ingest router.

Purpose: Detect agent type (Codex/CoPilot) and delegate to agent-specific ingestion handlers.
    Current: Codex uses raw JSONL loading, CoPilot uses structured parsing.
    Future: Codex can be enhanced to use CodexParser for structured parsing.
Author: AI-assisted
Date: 2025-12-30
Related: ingest_codex.py (Codex), ingest_copilot.py (CoPilot)
"""

from __future__ import annotations

import json
import logging
from itertools import islice
from pathlib import Path
from typing import Any, Iterator, TypedDict

from src.parsers.session_parser import (
    SessionDiscoveryError,
    iter_session_files,
    load_session_events,
)
from src.services.database import ensure_schema, get_connection
from src.services.ingest_codex import ingest_codex_session_file
from src.services.ingest_copilot import ingest_copilot_session_file
from src.services.redaction_rules import (
    DEFAULT_RULE_PATH,
    RedactionRule,
    load_rules,
)


logger = logging.getLogger(__name__)


class SessionSummary(TypedDict):
    """Structured ingest result for a single Codex session file."""

    session_file: str
    file_id: int
    prompts: int
    token_messages: int
    turn_context_messages: int
    agent_reasoning_messages: int
    function_plan_messages: int
    function_calls: int
    errors: list[dict[str, Any]]


__all__ = [
    "get_connection",
    "ensure_schema",
    "SessionDiscoveryError",
    "ingest_session_file",
    "ingest_sessions_in_directory",
    "ingest_copilot_session_file",
    "detect_agent_type",
    "SessionSummary",
]


def _create_empty_summary(session_file: Path, file_id: int) -> SessionSummary:
    """Create an empty summary dictionary for tracking ingestion stats."""
    return {
        "session_file": str(session_file),
        "file_id": file_id,
        "prompts": 0,
        "token_messages": 0,
        "turn_context_messages": 0,
        "agent_reasoning_messages": 0,
        "function_plan_messages": 0,
        "function_calls": 0,
        "errors": [],
    }


def detect_agent_type(session_file: Path) -> str:
    """Detect whether a session file is from Codex or CoPilot.

    Args:
        session_file: Path to session file (JSONL for Codex, JSON for CoPilot)

    Returns:
        "codex" or "copilot" based on file structure

    Raises:
        FileNotFoundError: If session file does not exist
        ValueError: If agent type cannot be determined
    """
    if not session_file.exists():
        raise FileNotFoundError(f"Session file not found: {session_file}")

    with session_file.open("r", encoding="utf-8") as handle:
        first_line = handle.readline().strip()

    if not first_line:
        msg = f"Empty file: {session_file}"
        raise ValueError(msg)

    # Try to parse first line as JSON to detect agent type
    try:
        obj = json.loads(first_line)
        if isinstance(obj, dict):
            # Check for CoPilot-specific fields
            if "requesterUsername" in obj or "responderUsername" in obj:
                return "copilot"

            # Check for Codex-specific event types
            event_type = obj.get("type")
            if event_type in (
                "session_meta",
                "event_msg",
                "turn_context",
                "response_item",
            ):
                return "codex"

    except json.JSONDecodeError:
        pass

    # If first line doesn't determine it, try loading as JSONL (Codex format)
    try:
        events = load_session_events(session_file)
    except ValueError as exc:
        # File is not valid JSONL, maybe it's single JSON (CoPilot)?
        try:
            with session_file.open("r", encoding="utf-8") as f:
                obj = json.load(f)
            if isinstance(obj, dict) and (
                "requesterUsername" in obj or "version" in obj
            ):
                return "copilot"
        except json.JSONDecodeError as json_exc:
            raise ValueError(
                f"Cannot determine agent type for {session_file}"
            ) from json_exc
        raise ValueError(f"Cannot determine agent type for {session_file}") from exc

    # Inspect all events to determine agent type
    for event in events:
        if isinstance(event, dict):
            event_type = event.get("type")

            # Codex events have type: "session_meta", "event_msg", "turn_context", "response_item"
            if event_type in (
                "session_meta",
                "event_msg",
                "turn_context",
                "response_item",
            ):
                return "codex"

            # CoPilot events have type: "request", "response", etc.
            if event_type in ("request", "response"):
                return "copilot"

    msg = f"No recognized event types found in {session_file}"
    raise ValueError(msg)


def ingest_session_file(
    session_file: Path,
    db_path: Path,
    *,
    verbose: bool = False,
    batch_size: int = 1000,
    rules_path: Path | None = None,
) -> dict[str, Any]:
    """Parse a session log and persist to agent-agnostic schema.

    Automatically detects agent type (Codex or CoPilot) and routes
    to the appropriate ingestion function.

    Args:
        session_file: Path to session JSONL file
        db_path: Path to SQLite database
        verbose: Enable debug logging
        batch_size: Events batch size for memory management
        rules_path: Optional path to redaction rules file

    Returns:
        Summary dict with ingest statistics
    """
    conn = get_connection(db_path)
    ensure_schema(conn)

    try:
        agent_type = detect_agent_type(session_file)
        rules = _load_rules_safely(rules_path or DEFAULT_RULE_PATH, verbose=verbose)

        if verbose:
            logger.info("Detected agent type: %s", agent_type)

        conn.execute("BEGIN IMMEDIATE")
        try:
            if agent_type == "codex":
                summary = ingest_codex_session_file(
                    conn,
                    session_file,
                    verbose=verbose,
                    batch_size=batch_size,
                    rules=rules,
                )
            elif agent_type == "copilot":
                summary = ingest_copilot_session_file(conn, session_file)
            else:
                raise ValueError(f"Unknown agent type: {agent_type}")
            conn.commit()
            return summary
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()


def ingest_sessions_in_directory(  # pylint: disable=too-many-arguments
    root: Path,
    db_path: Path,
    *,
    limit: int | None = None,
    verbose: bool = False,
    batch_size: int = 1000,
    rules_path: Path | None = None,
) -> Iterator[dict[str, Any]]:
    """Ingest multiple session files beneath ``root``.

    Automatically detects and routes each session to the appropriate
    agent-specific ingestion handler.

    Args:
        root: Root directory containing session files
        db_path: Path to SQLite database
        limit: Max number of sessions to ingest
        verbose: Enable debug logging
        batch_size: Events batch size for memory management
        rules_path: Optional path to redaction rules file

    Yields:
        Summary dict for each successfully ingested session

    Raises:
        SessionDiscoveryError: If no session files are found
    """
    conn = get_connection(db_path)
    ensure_schema(conn)

    try:
        rules = _load_rules_safely(rules_path or DEFAULT_RULE_PATH, verbose=verbose)
        files_iter = iter_session_files(root)
        if limit is not None:
            files_iter = islice(files_iter, limit)

        processed = False
        for session_file in files_iter:
            processed = True
            try:
                agent_type = detect_agent_type(session_file)
                if verbose:
                    logger.info("Ingesting %s (%s)", session_file.name, agent_type)

                conn.execute("BEGIN IMMEDIATE")
                try:
                    if agent_type == "codex":
                        summary = ingest_codex_session_file(
                            conn,
                            session_file,
                            verbose=verbose,
                            batch_size=batch_size,
                            rules=rules,
                        )
                    elif agent_type == "copilot":
                        summary = ingest_copilot_session_file(conn, session_file)
                    else:
                        logger.warning("Unknown agent type for %s", session_file)
                        continue
                    conn.commit()
                    yield summary
                except Exception as exc:  # pylint: disable=broad-except
                    conn.rollback()
                    logger.error("Failed to ingest %s: %s", session_file, exc)
                    if verbose:
                        raise
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Error processing %s: %s", session_file, exc)
                if verbose:
                    raise

        if not processed:
            raise SessionDiscoveryError(f"No session files found under {root}")
    finally:
        conn.close()


def _load_rules_safely(
    rules_path: Path, *, verbose: bool
) -> list[RedactionRule] | None:
    """Load rules; return None on failure to avoid blocking ingest."""
    try:
        return load_rules(rules_path)
    except Exception as exc:  # pylint: disable=broad-except
        if verbose:
            logger.warning(
                "Failed to load rules (%s); continuing ingest without rule logging",
                exc,
            )
        return None
