"""Ingest Codex session logs into SQLite.

Purpose: Normalize Codex session events into SQLite rows for transparency.
Author: Codex with Lauren Parlett
Date: 2025-10-30
AI-assisted: Updated with Codex (GPT-5).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from itertools import islice
from pathlib import Path
from sqlite3 import Connection
from typing import Any, Iterable, Iterator, TypedDict

from src.parsers.session_parser import (
    SessionDiscoveryError,
    iter_session_files,
    group_by_user_messages,
    load_session_events,
)
from src.parsers.handlers.event_handlers import (
    EventContext,
    EventHandlerDeps,
    FunctionCallTracker,
    handle_event_msg,
    handle_response_item_event,
    handle_turn_context_event,
)
from src.parsers.handlers.db_utils import (
    SessionInsert,
    PromptInsert,
    insert_session,
    insert_prompt,
    insert_event,
    insert_token,
    insert_turn_context,
    insert_agent_reasoning,
    insert_function_plan,
    insert_function_call,
    update_function_call_output,
)
from src.services.database import ensure_schema, get_connection
from src.services.redaction_rules import (
    DEFAULT_RULE_PATH,
    RedactionRule,
    apply_rules,
    load_rules,
    sync_rules_to_db,
)
from src.services.redactions import RedactionCreate, insert_redaction_application
from src.services.sanitization import sanitize_json
from src.services.validation import EventValidationError, validate_event


logger = logging.getLogger(__name__)


def build_event_handler_deps() -> EventHandlerDeps:
    """Return the default EventHandlerDeps wired to db_utils helpers."""

    return EventHandlerDeps(
        insert_event=insert_event,
        insert_token=insert_token,
        insert_turn_context=insert_turn_context,
        insert_agent_reasoning=insert_agent_reasoning,
        insert_function_plan=insert_function_plan,
        insert_function_call=insert_function_call,
        update_function_call_output=update_function_call_output,
    )


def validate_jsonl_event(event: Any) -> dict[str, Any]:
    """Wrapper around core validation to keep ingest-specific semantics."""

    return validate_event(event)


class SanitizationError(TypeError):
    """Raised when event sanitization fails or produces invalid output."""


def sanitize_json_for_storage(event: dict[str, Any]) -> dict[str, Any]:
    """Sanitize event data before persistence.

    Args:
        event: Raw event dictionary to sanitize

    Returns:
        Sanitized event dictionary with sensitive data redacted

    Raises:
        SanitizationError: If sanitization produces invalid output
        TypeError: If input is not a dictionary
    """
    if not isinstance(event, dict):
        raise TypeError("Event must be a dictionary")

    sanitized_event = sanitize_json(event)
    if not isinstance(sanitized_event, dict):
        raise SanitizationError(
            f"sanitize_json returned {type(sanitized_event)}, expected dict"
        )
    return sanitized_event


class ErrorSeverity(Enum):
    """Enumerates severity levels for processing issues."""

    WARNING = auto()
    ERROR = auto()
    CRITICAL = auto()


class ProcessingErrorAction(Enum):
    """Suggested handling strategy for a processing error."""

    CONTINUE = auto()
    RETRY = auto()
    ABORT = auto()


@dataclass
class ProcessingError:
    """Structured error information for session processing."""

    severity: ErrorSeverity
    code: str
    message: str
    recommended_action: ProcessingErrorAction
    file_path: Path | None = None
    line_number: int | None = None
    context: dict[str, Any] | None = None


def _log_processing_error(error: ProcessingError) -> None:
    """Log structured processing errors with appropriate severity."""

    location = ""
    if error.file_path is not None:
        location = f" ({error.file_path}"
        if error.line_number is not None:
            location += f":{error.line_number}"
        location += ")"
    message = f"{error.code}: {error.message}{location}"
    if error.context:
        message += f" | context={error.context}"

    if error.severity is ErrorSeverity.WARNING:
        logger.warning(message)
        return
    if error.severity is ErrorSeverity.ERROR:
        logger.error(message)
        return
    if error.severity is ErrorSeverity.CRITICAL:
        logger.critical(message)
        return


def serialize_processing_error(error: ProcessingError) -> dict[str, Any]:
    """Return a JSON-serializable representation of a processing error."""

    context: dict[str, Any] | None = None
    if error.context:
        context = sanitize_json_for_storage(error.context)
    return {
        "severity": error.severity.name,
        "code": error.code,
        "message": error.message,
        "recommended_action": error.recommended_action.name,
        "file_path": str(error.file_path) if error.file_path else None,
        "line_number": error.line_number,
        "context": context,
    }


def process_events_in_batches(
    events: Iterator[dict[str, Any]],
    batch_size: int = 1000,
) -> Iterator[list[dict[str, Any]]]:
    """Yield fixed-size batches of events to manage memory usage."""

    batch: list[dict[str, Any]] = []
    for event in events:
        batch.append(event)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


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


def _ensure_file_row(conn: Connection, session_file: Path) -> int:
    """Return file id, creating or resetting prompt data as needed."""

    cursor = conn.execute("SELECT id FROM files WHERE path = ?", (str(session_file),))
    row = cursor.fetchone()
    if row:
        file_id = int(row[0])
        conn.execute(
            "UPDATE files SET ingested_at = CURRENT_TIMESTAMP WHERE id = ?",
            (file_id,),
        )
        conn.execute("DELETE FROM prompts WHERE file_id = ?", (file_id,))
        conn.execute("DELETE FROM sessions WHERE file_id = ?", (file_id,))
        return file_id
    cursor = conn.execute("INSERT INTO files (path) VALUES (?)", (str(session_file),))
    if cursor.lastrowid is None:
        raise ValueError("Failed to retrieve lastrowid from the database.")
    return int(cursor.lastrowid)


def _build_prompt_insert(
    conn: Connection,
    file_id: int,
    prompt_index: int,
    prompt_event: dict[str, Any],
) -> PromptInsert:
    """Create a PromptInsert payload from the raw user event."""

    payload = prompt_event.get("payload")
    message = ""
    if isinstance(payload, dict):
        message = payload.get("message", "") or ""
    return PromptInsert(
        conn=conn,
        file_id=file_id,
        prompt_index=prompt_index,
        timestamp=prompt_event.get("timestamp"),
        message=message,
        raw=prompt_event,
    )


@dataclass
class EventProcessor:
    """Encapsulate per-prompt event processing to limit local variables."""

    deps: EventHandlerDeps
    conn: Any
    file_id: int
    prompt_id: int
    counts: dict[str, int] = field(
        default_factory=lambda: {
            "token_messages": 0,
            "turn_context_messages": 0,
            "agent_reasoning_messages": 0,
            "function_plan_messages": 0,
            "function_calls": 0,
        }
    )
    tracker: FunctionCallTracker = field(default_factory=FunctionCallTracker)

    def process(self, events: Iterable[dict[str, Any]]) -> dict[str, int]:
        """Process all events for the current prompt."""

        for event in events:
            payload = event.get("payload")
            if not isinstance(payload, dict):
                continue
            event_type = event.get("type")
            context = EventContext(
                conn=self.conn,
                file_id=self.file_id,
                prompt_id=self.prompt_id,
                timestamp=event.get("timestamp"),
                payload=payload,
                raw_event=event,
                counts=self.counts,
            )
            if event_type == "event_msg":
                handle_event_msg(self.deps, context)
            elif event_type == "turn_context":
                handle_turn_context_event(self.deps, context)
            elif event_type == "response_item":
                handle_response_item_event(self.deps, context, self.tracker)
        return self.counts


def _process_events(
    conn: Connection,
    file_id: int,
    prompt_id: int,
    events: Iterable[dict[str, Any]],
) -> dict[str, int]:
    """Process events for a prompt and populate child tables.

    Delegates to EventProcessor which:
        - Dispatches each event to the appropriate handler (event_msg, turn_context,
          response_item).
        - Tracks function call state across the entire prompt via FunctionCallTracker.
        - Updates counts for each message type encountered.

    Returns:
        Dictionary mapping message type names to their occurrence counts.
    """

    deps = build_event_handler_deps()
    processor = EventProcessor(
        deps=deps,
        conn=conn,
        file_id=file_id,
        prompt_id=prompt_id,
    )
    return processor.process(events)


def _prepare_events(
    raw_events: Iterable[dict[str, Any]],
    session_file: Path,
    errors: list[ProcessingError] | None = None,
    *,
    batch_size: int = 1000,
) -> list[dict[str, Any]]:
    """Validate and sanitize raw events before grouping using batches."""

    prepared: list[dict[str, Any]] = []
    index = 0
    for batch in process_events_in_batches(
        iter(raw_events),
        batch_size=batch_size,
    ):
        for event in batch:
            index += 1
            try:
                normalized = validate_jsonl_event(event)
            except EventValidationError as exc:
                context_data: dict[str, Any] | None = None
                if isinstance(event, dict):
                    context_data = {"event": sanitize_json_for_storage(event)}
                processing_error = ProcessingError(
                    severity=ErrorSeverity.WARNING,
                    code="invalid_event",
                    message=str(exc),
                    recommended_action=ProcessingErrorAction.CONTINUE,
                    file_path=session_file,
                    line_number=index,
                    context=context_data,
                )
                _log_processing_error(processing_error)
                if errors is not None:
                    errors.append(processing_error)
                continue
            # Security: redact potential secrets before persisting event payloads.
            prepared.append(sanitize_json_for_storage(normalized))
    return prepared


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


def _update_summary_counts(summary: SessionSummary, counts: dict[str, int]) -> None:
    """Update summary with counts from processed events."""
    summary["prompts"] += 1
    for key in (
        "token_messages",
        "turn_context_messages",
        "agent_reasoning_messages",
        "function_plan_messages",
        "function_calls",
    ):
        summary[key] += counts.get(key, 0)


# pylint: disable=too-many-instance-attributes
# Justification: Session ingestion requires tracking: connection, file path, batch
# size, verbosity flag, error list, optional rules, and computed file_id and summary.
# All attributes are semantically distinct and necessary for processing.
@dataclass
class SessionIngester:
    """Process and store a single session's events."""

    conn: Connection
    session_file: Path
    batch_size: int
    verbose: bool
    errors: list[ProcessingError]
    rules: list[RedactionRule] | None = None
    file_id: int = field(init=False)
    summary: SessionSummary = field(init=False)

    def __post_init__(self) -> None:
        """Initialize session-level data after construction."""
        if self.verbose:
            logger.info("Ingesting %s", self.session_file)
        self.file_id = _ensure_file_row(self.conn, self.session_file)
        self.summary = _create_empty_summary(self.session_file, self.file_id)

    def process_session(self) -> SessionSummary:
        """Process all events in the session."""
        events = load_session_events(self.session_file)
        prepared_events = _prepare_events(
            events,
            self.session_file,
            self.errors,
            batch_size=self.batch_size,
        )
        prelude, groups = group_by_user_messages(prepared_events)
        if self.rules:
            # Sync rules to database before applying them
            sync_rules_to_db(self.conn, self.rules)
            _apply_rule_applications_pre_prompt(
                conn=self.conn,
                rules=self.rules,
                file_id=self.file_id,
                session_file_path=str(self.session_file),
                prelude=prelude or [],
            )
        self._store_session_data(prelude, groups)
        self._finalize_summary()
        return self.summary

    def _store_session_data(
        self, prelude: list[dict[str, Any]], groups: list[dict[str, Any]]
    ) -> None:
        """Store session data and process prompt groups."""
        insert_session(
            SessionInsert(
                conn=self.conn,
                file_id=self.file_id,
                prelude=prelude or [],
            )
        )
        self._process_groups(groups)

    def _process_groups(self, groups: list[dict[str, Any]]) -> None:
        """Process and store each prompt group."""
        for index, group in enumerate(groups, start=1):
            prompt_insert = _build_prompt_insert(
                self.conn,
                self.file_id,
                index,
                group["user"],
            )
            prompt_id = insert_prompt(prompt_insert)
            if self.rules:
                _apply_rule_applications_for_prompt(
                    conn=self.conn,
                    rules=self.rules,
                    file_id=self.file_id,
                    prompt_id=prompt_id,
                    session_file_path=str(self.session_file),
                    prompt_event=group["user"],
                    events=group["events"],
                )
            counts = _process_events(
                self.conn,
                self.file_id,
                prompt_id,
                group["events"],
            )
            _update_summary_counts(self.summary, counts)

    def _finalize_summary(self) -> None:
        """Add error information to the summary."""
        self.summary["errors"] = [
            serialize_processing_error(error) for error in self.errors
        ]


def _ingest_single_session(
    conn: Connection,
    session_file: Path,
    *,
    verbose: bool = False,
    batch_size: int = 1000,
    rules: list[RedactionRule] | None = None,
) -> SessionSummary:
    """Internal helper to ingest one session using an existing connection."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        ingester = SessionIngester(
            conn=conn,
            session_file=session_file,
            batch_size=batch_size,
            verbose=verbose,
            errors=[],
            rules=rules,
        )
        summary = ingester.process_session()
        conn.commit()
        return summary
    except Exception:
        conn.rollback()
        raise


def ingest_session_file(
    session_file: Path,
    db_path: Path,
    *,
    verbose: bool = False,
    batch_size: int = 1000,
    rules_path: Path | None = None,
) -> SessionSummary:
    """Parse a session log and persist structured data into SQLite."""

    conn = get_connection(db_path)
    ensure_schema(conn)

    try:
        rules = _load_rules_safely(rules_path or DEFAULT_RULE_PATH, verbose=verbose)
        summary = _ingest_single_session(
            conn,
            session_file,
            verbose=verbose,
            batch_size=batch_size,
            rules=rules,
        )
        return summary
    finally:
        conn.close()


def ingest_sessions_in_directory(
    root: Path,
    db_path: Path,
    *,
    limit: int | None = None,
    verbose: bool = False,
    batch_size: int = 1000,
    rules_path: Path | None = None,
) -> Iterator[SessionSummary]:
    # pylint: disable=too-many-arguments
    # Justification: Caller needs to specify discovery root, DB path, and optional
    # filtering/config parameters (limit, verbosity, batch size, rules file).
    """Ingest multiple session files beneath ``root``."""

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
            summary = _ingest_single_session(
                conn,
                session_file,
                verbose=verbose,
                batch_size=batch_size,
                rules=rules,
            )
            yield summary

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
                "Failed to load rules (%s); continuing ingest without rule logging", exc
            )
        return None


def _apply_rule_applications_pre_prompt(
    *,
    conn: Connection,
    rules: list[RedactionRule],
    file_id: int,
    session_file_path: str,
    prelude: list[dict],
) -> None:
    """Apply rules to prelude events (no prompt id)."""

    for event in prelude:
        _apply_rule_applications_for_event(
            conn=conn,
            rules=rules,
            file_id=file_id,
            prompt_id=None,
            session_file_path=session_file_path,
            event=event,
        )


def _apply_rule_applications_for_prompt(
    *,
    conn: Connection,
    rules: list[RedactionRule],
    file_id: int,
    prompt_id: int,
    session_file_path: str,
    prompt_event: dict[str, Any],
    events: list[dict],
) -> None:
    # pylint: disable=too-many-arguments
    # Justification: Needs connection, rules, file/prompt IDs, session path, and
    # the prompt event + following events for comprehensive redaction tracking.
    """Apply rules to prompt text and associated events."""

    payload = prompt_event.get("payload") if isinstance(prompt_event, dict) else None
    message = ""
    if isinstance(payload, dict):
        message = payload.get("message", "") or ""
    _apply_rule_applications_for_text(
        conn=conn,
        rules=rules,
        file_id=file_id,
        prompt_id=prompt_id,
        session_file_path=session_file_path,
        text=message,
        scope="prompt",
        field_path="prompt.message",
    )
    for event in events:
        _apply_rule_applications_for_event(
            conn=conn,
            rules=rules,
            file_id=file_id,
            prompt_id=prompt_id,
            session_file_path=session_file_path,
            event=event,
        )


def _apply_rule_applications_for_text(
    *,
    conn: Connection,
    rules: list[RedactionRule],
    file_id: int,
    prompt_id: int | None,
    session_file_path: str,
    text: str,
    scope: str,
    field_path: str,
) -> None:
    # pylint: disable=too-many-arguments
    # Justification: Needs connection, rules, file/prompt IDs, session path, text,
    # scope, and field path for auditable redaction application tracking.
    """Apply rules to a text fragment and persist redaction applications."""

    scoped_rules = [rule for rule in rules if _scope_matches(rule.scope, scope)]
    if not scoped_rules or not text:
        return
    _, summary = apply_rules(text, scoped_rules)
    for rule in scoped_rules:
        if rule.id not in summary:
            continue
        _record_rule_application(
            conn=conn,
            rule=rule,
            file_id=file_id,
            prompt_id=prompt_id,
            field_path=field_path if rule.scope != "global" else "*",
            replacement_text=rule.effective_replacement,
            session_file_path=session_file_path,
        )


def _apply_rule_applications_for_event(
    *,
    conn: Connection,
    rules: list[RedactionRule],
    file_id: int,
    prompt_id: int | None,
    session_file_path: str,
    event: dict[str, Any],
) -> None:
    # pylint: disable=too-many-arguments,too-many-locals,too-many-branches
    # Justification: Needs connection, rules, file/prompt IDs, session path, and
    # event for extracting and redacting multiple payload field types with varied
    # branching for different event/payload combinations.
    """Apply rules to known event payload fields and record applications."""

    event_type = event.get("type")
    payload = event.get("payload") if isinstance(event, dict) else None
    payload_type = payload.get("type") if isinstance(payload, dict) else None

    def _apply(text: str, field_path: str, scope: str = "field") -> None:
        _apply_rule_applications_for_text(
            conn=conn,
            rules=rules,
            file_id=file_id,
            prompt_id=prompt_id,
            session_file_path=session_file_path,
            text=text,
            scope=scope,
            field_path=field_path,
        )

    if not isinstance(payload, dict):
        return

    if event_type == "event_msg":
        if payload_type == "agent_reasoning":
            text = payload.get("text")
            if isinstance(text, str) and text.strip():
                _apply(text, "agent.reasoning.text")
        elif payload_type == "agent_message":
            message = payload.get("message")
            if isinstance(message, str) and message.strip():
                _apply(message, "agent.message")

    elif event_type == "response_item":
        if payload_type == "message":
            content = payload.get("content")
            if isinstance(content, list):
                texts = [
                    str(item.get("text"))
                    for item in content
                    if isinstance(item, dict) and isinstance(item.get("text"), str)
                ]
                if texts:
                    _apply(" ".join(texts), "response.message")
        elif payload_type == "function_call":
            name = payload.get("name")
            if name:
                _apply(name, "function_call.name")
            arguments = payload.get("arguments")
            if isinstance(arguments, str) and arguments.strip():
                _apply(arguments, "function_call.arguments")
        elif payload_type == "function_call_output":
            output = payload.get("output")
            if isinstance(output, str) and output.strip():
                _apply(output, "function_call.output")
    elif event_type == "turn_context":
        cwd = payload.get("cwd")
        if isinstance(cwd, str) and cwd.strip():
            _apply(cwd, "turn_context.cwd", scope="field")


def _record_rule_application(
    *,
    conn: Connection,
    rule: RedactionRule,
    file_id: int,
    prompt_id: int | None,
    field_path: str,
    replacement_text: str,  # pylint: disable=unused-argument
    session_file_path: str,
) -> None:
    # pylint: disable=too-many-arguments
    # Justification: Needs connection, rule metadata, file/prompt IDs, field path,
    # replacement text, and session path for comprehensive audit trail recording.
    """Persist rule applications with fingerprinting and upsert logic."""

    payload = RedactionCreate(
        file_id=file_id,
        prompt_id=prompt_id,
        rule_id=rule.id,
        rule_fingerprint=rule.fingerprint,
        field_path=field_path,
        reason=rule.reason,
        actor=rule.actor,
        session_file_path=session_file_path,
        applied_at=None,
    )
    insert_redaction_application(conn, payload)


def _scope_matches(rule_scope: str, context_scope: str) -> bool:
    """Return True when a rule scope applies to the current context."""

    if rule_scope == "global":
        return True
    if rule_scope == "prompt" and context_scope == "prompt":
        return True
    if rule_scope == "field" and context_scope == "field":
        return True
    return False
