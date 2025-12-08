"""Tests for db_utils and event_handlers helpers (AI-assisted by Codex GPT-5)."""

# pylint: disable=import-error

from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path

import pytest

from src.parsers.handlers.db_utils import (
    AgentReasoningInsert,
    EventInsert,
    FunctionCallInsert,
    FunctionCallOutputUpdate,
    PromptInsert,
    SessionInsert,
    SAFE_COLUMNS,
    UnsafeColumnError,
    extract_session_details,
    extract_token_fields,
    extract_turn_context,
    get_reasoning_text,
    extract_tag_value,
    insert_agent_reasoning,
    insert_event,
    insert_function_call,
    insert_function_plan,
    update_function_call_output,
    insert_prompt,
    insert_session,
    insert_token,
    insert_turn_context,
    parse_prompt_message,
    safe_value,
    validate_safe_column,
)
from src.parsers.handlers.event_handlers import (
    EventContext,
    EventHandlerDeps,
    FunctionCallTracker,
    handle_event_msg,
    handle_response_item_event,
    handle_turn_context_event,
)
from src.services.ingest import build_event_handler_deps
from src.services.database import ensure_schema, get_connection

TC = unittest.TestCase()


def _make_connection(tmp_path: Path) -> sqlite3.Connection:
    """Create SQLite connection with schema for handler/db_utils tests."""

    conn = get_connection(tmp_path / "test.sqlite")
    ensure_schema(conn)
    return conn


def _create_file_and_prompt(conn: sqlite3.Connection, message: str) -> tuple[int, int]:
    """Insert a file row and prompt row for downstream insert helpers."""

    file_id = conn.execute(
        "INSERT INTO files (path) VALUES (?)",
        ("tests/fixtures/codex_sample_session.jsonl",),
    ).lastrowid
    if file_id is None:
        raise RuntimeError("Failed to insert file row")
    prompt_id = insert_prompt(
        PromptInsert(
            conn=conn,
            file_id=int(file_id),
            prompt_index=1,
            timestamp="2025-10-31T10:00:01Z",
            message=message,
            raw={"message": message},
        )
    )
    return int(file_id), prompt_id


def test_safe_value_allowlist() -> None:
    """Validate column allowlist handling."""

    TC.assertEqual(safe_value("message", "ok"), "ok")
    with pytest.raises(UnsafeColumnError):
        validate_safe_column("bad_column")


def test_validate_safe_column_exhaustive_and_case_sensitive() -> None:
    """All SAFE_COLUMNS should pass; unknown and mixed-case should fail."""

    for column in SAFE_COLUMNS:
        validate_safe_column(column)

    for column in ("Message", "file_id", "prompt_id", "drop table"):
        with pytest.raises(UnsafeColumnError):
            validate_safe_column(column)

    # Regression: ensure user-supplied values containing SQL do not alter queries
    value = "ok'; DROP TABLE prompts;--"
    TC.assertEqual(safe_value("message", value), value)


def test_function_call_tracker_resolve_branches() -> None:
    """FunctionCallTracker should resolve by id, then queue, then None."""

    tracker = FunctionCallTracker()
    tracker.register("id-1", 10)
    tracker.register(None, 20)

    TC.assertEqual(tracker.resolve("id-1"), 10)
    TC.assertEqual(tracker.resolve(None), 20)
    TC.assertIsNone(tracker.resolve("missing"))


def test_function_call_tracker_prefers_id_over_queue() -> None:
    """Resolve should prefer explicit id even when queue has entries."""

    tracker = FunctionCallTracker()
    tracker.register(None, 1)
    tracker.register("abc", 2)

    TC.assertEqual(tracker.resolve("abc"), 2)
    TC.assertEqual(tracker.queue, [1])


def test_handle_event_msg_unknown_subtype(tmp_path: Path) -> None:
    """Unknown event_msg subtype should not alter counts."""

    conn = _make_connection(tmp_path)
    file_id, prompt_id = _create_file_and_prompt(conn, "## My request for Codex:\nTest")
    deps = _deps_with_real_inserts()
    counts: dict[str, int] = {"agent_reasoning_messages": 0, "token_messages": 0}

    event = EventContext(
        conn=conn,
        file_id=file_id,
        prompt_id=prompt_id,
        timestamp="t1",
        payload={"type": "unknown"},
        raw_event={"type": "event_msg"},
        counts=counts,
    )
    handle_event_msg(deps, event)
    TC.assertEqual(counts["agent_reasoning_messages"], 0)
    TC.assertEqual(counts["token_messages"], 0)
    conn.close()


def test_parse_and_extract_helpers() -> None:
    """Ensure parsing utilities normalize expected structures."""

    message = (
        "## Active file: src/main.py\n"
        "## Open tabs:\n- tab1\n- tab2\n"
        "## My request for Codex:\nHelp me test\n"
    )
    active_file, open_tabs, my_request = parse_prompt_message(message)
    TC.assertEqual(active_file, "src/main.py")
    open_tabs_value = open_tabs or ""
    my_request_value = my_request or ""
    TC.assertIn("tab1", open_tabs_value)
    TC.assertIn("tab2", open_tabs_value)
    TC.assertIn("Help me test", my_request_value)

    prelude = [
        {
            "type": "session_meta",
            "timestamp": "t1",
            "payload": {"id": "sid", "cwd": "C:/workspace"},
        },
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "content": [
                    {
                        "text": (
                            "<environment_context><cwd>C:/proj</cwd>"
                            "<approval_policy>never</approval_policy>"
                            "<sandbox_mode>danger-full-access</sandbox_mode>"
                            "<network_access>enabled</network_access></environment_context>"
                        )
                    }
                ],
            },
        },
    ]
    details = extract_session_details(prelude)
    TC.assertEqual(details["session_id"], "sid")
    TC.assertEqual(details["cwd"], "C:/proj")
    TC.assertEqual(details["approval_policy"], "never")
    TC.assertEqual(details["sandbox_mode"], "danger-full-access")
    TC.assertEqual(details["network_access"], "enabled")

    token_fields = extract_token_fields(
        {
            "rate_limits": {
                "primary": {"used_percent": 1, "window_minutes": 60, "resets_at": 123}
            }
        }
    )
    TC.assertEqual(token_fields["primary_used_percent"], 1)
    TC.assertIsNone(token_fields["secondary_used_percent"])

    turn_ctx = extract_turn_context(
        {
            "cwd": "/w",
            "approval_policy": "never",
            "sandbox_policy": {"mode": "rw", "writable_roots": ["a", "b"]},
        }
    )
    TC.assertEqual(turn_ctx["sandbox_mode"], "rw")
    TC.assertIn("a, b", turn_ctx["writable_roots"])

    TC.assertEqual(get_reasoning_text({"text": "direct"}), "direct")
    TC.assertEqual(
        get_reasoning_text({"summary": [{"text": "from summary"}]}), "from summary"
    )
    TC.assertEqual(get_reasoning_text({"content": "fallback"}), "fallback")
    TC.assertIsNone(get_reasoning_text({}))
    TC.assertIsNone(get_reasoning_text({"summary": []}))
    TC.assertIsNone(extract_tag_value("no tags here", "cwd"))
    TC.assertIsNone(extract_tag_value("<cwd>missing end", "cwd"))
    TC.assertEqual(
        extract_tag_value("<cwd>nested<cwd>inner</cwd></cwd>", "cwd"),
        "nested<cwd>inner",
    )
    TC.assertEqual(parse_prompt_message(None), (None, None, None))
    TC.assertEqual(parse_prompt_message(""), (None, None, None))
    TC.assertEqual(parse_prompt_message("No headers here"), (None, None, None))


def test_parse_prompt_message_handles_state_resets() -> None:
    """Ensure open tabs parsing stops on blanks or new headers."""
    message = (
        "## Open tabs:\n- tab1\n\n"
        "## My request for Codex:\nLine1\n"
        "## Other header:\nIgnored\n"
    )
    active_file, open_tabs, my_request = parse_prompt_message(message)
    TC.assertIsNone(active_file)
    open_tabs_value = open_tabs or ""
    my_request_value = my_request or ""
    TC.assertEqual(open_tabs_value, "tab1")
    TC.assertIn("Line1", my_request_value)


def test_parse_prompt_message_with_irregular_bullets() -> None:
    """Parse prompt message with mixed bullet and inline tab entries."""

    message = (
        "## Active file: README.md\n"
        "## Open tabs:\n"
        "- tab1.md\n"
        "tab2.md\n"
        "## My request for Codex:\n"
        "Line 1\n"
        "Line 2\n"
    )
    active_file, open_tabs, my_request = parse_prompt_message(message)
    TC.assertEqual(active_file, "README.md")
    TC.assertIn("tab1.md", open_tabs or "")
    TC.assertIn("tab2.md", open_tabs or "")
    TC.assertIn("Line 1", my_request or "")
    TC.assertIn("Line 2", my_request or "")


def test_insert_helpers_persist_rows(tmp_path: Path) -> None:
    """Exercise db_utils insert helpers end-to-end."""

    conn = _make_connection(tmp_path)
    message = (
        "## Active file: src/main.py\n"
        "## Open tabs:\n- tab1\n- tab2\n"
        "## My request for Codex:\nHelp me test\n"
    )
    file_id, prompt_id = _create_file_and_prompt(conn, message)

    insert_session(
        SessionInsert(
            conn=conn,
            file_id=file_id,
            prelude=[
                {
                    "type": "session_meta",
                    "payload": {"id": "sid", "cwd": "C:/workspace"},
                }
            ],
        )
    )
    insert_event(
        EventInsert(
            conn=conn,
            file_id=file_id,
            prompt_id=prompt_id,
            timestamp="2025-10-31T10:00:02Z",
            payload={"type": "event_msg", "priority": "high", "category": "test"},
            raw={"raw": True},
        )
    )
    insert_token(
        EventInsert(
            conn=conn,
            file_id=file_id,
            prompt_id=prompt_id,
            timestamp="2025-10-31T10:00:03Z",
            payload={
                "type": "token_count",
                "rate_limits": {
                    "primary": {
                        "used_percent": 50,
                        "window_minutes": 60,
                        "resets_at": 111,
                    }
                },
            },
            raw={"raw": True},
        )
    )
    insert_turn_context(
        EventInsert(
            conn=conn,
            file_id=file_id,
            prompt_id=prompt_id,
            timestamp="2025-10-31T10:00:04Z",
            payload={
                "cwd": "C:/workspace",
                "approval_policy": "never",
                "sandbox_policy": {"mode": "r"},
            },
            raw={"raw": True},
        )
    )
    insert_agent_reasoning(
        AgentReasoningInsert(
            conn=conn,
            file_id=file_id,
            prompt_id=prompt_id,
            timestamp="2025-10-31T10:00:05Z",
            payload={"text": "thinking"},
            raw={"raw": True},
            source="agent_message",
        )
    )
    insert_function_plan(
        EventInsert(
            conn=conn,
            file_id=file_id,
            prompt_id=prompt_id,
            timestamp="2025-10-31T10:00:06Z",
            payload={"name": "update_plan", "arguments": "{}"},
            raw={"raw": True},
        )
    )
    call_id = insert_function_call(
        FunctionCallInsert(
            conn=conn,
            file_id=file_id,
            prompt_id=prompt_id,
            timestamp="2025-10-31T10:00:07Z",
            payload={"name": "shell_command", "call_id": "123", "arguments": "{}"},
            raw={"raw": True},
        )
    )
    update_function_call_output(
        FunctionCallOutputUpdate(
            conn=conn,
            row_id=call_id,
            timestamp="2025-10-31T10:00:08Z",
            payload={"output": "done"},
            raw={"raw": True},
        )
    )

    TC.assertEqual(conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 1)
    TC.assertEqual(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0], 1)
    TC.assertEqual(conn.execute("SELECT COUNT(*) FROM token_messages").fetchone()[0], 1)
    TC.assertEqual(
        conn.execute("SELECT COUNT(*) FROM turn_context_messages").fetchone()[0], 1
    )
    TC.assertEqual(
        conn.execute("SELECT COUNT(*) FROM agent_reasoning_messages").fetchone()[0], 1
    )
    TC.assertEqual(
        conn.execute("SELECT COUNT(*) FROM function_plan_messages").fetchone()[0], 1
    )
    output = conn.execute(
        "SELECT output FROM function_calls WHERE id = ?", (call_id,)
    ).fetchone()[0]
    TC.assertEqual(output, "done")

    conn.close()


def test_database_schema_enforces_foreign_keys(tmp_path: Path) -> None:
    """ensure_schema should enforce FK constraints and be idempotent."""

    conn = get_connection(tmp_path / "fk.sqlite")
    ensure_schema(conn)
    ensure_schema(conn)  # idempotent
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO prompts (file_id, prompt_index) VALUES (?, ?)",
            (999, 1),
        )
    conn.close()


def _deps_with_real_inserts() -> EventHandlerDeps:
    """Create EventHandlerDeps wired to real db_utils inserts."""

    return build_event_handler_deps()


def test_insert_function_call_stores_call_fields(tmp_path: Path) -> None:
    """insert_function_call should persist function call data and raw JSON."""

    conn = _make_connection(tmp_path)
    file_id, prompt_id = _create_file_and_prompt(conn, "## My request for Codex:\nCall")

    payload = {"name": "shell_command", "call_id": "abc123", "arguments": "{foo:1}"}
    raw = {"raw": "data", "payload": payload}
    row_id = insert_function_call(
        FunctionCallInsert(
            conn=conn,
            file_id=file_id,
            prompt_id=prompt_id,
            timestamp="t1",
            payload=payload,
            raw=raw,
        )
    )

    row = conn.execute(
        """
        SELECT name, call_id, arguments, output, raw_call_json
        FROM function_calls
        WHERE id = ?
        """,
        (row_id,),
    ).fetchone()
    TC.assertEqual(row[0], "shell_command")
    TC.assertEqual(row[1], "abc123")
    TC.assertEqual(row[2], "{foo:1}")
    TC.assertIsNone(row[3])
    TC.assertIn("raw", row[4])
    conn.close()


def test_handle_event_msg_branches(tmp_path: Path) -> None:
    """Cover event_msg subtypes and counts."""

    conn = _make_connection(tmp_path)
    file_id, prompt_id = _create_file_and_prompt(conn, "## My request for Codex:\nTest")
    deps = _deps_with_real_inserts()
    counts: dict[str, int] = {
        "token_messages": 0,
        "agent_reasoning_messages": 0,
        "events": 0,
    }

    token_event = EventContext(
        conn=conn,
        file_id=file_id,
        prompt_id=prompt_id,
        timestamp="t1",
        payload={"type": "token_count"},
        raw_event={"type": "event_msg"},
        counts=counts,
    )
    handle_event_msg(deps, token_event)

    for subtype in ("agent_reasoning", "turn_aborted", "agent_message"):
        handle_event_msg(
            deps,
            EventContext(
                conn=conn,
                file_id=file_id,
                prompt_id=prompt_id,
                timestamp="t2",
                payload={"type": subtype, "text": subtype},
                raw_event={"type": "event_msg"},
                counts=counts,
            ),
        )

    TC.assertEqual(counts["token_messages"], 1)
    TC.assertEqual(counts["agent_reasoning_messages"], 3)
    conn.close()


def test_handle_event_msg_unknown_type_no_op(tmp_path: Path) -> None:
    """Unknown subtype should not increment counts or crash."""

    conn = _make_connection(tmp_path)
    file_id, prompt_id = _create_file_and_prompt(conn, "## My request for Codex:\nTest")
    deps = _deps_with_real_inserts()
    counts: dict[str, int] = {"agent_reasoning_messages": 0, "token_messages": 0}
    event = EventContext(
        conn=conn,
        file_id=file_id,
        prompt_id=prompt_id,
        timestamp="t0",
        payload={"type": "unknown"},
        raw_event={"type": "event_msg"},
        counts=counts,
    )
    handle_event_msg(deps, event)
    TC.assertEqual(counts["agent_reasoning_messages"], 0)
    TC.assertEqual(counts["token_messages"], 0)
    conn.close()


def test_handle_turn_context_event(tmp_path: Path) -> None:
    """Validate turn_context handling and counter update."""

    conn = _make_connection(tmp_path)
    file_id, prompt_id = _create_file_and_prompt(conn, "## My request for Codex:\nTest")
    deps = _deps_with_real_inserts()
    counts: dict[str, int] = {"turn_context_messages": 0}
    handle_turn_context_event(
        deps,
        EventContext(
            conn=conn,
            file_id=file_id,
            prompt_id=prompt_id,
            timestamp="t3",
            payload={"sandbox_policy": {"mode": "r"}},
            raw_event={"type": "turn_context"},
            counts=counts,
        ),
    )
    TC.assertEqual(counts["turn_context_messages"], 1)
    conn.close()


def test_handle_response_item_event_calls_and_outputs(tmp_path: Path) -> None:
    """Cover function_call, function_call_output (with/without call_id), and reasoning skip."""

    conn = _make_connection(tmp_path)
    file_id, prompt_id = _create_file_and_prompt(conn, "## My request for Codex:\nTest")
    deps = _deps_with_real_inserts()
    tracker = FunctionCallTracker()
    counts: dict[str, int] = {"function_calls": 0, "function_plan_messages": 0}

    # skip reasoning
    handle_response_item_event(
        deps,
        EventContext(
            conn=conn,
            file_id=file_id,
            prompt_id=prompt_id,
            timestamp="t4",
            payload={"type": "reasoning"},
            raw_event={"type": "response_item"},
            counts=counts,
        ),
        tracker,
    )
    TC.assertEqual(counts["function_calls"], 0)

    # function_call -> registers
    handle_response_item_event(
        deps,
        EventContext(
            conn=conn,
            file_id=file_id,
            prompt_id=prompt_id,
            timestamp="t5",
            payload={
                "type": "function_call",
                "name": "shell_command",
                "call_id": "abc",
                "arguments": "{}",
            },
            raw_event={"type": "response_item"},
            counts=counts,
        ),
        tracker,
    )
    TC.assertEqual(counts["function_calls"], 1)

    # function_call_output with matching id
    handle_response_item_event(
        deps,
        EventContext(
            conn=conn,
            file_id=file_id,
            prompt_id=prompt_id,
            timestamp="t6",
            payload={
                "type": "function_call_output",
                "call_id": "abc",
                "output": "done",
            },
            raw_event={"type": "response_item"},
            counts=counts,
        ),
        tracker,
    )

    # function_call_output without call id queues a new call
    handle_response_item_event(
        deps,
        EventContext(
            conn=conn,
            file_id=file_id,
            prompt_id=prompt_id,
            timestamp="t7",
            payload={"type": "function_call_output", "output": "queued"},
            raw_event={"type": "response_item"},
            counts=counts,
        ),
        tracker,
    )

    # second output with no call id should consume queued call
    handle_response_item_event(
        deps,
        EventContext(
            conn=conn,
            file_id=file_id,
            prompt_id=prompt_id,
            timestamp="t9",
            payload={"type": "function_call_output", "output": "updated"},
            raw_event={"type": "response_item"},
            counts=counts,
        ),
        tracker,
    )

    # update_plan path
    handle_response_item_event(
        deps,
        EventContext(
            conn=conn,
            file_id=file_id,
            prompt_id=prompt_id,
            timestamp="t8",
            payload={"type": "function_call", "name": "update_plan", "arguments": "{}"},
            raw_event={"type": "response_item"},
            counts=counts,
        ),
        tracker,
    )
    TC.assertEqual(counts["function_plan_messages"], 1)
    TC.assertEqual(counts["function_calls"], 2)  # includes queued call

    outputs = conn.execute("SELECT output FROM function_calls ORDER BY id").fetchall()
    TC.assertEqual({row[0] for row in outputs}, {"done", "updated"})
    conn.close()


def test_handle_response_item_event_unknown_subtype(tmp_path: Path) -> None:
    """handle_response_item_event should gracefully skip unknown subtypes."""
    conn = _make_connection(tmp_path)
    file_id, prompt_id = _create_file_and_prompt(conn, "## Test")
    deps = _deps_with_real_inserts()
    tracker = FunctionCallTracker()
    counts: dict[str, int] = {"function_calls": 0}

    # Unknown subtype should be silently ignored
    handle_response_item_event(
        deps,
        EventContext(
            conn=conn,
            file_id=file_id,
            prompt_id=prompt_id,
            timestamp="t0",
            payload={"type": "unknown_type", "data": "some value"},
            raw_event={"type": "response_item"},
            counts=counts,
        ),
        tracker,
    )

    # No function calls should be created
    TC.assertEqual(counts["function_calls"], 0)
    conn.close()


def test_record_agent_reasoning_sources(tmp_path: Path) -> None:
    """_record_agent_reasoning should store different sources."""

    conn = _make_connection(tmp_path)
    file_id, prompt_id = _create_file_and_prompt(conn, "## My request for Codex:\nTest")
    deps = _deps_with_real_inserts()
    counts: dict[str, int] = {"agent_reasoning_messages": 0}

    for subtype in ("agent_reasoning", "turn_aborted", "agent_message"):
        handle_event_msg(
            deps,
            EventContext(
                conn=conn,
                file_id=file_id,
                prompt_id=prompt_id,
                timestamp="t2",
                payload={"type": subtype, "text": subtype},
                raw_event={"type": "event_msg"},
                counts=counts,
            ),
        )
    TC.assertEqual(
        conn.execute("SELECT COUNT(*) FROM agent_reasoning_messages").fetchone()[0], 3
    )
    conn.close()
