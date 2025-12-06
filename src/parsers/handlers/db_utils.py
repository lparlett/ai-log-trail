"""Database utility helpers used during Codex session ingestion.

Purpose: Shared extract/insert helpers for Codex session ingest.
Author: Codex with Lauren Parlett
Date: 2025-10-30
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


DB_UTIL_EXPORTS: tuple[str, ...] = (
    "json_dumps",
    "extract_session_details",
    "extract_token_fields",
    "extract_turn_context",
    "get_reasoning_text",
    "parse_prompt_message",
    "SessionInsert",
    "PromptInsert",
    "EventInsert",
    "AgentReasoningInsert",
    "FunctionCallInsert",
    "FunctionCallOutputUpdate",
    "insert_session",
    "insert_prompt",
    "insert_event",
    "insert_token",
    "insert_turn_context",
    "insert_agent_reasoning",
    "insert_function_plan",
    "insert_function_call",
    "update_function_call_output",
    "SAFE_COLUMNS",
)

# Columns that accept sanitized user-supplied content; referenced when
# documenting safeguards around SQL parameterization.
SAFE_COLUMNS = frozenset(
    (
        "message",
        "active_file",
        "open_tabs",
        "my_request",
    )
)


class UnsafeColumnError(ValueError):
    """Raised when attempting to bind user data to an unvetted column."""


def validate_safe_column(column: str) -> None:
    """Ensure only vetted columns receive user-supplied payloads."""

    if column not in SAFE_COLUMNS:
        raise UnsafeColumnError(
            f"Column '{column}' is not in the allowlist for user-supplied data. "
            f"Allowed columns are: {sorted(SAFE_COLUMNS)}"
        )


def safe_value(column: str, value: Any) -> Any:
    """Return value after verifying the destination column is permitted."""

    validate_safe_column(column)
    return value


def json_dumps(data: Any) -> str:
    """Serialize payloads to JSON without forcing ASCII."""

    return json.dumps(data, ensure_ascii=False)


def extract_tag_value(text: str, tag: str) -> str | None:
    """Return inner text for the given XML-style tag if present."""

    start_tag = f"<{tag}>"
    end_tag = f"</{tag}>"
    start_index = text.find(start_tag)
    if start_index == -1:
        return None
    start_index += len(start_tag)
    end_index = text.find(end_tag, start_index)
    if end_index == -1:
        return None
    return text[start_index:end_index].strip()


def extract_session_details(prelude: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive session metadata from the prelude events."""

    details: dict[str, Any] = {
        "session_id": None,
        "session_timestamp": None,
        "cwd": None,
        "approval_policy": None,
        "sandbox_mode": None,
        "network_access": None,
    }

    for event in prelude:
        event_type = event.get("type")
        payload = event.get("payload")
        if event_type == "session_meta" and isinstance(payload, dict):
            details["session_id"] = payload.get("id")
            details["session_timestamp"] = payload.get("timestamp") or event.get(
                "timestamp"
            )
            details["cwd"] = payload.get("cwd") or details["cwd"]
        elif (
            event_type == "response_item"
            and isinstance(payload, dict)
            and payload.get("type") == "message"
        ):
            _extract_env_context(payload, details)

    return details


def _extract_env_context(payload: dict[str, Any], details: dict[str, Any]) -> None:
    """Populate environment details from message payload."""

    content = payload.get("content")
    if not isinstance(content, list):
        return
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str) or "<environment_context>" not in text:
            continue
        details["cwd"] = extract_tag_value(text, "cwd") or details["cwd"]
        details["approval_policy"] = extract_tag_value(
            text,
            "approval_policy",
        )
        details["sandbox_mode"] = extract_tag_value(text, "sandbox_mode")
        details["network_access"] = extract_tag_value(
            text,
            "network_access",
        )


def extract_token_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize token count payload for insertion."""

    primary = (
        payload.get("rate_limits", {}).get("primary", {})
        if isinstance(payload, dict)
        else {}
    )
    secondary = (
        payload.get("rate_limits", {}).get("secondary", {})
        if isinstance(payload, dict)
        else {}
    )
    return {
        "primary_used_percent": primary.get("used_percent"),
        "primary_window_minutes": primary.get("window_minutes"),
        "primary_resets": primary.get("resets_at") or primary.get("resets_in_seconds"),
        "secondary_used_percent": secondary.get("used_percent"),
        "secondary_window_minutes": secondary.get("window_minutes"),
        "secondary_resets": secondary.get("resets_at")
        or secondary.get("resets_in_seconds"),
    }


def extract_turn_context(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize turn context payload for insertion."""

    sandbox = payload.get("sandbox_policy", {}) if isinstance(payload, dict) else {}
    writable_roots = sandbox.get("writable_roots")
    if isinstance(writable_roots, list):
        writable_roots = ", ".join(str(item) for item in writable_roots)
    return {
        "cwd": payload.get("cwd"),
        "approval_policy": payload.get("approval_policy"),
        "sandbox_mode": sandbox.get("mode"),
        "network_access": sandbox.get("network_access"),
        "writable_roots": writable_roots,
    }


def get_reasoning_text(payload: dict[str, Any]) -> str | None:
    """Extract reasoning text from payload if present."""

    text = payload.get("text")
    if isinstance(text, str) and text.strip():
        return text
    summary = payload.get("summary")
    if isinstance(summary, list) and summary:
        entry = summary[0]
        if isinstance(entry, dict):
            text = entry.get("text")
            if isinstance(text, str) and text.strip():
                return text
    content = payload.get("content")
    if isinstance(content, str) and content.strip():
        return content
    return None


def parse_prompt_message(
    message: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Extract structured context from the standard prompt template."""

    if not message:
        return None, None, None

    active_file: str | None = None
    open_tabs: list[str] = []
    my_request_lines: list[str] = []

    state: str | None = None
    for line in message.splitlines():
        stripped = line.strip()
        if stripped.startswith("## Active file:"):
            active_file = stripped[len("## Active file:") :].strip() or None
            state = None
            continue
        if stripped.startswith("## Open tabs:"):
            state = "open_tabs"
            continue
        if stripped.startswith("## My request for Codex:"):
            state = "my_request"
            continue
        if state == "open_tabs":
            if stripped.startswith("-"):
                open_tabs.append(stripped[1:].strip())
                continue
            if stripped.startswith("## ") or stripped == "":
                state = None
                continue
            open_tabs.append(stripped)
            continue
        if state == "my_request":
            if stripped.startswith("## "):
                state = None
                continue
            my_request_lines.append(line.rstrip())

    open_tabs_value = "\n".join(tab for tab in open_tabs if tab) or None
    my_request_value = (
        "\n".join(line for line in my_request_lines if line).strip() or None
    )
    return active_file, open_tabs_value, my_request_value


@dataclass
class SessionInsert:
    """Context for inserting session-level metadata."""

    conn: Any
    file_id: int
    prelude: list[dict[str, Any]]


@dataclass
class PromptInsert:
    """Context for inserting a user prompt."""

    conn: Any
    file_id: int
    prompt_index: int
    timestamp: str | None
    message: str
    raw: dict[str, Any]


@dataclass
class EventInsert:
    """Context for inserting an event related to a prompt."""

    conn: Any
    file_id: int
    prompt_id: int
    timestamp: str | None
    payload: dict[str, Any]
    raw: dict[str, Any]


def insert_event(ctx: EventInsert) -> None:
    """Insert a base event record."""

    cursor = ctx.conn.cursor()
    cursor.execute(
        """
        INSERT INTO events (
            file_id,
            timestamp,
            event_type,
            category,
            priority,
            session_id,
            data,
            raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            ctx.file_id,
            ctx.timestamp,
            ctx.payload.get("type", "unknown"),
            ctx.payload.get("category", "other"),
            ctx.payload.get("priority", "medium"),
            ctx.payload.get("session_id"),
            json_dumps(ctx.payload),
            json_dumps(ctx.raw),
        ),
    )


@dataclass
class AgentReasoningInsert(EventInsert):
    """Context for inserting agent reasoning content."""

    source: str


@dataclass
class FunctionCallInsert(EventInsert):
    """Context for inserting a function call event."""


@dataclass
class FunctionCallOutputUpdate:
    """Context for updating a function call with output details."""

    conn: Any
    row_id: int
    timestamp: str | None
    payload: dict[str, Any]
    raw: dict[str, Any]


def insert_session(context: SessionInsert) -> None:
    """Persist session-level metadata captured before the first user prompt."""

    details = extract_session_details(context.prelude)
    session_cursor = context.conn.execute(
        """
        INSERT INTO sessions (
            file_id, session_id, session_timestamp, raw_json
        ) VALUES (?, ?, ?, ?)
        """,
        (
            context.file_id,
            details["session_id"],
            details["session_timestamp"],
            json_dumps({"events": context.prelude}),
        ),
    )
    session_id = session_cursor.lastrowid
    if session_id is None:
        raise RuntimeError("Failed to insert session row")

    # Insert context data into session_context table
    context.conn.execute(
        """
        INSERT INTO session_context (
            session_id, cwd, approval_policy, sandbox_mode, network_access
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            session_id,
            details["cwd"],
            details["approval_policy"],
            details["sandbox_mode"],
            details["network_access"],
        ),
    )


def insert_prompt(context: PromptInsert) -> int:
    """Insert prompt row and return its id."""

    active_file, open_tabs, my_request = parse_prompt_message(context.message)
    cursor = context.conn.execute(
        """
        INSERT INTO prompts (
            file_id, prompt_index, timestamp, message, active_file, open_tabs,
            my_request, raw_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            context.file_id,
            context.prompt_index,
            context.timestamp,
            safe_value("message", context.message),
            safe_value("active_file", active_file),
            safe_value("open_tabs", open_tabs),
            safe_value("my_request", my_request),
            json_dumps(context.raw),
        ),
    )
    return int(cursor.lastrowid)


def insert_token(context: EventInsert) -> None:
    """Persist token usage data."""

    fields = extract_token_fields(context.payload)
    context.conn.execute(
        """
        INSERT INTO token_messages (
            prompt_id, timestamp,
            primary_used_percent, primary_window_minutes, primary_resets,
            secondary_used_percent, secondary_window_minutes, secondary_resets,
            raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            context.prompt_id,
            context.timestamp,
            fields["primary_used_percent"],
            fields["primary_window_minutes"],
            fields["primary_resets"],
            fields["secondary_used_percent"],
            fields["secondary_window_minutes"],
            fields["secondary_resets"],
            json_dumps(context.raw),
        ),
    )


def insert_turn_context(context: EventInsert) -> None:
    """Persist turn context metadata."""

    ctx = extract_turn_context(context.payload)
    context.conn.execute(
        """
        INSERT INTO turn_context_messages (
            prompt_id, timestamp, writable_roots, raw_json
        ) VALUES (?, ?, ?, ?)
        """,
        (
            context.prompt_id,
            context.timestamp,
            ctx["writable_roots"],
            json_dumps(context.raw),
        ),
    )


def insert_agent_reasoning(context: AgentReasoningInsert) -> None:
    """Persist agent reasoning content."""

    text = get_reasoning_text(context.payload)
    context.conn.execute(
        """
        INSERT INTO agent_reasoning_messages (
            prompt_id, timestamp, source, text, raw_json
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            context.prompt_id,
            context.timestamp,
            context.source,
            text,
            json_dumps(context.raw),
        ),
    )


def insert_function_plan(context: EventInsert) -> None:
    """Persist update_plan function calls."""

    context.conn.execute(
        """
        INSERT INTO function_plan_messages (
            prompt_id, timestamp, name, arguments, raw_json
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            context.prompt_id,
            context.timestamp,
            context.payload.get("name"),
            context.payload.get("arguments"),
            json_dumps(context.raw),
        ),
    )


def insert_function_call(context: FunctionCallInsert) -> int:
    """Persist function calls (non-update_plan) and return row id."""

    cursor = context.conn.execute(
        """
        INSERT INTO function_calls (
            prompt_id, call_timestamp, output_timestamp, name, call_id,
            arguments, output, raw_call_json, raw_output_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            context.prompt_id,
            context.timestamp,
            None,
            context.payload.get("name"),
            context.payload.get("call_id"),
            context.payload.get("arguments"),
            None,
            json_dumps(context.raw),
            None,
        ),
    )
    return int(cursor.lastrowid)


def update_function_call_output(context: FunctionCallOutputUpdate) -> None:
    """Update the stored function call with output payload details."""

    context.conn.execute(
        """
        UPDATE function_calls
        SET output_timestamp = ?, output = ?, raw_output_json = ?
        WHERE id = ?
        """,
        (
            context.timestamp,
            context.payload.get("output"),
            json_dumps(context.raw),
            context.row_id,
        ),
    )


# Update this tuple when adding/removing exports above.
__all__ = (
    "json_dumps",
    "extract_session_details",
    "extract_token_fields",
    "extract_turn_context",
    "get_reasoning_text",
    "parse_prompt_message",
    "SessionInsert",
    "PromptInsert",
    "EventInsert",
    "AgentReasoningInsert",
    "FunctionCallInsert",
    "FunctionCallOutputUpdate",
    "insert_session",
    "insert_prompt",
    "insert_token",
    "insert_turn_context",
    "insert_agent_reasoning",
    "insert_function_plan",
    "insert_function_call",
    "update_function_call_output",
    "SAFE_COLUMNS",
)
