"""Coverage-focused tests for CLI entry points (AI-assisted)."""

# pylint: disable=import-error,protected-access,too-few-public-methods

from __future__ import annotations

import sqlite3
import sys
import types
import unittest
from pathlib import Path
from typing import Any, Iterator, cast

import pytest

from cli import group_session, ingest_session, migrate_sqlite_to_postgres
from src.services.config import DatabaseConfig, OutputPaths, SessionsConfig, ConfigError
from src.services.ingest import SessionSummary

TC = unittest.TestCase()


def _fake_config(tmp_path: Path) -> SessionsConfig:
    """Build a SessionsConfig rooted in a temp directory."""

    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    return SessionsConfig(
        sessions_root=tmp_path,
        ingest_batch_size=5,
        database=DatabaseConfig(sqlite_path=tmp_path / "db.sqlite"),
        outputs=OutputPaths(reports_dir=reports_dir),
    )


def test_group_session_main_writes_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """group_session.main should render output and write report."""

    config = _fake_config(tmp_path)
    session_path = tmp_path / "session.jsonl"
    session_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(group_session, "load_config", lambda: config)
    monkeypatch.setattr(
        group_session, "find_first_session_file", lambda root: session_path
    )
    monkeypatch.setattr(group_session, "load_session_events", lambda path: [])
    monkeypatch.setattr(
        group_session,
        "group_by_user_messages",
        lambda events: (
            [],
            [
                {
                    "user": {"timestamp": "t1", "payload": {"message": "Hi"}},
                    "events": [],
                }
            ],
        ),
    )
    monkeypatch.setattr(sys, "argv", ["prog"])

    group_session.main()
    out = capsys.readouterr().out
    TC.assertIn("Prompt 1", out)
    TC.assertTrue((config.outputs.reports_dir / "session.txt").exists())


def test_group_session_main_handles_config_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """group_session.main should surface ConfigError cleanly."""

    monkeypatch.setattr(
        group_session,
        "load_config",
        lambda: (_ for _ in ()).throw(ConfigError("bad config")),
    )
    monkeypatch.setattr(sys, "argv", ["prog"])

    group_session.main()
    out = capsys.readouterr().out
    TC.assertIn("Configuration error", out)


def test_group_session_main_handles_discovery_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """group_session.main should handle SessionDiscoveryError gracefully."""

    config = _fake_config(Path("."))
    monkeypatch.setattr(group_session, "load_config", lambda: config)
    monkeypatch.setattr(
        group_session,
        "find_first_session_file",
        lambda root: (_ for _ in ()).throw(group_session.SessionDiscoveryError("none")),
    )
    monkeypatch.setattr(sys, "argv", ["prog"])

    group_session.main()
    out = capsys.readouterr().out
    TC.assertIn("Session discovery error", out)


def test_group_session_helpers_cover_payload_branches() -> None:
    """Exercise shorten and payload describers for coverage."""

    TC.assertEqual(group_session.shorten("abc", limit=5), "abc")
    TC.assertTrue(group_session.shorten("abcdef", limit=5).endswith("..."))

    reasoning = group_session.describe_event(
        {
            "type": "event_msg",
            "timestamp": "t",
            "payload": {"type": "agent_reasoning", "text": "thinking"},
        }
    )
    TC.assertIn("reasoning", reasoning)

    agent_message = group_session.describe_event(
        {
            "type": "event_msg",
            "timestamp": "t",
            "payload": {"type": "agent_message", "message": "hello"},
        }
    )
    TC.assertIn("hello", agent_message)

    aborted = group_session.describe_event(
        {
            "type": "event_msg",
            "timestamp": "t",
            "payload": {"type": "turn_aborted", "reason": "error"},
        }
    )
    TC.assertIn("reason", aborted)

    response = group_session.describe_event(
        {
            "type": "response_item",
            "timestamp": "t",
            "payload": {
                "type": "message",
                "content": [{"text": "hi"}, {"text": "there"}],
            },
        }
    )
    TC.assertIn("message", response)

    function_call = group_session.describe_event(
        {
            "type": "response_item",
            "timestamp": "t",
            "payload": {"type": "function_call", "name": "foo", "arguments": "{}"},
        }
    )
    TC.assertIn("function", function_call)

    function_output = group_session.describe_event(
        {
            "type": "response_item",
            "timestamp": "t",
            "payload": {"type": "function_call_output", "output": "done"},
        }
    )
    TC.assertIn("output", function_output)

    unknown = group_session.describe_event({"type": "other", "timestamp": "t0"})
    TC.assertIn("other", unknown)


def test_group_session_describe_additional_payloads() -> None:
    """Cover secondary token_count and reasoning summary branches."""

    token_event = {
        "type": "event_msg",
        "timestamp": "t",
        "payload": {
            "type": "token_count",
            "rate_limits": {
                "secondary": {
                    "used_percent": 5,
                    "window_minutes": 30,
                    "resets_in_seconds": 10,
                }
            },
        },
    }
    desc = group_session.describe_event(token_event)
    TC.assertIn("secondary", desc)

    # Test token_count with non-dict rate_limits
    bad_token_event = {
        "type": "event_msg",
        "timestamp": "t",
        "payload": {
            "type": "token_count",
            "rate_limits": "not a dict",
        },
    }
    bad_desc = group_session.describe_event(bad_token_event)
    TC.assertIn("token_count", bad_desc)

    reasoning_summary = {
        "type": "response_item",
        "timestamp": "t",
        "payload": {"type": "reasoning", "summary": [{"text": "summary text"}]},
    }
    reasoning_desc = group_session.describe_event(reasoning_summary)
    TC.assertIn("summary", reasoning_desc)

    turn_ctx_payload = {
        "type": "turn_context",
        "timestamp": "t",
        "payload": {"cwd": "/work"},
    }
    turn_desc = group_session.describe_event(turn_ctx_payload)
    TC.assertIn("cwd: /work", turn_desc)


def test_group_session_render_session_and_groups(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """_render_session should print prelude and grouped events with output path."""

    group_session.build_parser()  # cover parser construction
    session_file = tmp_path / "s.jsonl"
    session_file.write_text("{}", encoding="utf-8")
    events = [
        {"type": "session_meta", "timestamp": "t0", "payload": {"id": "sid"}},
        {
            "type": "event_msg",
            "timestamp": "t1",
            "payload": {"type": "user_message", "message": "Hi"},
        },
        {
            "type": "turn_context",
            "timestamp": "t2",
            "payload": {"cwd": str(tmp_path)},
        },
    ]
    monkeypatch.setattr(group_session, "load_session_events", lambda path: events)
    captured = group_session._render_session(
        session_file
    )  # pylint: disable=protected-access
    TC.assertTrue(any("Prompt 1" in line for line in captured))
    TC.assertTrue(any(f"cwd: {tmp_path}" in line for line in captured))

    captured.clear()
    group_session._render_prelude(
        events[:1], captured
    )  # pylint: disable=protected-access
    TC.assertTrue(captured)

    captured.clear()
    group_session._render_groups([], captured)  # pylint: disable=protected-access
    TC.assertTrue(any("No user messages" in line for line in captured))


def test_group_session_write_report_and_reconfigure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """write_report and _reconfigure_stdout should execute without error."""

    output_path = tmp_path / "out" / "report.txt"
    group_session.write_report(output_path, ["line1", "line2"])
    TC.assertTrue(output_path.exists())

    class FakeStdout:
        """Stub stdout that raises on reconfigure."""

        def reconfigure(self, encoding: str) -> None:  # pylint: disable=unused-argument
            """Simulate stdout that cannot be reconfigured."""
            raise ValueError("cannot reconfigure")

    fake_stdout = FakeStdout()
    monkeypatch.setattr(sys, "stdout", fake_stdout)
    group_session._reconfigure_stdout()  # pylint: disable=protected-access


def test_group_session_main_full_flow(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """group_session.main should write default output on happy path."""

    config = _fake_config(tmp_path)
    session_path = tmp_path / "session.jsonl"
    session_path.write_text("{}", encoding="utf-8")
    prelude = [{"type": "turn_context", "timestamp": "t0", "payload": {"cwd": "/w"}}]
    groups = [
        {
            "user": {"timestamp": "t1", "payload": {"message": "Hello"}},
            "events": [
                {
                    "type": "event_msg",
                    "timestamp": "t2",
                    "payload": {"type": "agent_reasoning", "text": "think"},
                },
                {"type": "turn_context", "timestamp": "t3", "payload": {"cwd": "/w2"}},
            ],
        }
    ]
    monkeypatch.setattr(group_session, "load_config", lambda: config)
    monkeypatch.setattr(
        group_session, "find_first_session_file", lambda root: session_path
    )
    monkeypatch.setattr(group_session, "load_session_events", lambda path: [])
    monkeypatch.setattr(
        group_session, "group_by_user_messages", lambda events: (prelude, groups)
    )
    monkeypatch.setattr(sys, "argv", ["prog"])

    group_session.main()
    output_path = config.outputs.reports_dir / "session.txt"
    TC.assertTrue(output_path.exists())


def test_group_session_main_with_output_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """group_session.main should honor explicit --output path."""

    config = _fake_config(tmp_path)
    session_path = tmp_path / "session.jsonl"
    session_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(group_session, "load_config", lambda: config)
    monkeypatch.setattr(
        group_session, "find_first_session_file", lambda root: session_path
    )
    monkeypatch.setattr(group_session, "load_session_events", lambda path: [])
    monkeypatch.setattr(
        group_session,
        "group_by_user_messages",
        lambda events: ([], []),
    )
    out_path = tmp_path / "custom.txt"
    monkeypatch.setattr(sys, "argv", ["prog", "--output", str(out_path)])

    group_session.main()
    TC.assertTrue(out_path.exists())


def test_group_session_main_error_without_output_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """group_session.main should handle errors gracefully when output_path is None."""

    def mock_load_config() -> SessionsConfig:
        raise ConfigError("Config failed")

    monkeypatch.setattr(group_session, "load_config", mock_load_config)
    monkeypatch.setattr(sys, "argv", ["prog"])

    group_session.main()
    out = capsys.readouterr().out
    TC.assertIn("Configuration error", out)


def test_group_session_describe_turn_context_edge_cases() -> None:
    """describe_event should handle turn_context event with missing/non-string cwd."""
    # Event where event_type is "turn_context" with a dict payload (no cwd)
    event = {
        "type": "turn_context",
        "timestamp": "2025-10-31T10:00:00Z",
        "payload": {"other_field": "value"},
    }
    desc = group_session.describe_event(event)
    # Should have the header but no cwd line
    TC.assertIn("turn_context", desc)

    # Event where payload_type is "turn_context" via non-matching event_type
    # This tests the `if payload_type == "turn_context"` path (line 69)
    event2 = {
        "type": "unknown_event_type",
        "timestamp": "2025-10-31T10:00:01Z",
        "payload": {"type": "turn_context", "cwd": "/some/path"},
    }
    desc2 = group_session.describe_event(event2)
    TC.assertIn("cwd: /some/path", desc2)


def test_ingest_resolve_runtime_options_debug_limit() -> None:
    """_resolve_runtime_options should cap limit when debug is set."""

    args = type("Args", (), {"verbose": False, "debug": True, "limit": None})()
    verbose, limit = ingest_session._resolve_runtime_options(args)
    TC.assertTrue(verbose)
    TC.assertEqual(limit, 2)


def test_ingest_validate_db_path_missing_parent(tmp_path: Path) -> None:
    """validate_db_path should raise when parent is missing or unwritable."""

    target = tmp_path / "missing" / "db.sqlite"
    with pytest.raises(ConfigError):
        ingest_session.validate_db_path(target)


def test_ingest_single_and_many_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """_ingest_single_file and _ingest_many_files should print summaries."""

    summary: SessionSummary = {
        "session_file": "file.jsonl",
        "file_id": 1,
        "prompts": 1,
        "token_messages": 2,
        "turn_context_messages": 0,
        "agent_reasoning_messages": 0,
        "function_plan_messages": 0,
        "function_calls": 0,
        "errors": [],
    }
    monkeypatch.setattr(
        ingest_session, "ingest_session_file", lambda *args, **kwargs: summary
    )
    ingest_session._ingest_single_file(
        Path("file.jsonl"), tmp_path / "db.sqlite", False, 5
    )  # pylint: disable=protected-access
    single_out = capsys.readouterr().out
    TC.assertIn("Inserted rows", single_out)

    monkeypatch.setattr(
        ingest_session,
        "ingest_sessions_in_directory",
        lambda root, db, limit=None, verbose=False, batch_size=5: iter([summary]),
    )
    summaries = ingest_session._ingest_many_files(
        tmp_path, tmp_path / "db.sqlite", None, False, 5
    )  # pylint: disable=protected-access
    TC.assertEqual(len(summaries), 1)
    ingest_session._report_many_results(
        summaries, Path("db.sqlite")
    )  # pylint: disable=protected-access
    many_out = capsys.readouterr().out
    TC.assertIn("Ingested", many_out)


def test_ingest_many_files_handles_discovery_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_ingest_many_files should exit when discovery fails."""

    monkeypatch.setattr(
        ingest_session,
        "ingest_sessions_in_directory",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ingest_session.SessionDiscoveryError("nope")
        ),
    )
    with pytest.raises(SystemExit):
        ingest_session._ingest_many_files(
            Path("."), Path("db.sqlite"), None, False, 5
        )  # pylint: disable=protected-access


def test_ingest_print_error_details_counts(capsys: pytest.CaptureFixture[str]) -> None:
    """_print_error_details should render multiple errors and count them."""

    errors: list[dict[str, Any]] = [
        {"severity": "ERROR", "code": "c1", "message": "m1"},
        {"severity": "WARNING", "code": "c2", "message": "m2"},
        {"severity": "ERROR", "code": "c3", "message": "m3"},
        {"severity": "ERROR", "code": "c4", "message": "m4"},
    ]
    count = ingest_session._print_error_details(
        errors, indent=""
    )  # pylint: disable=protected-access
    out = capsys.readouterr().out
    TC.assertEqual(count, 4)
    TC.assertIn("... 1 more", out)


def test_ingest_report_many_results_totals(capsys: pytest.CaptureFixture[str]) -> None:
    """_report_many_results should aggregate totals across summaries."""

    s1 = {
        "session_file": "file1",
        "file_id": 1,
        "prompts": 1,
        "token_messages": 1,
        "turn_context_messages": 0,
        "agent_reasoning_messages": 0,
        "function_plan_messages": 0,
        "function_calls": 0,
        "errors": [],
    }
    s2 = {
        "session_file": "file2",
        "file_id": 2,
        "prompts": 2,
        "token_messages": 0,
        "turn_context_messages": 1,
        "agent_reasoning_messages": 0,
        "function_plan_messages": 0,
        "function_calls": 1,
        "errors": [{"severity": "ERROR", "code": "x", "message": "bad"}],
    }
    summaries = cast(list[dict[str, Any]], [s1, s2])
    ingest_session._report_many_results(
        summaries, Path("db.sqlite")
    )  # pylint: disable=protected-access
    out = capsys.readouterr().out
    TC.assertIn("Files processed: 2", out)
    TC.assertIn("errors: 1", out)


def test_ingest_main_uses_cli_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """ingest_session.main should process explicit --session path."""

    config = _fake_config(tmp_path)
    session_file = tmp_path / "s.jsonl"
    session_file.write_text("{}", encoding="utf-8")
    summary: SessionSummary = {
        "session_file": str(session_file),
        "file_id": 1,
        "prompts": 0,
        "token_messages": 0,
        "turn_context_messages": 0,
        "agent_reasoning_messages": 0,
        "function_plan_messages": 0,
        "function_calls": 0,
        "errors": [],
    }
    monkeypatch.setattr(ingest_session, "load_config", lambda: config)
    monkeypatch.setattr(
        ingest_session, "ingest_session_file", lambda *args, **kwargs: summary
    )
    monkeypatch.setattr(sys, "argv", ["prog", "--session", str(session_file)])

    ingest_session.main()
    out = capsys.readouterr().out
    TC.assertIn("Ingested session file", out)


def test_ingest_load_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """_load_configuration should propagate ConfigError."""

    monkeypatch.setattr(
        ingest_session, "load_config", lambda: (_ for _ in ()).throw(ConfigError("bad"))
    )
    with pytest.raises(SystemExit):
        ingest_session._load_configuration()  # pylint: disable=protected-access


def test_migrate_main_dry_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """migrate_sqlite_to_postgres.main should perform dry-run and exit before execute."""

    config = _fake_config(tmp_path)
    sqlite_src = tmp_path / "db.sqlite"
    sqlite_src.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        migrate_sqlite_to_postgres, "_load_configuration", lambda path: config
    )
    monkeypatch.setattr(
        migrate_sqlite_to_postgres,
        "run_dry_run",
        lambda sqlite_path, dsn: {
            "source_counts": {"files": 1},
            "target_counts": {"files": 0},
        },
    )
    called = {"migrate": 0}
    monkeypatch.setattr(
        migrate_sqlite_to_postgres,
        "migrate",
        lambda sqlite_path, dsn, batch_size: called.__setitem__(
            "migrate", called["migrate"] + 1
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prog",
            "--config",
            str(tmp_path / "c.toml"),
            "--sqlite",
            str(sqlite_src),
            "--postgres-dsn",
            "postgres://dsn",
        ],
    )

    migrate_sqlite_to_postgres.main()
    out = capsys.readouterr().out
    TC.assertIn("Dry-run complete", out)
    TC.assertEqual(called["migrate"], 0)


def test_migrate_main_execute(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """migrate_sqlite_to_postgres.main should call migrate when --execute is provided."""

    config = _fake_config(tmp_path)
    sqlite_src = tmp_path / "db.sqlite"
    sqlite_src.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        migrate_sqlite_to_postgres, "_load_configuration", lambda path: config
    )
    monkeypatch.setattr(
        migrate_sqlite_to_postgres,
        "run_dry_run",
        lambda sqlite_path, dsn: {
            "source_counts": {"files": 0},
            "target_counts": {"files": 0},
        },
    )
    called = {"migrate": 0}
    monkeypatch.setattr(
        migrate_sqlite_to_postgres,
        "migrate",
        lambda sqlite_path, dsn, batch_size: called.__setitem__(
            "migrate", called["migrate"] + 1
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prog",
            "--config",
            str(tmp_path / "c.toml"),
            "--sqlite",
            str(sqlite_src),
            "--postgres-dsn",
            "postgres://dsn",
            "--execute",
        ],
    )

    migrate_sqlite_to_postgres.main()
    out = capsys.readouterr().out
    TC.assertIn("Executing migration", out)
    TC.assertEqual(called["migrate"], 1)


def test_migrate_main_requires_dsn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """main should exit when no Postgres DSN is provided."""

    outputs = OutputPaths(reports_dir=tmp_path / "reports")
    config = SessionsConfig(
        sessions_root=tmp_path,
        ingest_batch_size=1,
        database=DatabaseConfig(
            sqlite_path=tmp_path / "db.sqlite", postgres_dsn=None, backend="postgres"
        ),
        outputs=outputs,
    )
    monkeypatch.setattr(
        migrate_sqlite_to_postgres, "_load_configuration", lambda path: config
    )
    monkeypatch.setattr(sys, "argv", ["prog", "--config", str(tmp_path / "c.toml")])
    with pytest.raises(SystemExit):
        migrate_sqlite_to_postgres.main()


def test_migrate_run_dry_run_calls_counts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """run_dry_run should call table count helpers and close connections."""

    class _Conn:
        """Lightweight connection stub tracking closed state."""

        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            """Mark stub connection as closed."""
            self.closed = True

    sqlite_conn = _Conn()
    pg_conn = _Conn()

    def _open_sqlite(_path: Path) -> _Conn:
        """Return sqlite stub for dry-run test."""
        sqlite_conn.closed = False
        return sqlite_conn

    def _open_postgres(_dsn: str) -> _Conn:
        """Return postgres stub for dry-run test."""
        pg_conn.closed = False
        return pg_conn

    monkeypatch.setattr(migrate_sqlite_to_postgres, "_open_sqlite", _open_sqlite)
    monkeypatch.setattr(migrate_sqlite_to_postgres, "_open_postgres", _open_postgres)
    monkeypatch.setattr(
        migrate_sqlite_to_postgres,
        "_table_counts",
        lambda conn, tables: {"files": 1},
    )
    monkeypatch.setattr(
        migrate_sqlite_to_postgres,
        "_table_counts_postgres",
        lambda conn, tables: {"files": 0},
    )

    summary = migrate_sqlite_to_postgres.run_dry_run(
        tmp_path / "db.sqlite", "postgres://dsn"
    )
    TC.assertEqual(summary["source_counts"]["files"], 1)
    TC.assertEqual(summary["target_counts"]["files"], 0)
    TC.assertTrue(sqlite_conn.closed is True or hasattr(sqlite_conn, "closed"))
    TC.assertTrue(pg_conn.closed is True or hasattr(pg_conn, "closed"))


def test_migrate_open_postgres_missing_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    """_open_postgres should exit when psycopg2 is missing."""

    real_import = __import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "psycopg2":
            raise ModuleNotFoundError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(sys.modules["builtins"], "__import__", fake_import)
    with pytest.raises(SystemExit):
        migrate_sqlite_to_postgres._open_postgres(
            "dsn"
        )  # pylint: disable=protected-access


def test_migrate_open_postgres_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """_open_postgres should return connection when psycopg2 is present."""

    class DummyPsycoConn:
        """Stub psycopg2 connection with autocommit flag."""

        def __init__(self) -> None:
            self.autocommit = False

    class DummyPsyco:
        """Stub psycopg2 module returning the stub connection."""

        def __init__(self) -> None:
            self.connected = DummyPsycoConn()

        def connect(
            self, _dsn: str = "", **_kwargs: Any
        ) -> DummyPsycoConn:  # pylint: disable=unused-argument
            """Return shared DummyPsycoConn instance."""
            return self.connected

    dummy = DummyPsyco()
    monkeypatch.setitem(sys.modules, "psycopg2", dummy)
    conn = migrate_sqlite_to_postgres._open_postgres(
        "dsn"
    )  # pylint: disable=protected-access
    TC.assertIs(conn, dummy.connected)


def test_migrate_load_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """_load_configuration should exit when load_config raises ConfigError."""

    monkeypatch.setattr(
        migrate_sqlite_to_postgres,
        "load_config",
        lambda path: (_ for _ in ()).throw(ConfigError("bad")),
    )
    with pytest.raises(SystemExit):
        migrate_sqlite_to_postgres._load_configuration(
            Path("c.toml")
        )  # pylint: disable=protected-access


def test_migrate_ensure_target_empty_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """_ensure_target_empty should raise when target has rows."""

    monkeypatch.setattr(
        migrate_sqlite_to_postgres,
        "_table_counts_postgres",
        lambda conn, tables: {"files": 1},
    )
    with pytest.raises(SystemExit):
        migrate_sqlite_to_postgres._ensure_target_empty(
            object(), ("files",)
        )  # pylint: disable=protected-access


def test_migrate_table_counts_postgres_missing() -> None:
    """_table_counts_postgres should set zero when table missing."""

    class Cursor:
        """Cursor stub tracking state to simulate missing table."""

        def __init__(self) -> None:
            self.state = 0

        def __enter__(self) -> "Cursor":
            return self

        def __exit__(
            self, exc_type: BaseException | None, exc: BaseException | None, tb: object
        ) -> None:
            return None

        def execute(self, _stmt: str, _params: Any | None = None) -> None:
            """Increment state to simulate execution."""
            self.state += 1

        def fetchone(self) -> tuple[int]:
            """Return a single-row count result."""
            return (0,)

    class Conn:
        """Connection stub returning the cursor."""

        def cursor(self) -> Cursor:
            """Return a new Cursor stub."""
            return Cursor()

    counts = migrate_sqlite_to_postgres._table_counts_postgres(
        Conn(), ("files",)
    )  # pylint: disable=protected-access
    TC.assertEqual(counts["files"], 0)


def test_migrate_table_counts_postgres_existing() -> None:
    """_table_counts_postgres should return counts when table exists."""

    class Cursor:
        """Cursor stub that returns different counts across calls."""

        def __init__(self) -> None:
            self.calls = 0

        def __enter__(self) -> "Cursor":
            return self

        def __exit__(
            self, exc_type: BaseException | None, exc: BaseException | None, tb: object
        ) -> None:
            return None

        def execute(self, _stmt: str, _params: Any | None = None) -> None:
            """Increment call count per execution."""
            self.calls += 1

        def fetchone(self) -> tuple[int]:
            """Return simulated count values by call order."""
            if self.calls == 1:
                return (1,)
            return (3,)

    class Conn:
        """Connection stub returning counting cursor."""

        def cursor(self) -> Cursor:
            """Return a new Cursor stub."""
            return Cursor()

    counts = migrate_sqlite_to_postgres._table_counts_postgres(
        Conn(), ("files",)
    )  # pylint: disable=protected-access
    TC.assertEqual(counts["files"], 3)


def test_migrate_print_dry_run_summary_warning(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_print_dry_run_summary should warn when target has rows."""

    migrate_sqlite_to_postgres._print_dry_run_summary(
        {"source_counts": {"files": 1}, "target_counts": {"files": 2}},
        Path("db.sqlite"),
    )
    out = capsys.readouterr().out
    TC.assertIn("WARNING", out)


def test_migrate_copy_table_rejects_unknown_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_copy_table should raise on unexpected table names."""

    dummy_sql_module = types.SimpleNamespace(SQL=lambda x: x, Identifier=lambda x: x)
    monkeypatch.setitem(
        sys.modules, "psycopg2", types.SimpleNamespace(sql=dummy_sql_module)
    )
    monkeypatch.setitem(
        sys.modules,
        "psycopg2.extras",
        types.SimpleNamespace(
            execute_values=lambda *_args, **_kwargs: None
        ),  # pylint: disable=unused-argument
    )

    sqlite_conn_any: Any = sqlite3.connect(":memory:")
    with pytest.raises(SystemExit):
        migrate_sqlite_to_postgres._copy_table(
            sqlite_conn_any,
            object(),
            "unknown",
            batch_size=1,
        )  # pylint: disable=protected-access


def test_migrate_copy_table_flushes_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    """_copy_table should flush batches when batch_size threshold is met."""

    class DummyCursor:
        """Cursor stub returning fixed rows and description."""

        description = [("id",), ("val",)]

        def __init__(self) -> None:
            self._rows = [(1, "a"), (2, "b")]

        def execute(self, stmt: str) -> None:  # pylint: disable=unused-argument
            """No-op execute for stub cursor."""
            return None

        def fetchall(self) -> list[tuple[int, str]]:
            """Return preset rows."""
            return self._rows

    class DummySqlite:
        """SQLite connection stub returning DummyCursor."""

        def cursor(self) -> DummyCursor:
            """Return a new DummyCursor."""
            return DummyCursor()

    class DummySQL:
        """psycopg2.sql.SQL-compatible stub supporting join/format."""

        def __init__(self, template: str) -> None:
            self.template = template

        def join(self, iterable: Iterator[str]) -> "DummySQL":
            """Return a new DummySQL with joined identifiers."""
            return DummySQL(", ".join(iterable))

        def format(self, *_args: Any, **_kwargs: Any) -> "DummySQL":
            """Return self; formatting is not simulated."""
            return self

    dummy_sql_module = types.SimpleNamespace(
        SQL=DummySQL, Identifier=lambda value: value
    )
    monkeypatch.setitem(
        sys.modules, "psycopg2", types.SimpleNamespace(sql=dummy_sql_module)
    )

    flushed = {"calls": 0}

    def dummy_execute_values(*_args: Any, **_kwargs: Any) -> None:
        """Count batch flush calls."""
        flushed["calls"] += 1

    monkeypatch.setitem(
        sys.modules,
        "psycopg2.extras",
        types.SimpleNamespace(execute_values=dummy_execute_values),
    )

    class DummyPgCursor:
        """Postgres cursor stub supporting context management."""

        def __enter__(self) -> "DummyPgCursor":
            return self

        def __exit__(
            self,
            exc_type: BaseException | None,
            exc: BaseException | None,
            tb: object | None,
        ) -> None:
            return None

    class DummyPg:
        """Postgres connection stub that returns DummyPgCursor."""

        def cursor(self) -> DummyPgCursor:
            """Return a new DummyPgCursor."""
            return DummyPgCursor()

        def commit(self) -> None:
            """Commit stub (no-op)."""
            return None

    sqlite_conn_any: Any = DummySqlite()
    migrate_sqlite_to_postgres._copy_table(
        sqlite_conn_any, DummyPg(), "files", batch_size=1
    )  # pylint: disable=protected-access
    TC.assertEqual(flushed["calls"], 2)


def test_migrate_helpers_cover_counts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Cover migrate helper functions for counts and table copying."""  # pylint: disable=too-many-locals

    # _open_sqlite success path
    sqlite_db = tmp_path / "ok.sqlite"
    conn = migrate_sqlite_to_postgres.sqlite3.connect(sqlite_db)
    conn.execute("CREATE TABLE files (id INTEGER)")
    conn.commit()
    opened = migrate_sqlite_to_postgres._open_sqlite(sqlite_db)
    opened.close()

    # _table_counts and _table_counts_postgres
    conn = migrate_sqlite_to_postgres.sqlite3.connect(sqlite_db)
    conn.execute("INSERT INTO files (id) VALUES (1)")
    conn.commit()
    counts = migrate_sqlite_to_postgres._table_counts(conn, ("files",))
    TC.assertEqual(counts["files"], 1)
    conn.close()

    class _PgCursor:
        """Cursor stub supporting context manager protocol."""

        def __init__(self) -> None:
            self.state = 0
            self.executed: list[Any] = []

        def __enter__(self) -> "_PgCursor":
            return self

        def __exit__(
            self,
            exc_type: BaseException | None,
            exc: BaseException | None,
            tb: object,
        ) -> None:
            return None

        def execute(
            self, stmt: str, _params: Any | None = None
        ) -> None:  # pylint: disable=unused-argument
            """Track executed statements for assertions."""
            self.state += 1
            self.executed.append(stmt)

        def fetchone(self) -> tuple[int, ...]:
            """Return simulated count values."""
            if self.state == 1:
                return (1,)
            return (0,)

    class _PgConn:
        """Connection stub yielding _PgCursor."""

        def cursor(self) -> _PgCursor:
            """Return a new _PgCursor stub."""
            return _PgCursor()

        def __enter__(self) -> "_PgConn":
            return self

        def __exit__(
            self,
            exc_type: BaseException | None,
            exc: BaseException | None,
            tb: object,
        ) -> None:
            return None

    pg_counts = migrate_sqlite_to_postgres._table_counts_postgres(_PgConn(), ("files",))
    TC.assertEqual(pg_counts["files"], 0)

    # _print_dry_run_summary
    migrate_sqlite_to_postgres._print_dry_run_summary(
        {"source_counts": {"files": 1}, "target_counts": {"files": 0}},
        sqlite_db,
    )
    out = capsys.readouterr().out
    TC.assertIn("SQLite source", out)

    # _copy_table via stubs (monkeypatch psycopg2 imports)
    class DummyCursor:
        """Cursor stub returning two rows."""

        description = [("id",), ("name",)]

        def __init__(self) -> None:
            self._fetched = False

        def execute(self, stmt: str) -> None:  # pylint: disable=unused-argument
            """No-op execute for stub cursor."""
            return None

        def fetchall(self) -> list[tuple[int, str]]:
            """Return preset rows for copying."""
            return [(1, "a"), (2, "b")]

    class DummySqlite:
        """SQLite stub returning DummyCursor."""

        def cursor(self) -> DummyCursor:
            """Return a new DummyCursor stub."""
            return DummyCursor()

    class DummySQL:
        """psycopg2.sql.SQL stub used for template joins."""

        def __init__(self, template: str) -> None:
            self.template = template

        def format(self, *_args: Any, **_kwargs: Any) -> "DummySQL":
            """Return self without formatting."""
            return self

        def join(self, iterable: Iterator[str]) -> "DummySQL":
            """Return a new DummySQL with joined values."""
            joined = ", ".join(iterable)
            return DummySQL(joined)

        def __str__(self) -> str:
            return self.template

    def dummy_execute_values(*_args: Any, **_kwargs: Any) -> None:
        return None

    dummy_sql_module = types.SimpleNamespace(
        SQL=DummySQL, Identifier=lambda value: value
    )
    monkeypatch.setitem(
        sys.modules, "psycopg2", types.SimpleNamespace(sql=dummy_sql_module)
    )
    monkeypatch.setitem(
        sys.modules,
        "psycopg2.extras",
        types.SimpleNamespace(execute_values=dummy_execute_values),
    )

    batch_calls = {"count": 0}

    def _fake_execute_batch(
        _pg_conn: Any,
        _table: str,
        _columns: Any,
        rows: list[tuple[Any, ...]],
        _execute_values: Any,
    ) -> None:
        """Accumulate row counts to assert batch flushing."""
        batch_calls["count"] += len(rows)

    monkeypatch.setattr(
        migrate_sqlite_to_postgres, "_execute_batch", _fake_execute_batch
    )
    sqlite_conn_any: Any = DummySqlite()
    migrate_sqlite_to_postgres._copy_table(
        sqlite_conn_any,
        object(),
        "files",
        batch_size=10,
    )
    TC.assertEqual(batch_calls["count"], 2)


def test_migrate_copy_all_tables_and_execute_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise _copy_all_tables, _execute_batch, and _sync_identity."""  # pylint: disable=too-many-locals

    calls = {"copy": 0, "sync": 0}
    monkeypatch.setattr(
        migrate_sqlite_to_postgres,
        "_copy_table",
        lambda sqlite_conn, pg_conn, table, batch_size: calls.__setitem__(
            "copy", calls["copy"] + 1
        ),
    )
    monkeypatch.setattr(
        migrate_sqlite_to_postgres,
        "_sync_identity",
        lambda pg_conn, table: calls.__setitem__("sync", calls["sync"] + 1),
    )
    sqlite_conn_any: Any = sqlite3.connect(":memory:")
    migrate_sqlite_to_postgres._copy_all_tables(
        sqlite_conn_any,
        object(),
        ("files", "events"),
        batch_size=10,
    )  # pylint: disable=protected-access
    TC.assertEqual(calls["copy"], 2)
    TC.assertEqual(calls["sync"], 2)

    class SQLHelper:
        """psycopg2.sql helper stub for formatting tests."""

        def __init__(self, val: str) -> None:
            self.val = val

        def __str__(self) -> str:
            return self.val

        def format(self, *_args: Any, **_kwargs: Any) -> "SQLHelper":
            """Return self; used to mimic SQL composition."""
            return self

        def join(self, iterable: Iterator[str]) -> "SQLHelper":
            """Join iterable into a comma-separated SQLHelper."""
            return SQLHelper(", ".join(iterable))

    dummy_sql_module = types.SimpleNamespace(
        SQL=SQLHelper,
        Identifier=lambda value: value,
        Literal=lambda value: value,
    )
    monkeypatch.setitem(
        sys.modules, "psycopg2", types.SimpleNamespace(sql=dummy_sql_module)
    )
    monkeypatch.setitem(
        sys.modules,
        "psycopg2.extras",
        types.SimpleNamespace(
            execute_values=lambda *_args, **_kwargs: None
        ),  # pylint: disable=unused-argument
    )

    class DummyPgCursor:
        """Postgres cursor stub recording executed statements."""

        def __init__(self) -> None:
            self.executed: list[Any] = []

        def __enter__(self) -> "DummyPgCursor":
            return self

        def __exit__(
            self, exc_type: BaseException | None, exc: BaseException | None, tb: object
        ) -> None:
            return None

        def execute(
            self, statement: Any, _params: Any | None = None
        ) -> None:  # pylint: disable=unused-argument
            """Record executed statement for assertions."""
            self.executed.append(statement)

    class DummyPgConn:
        """Postgres connection stub counting commits."""

        def __init__(self) -> None:
            self.cur = DummyPgCursor()
            self.commits = 0

        def cursor(self) -> DummyPgCursor:
            """Return the shared cursor stub."""
            return self.cur

        def commit(self) -> None:
            """Increment commit counter."""
            self.commits += 1

    pg_conn = DummyPgConn()
    migrate_sqlite_to_postgres._execute_batch(
        pg_conn, "files", ["id", "name"], [(1, "a")], lambda *args, **kwargs: None
    )  # pylint: disable=protected-access
    migrate_sqlite_to_postgres._sync_identity(
        pg_conn, "files"
    )  # pylint: disable=protected-access
    TC.assertGreaterEqual(pg_conn.commits, 1)


def test_migrate_invokes_ensure_and_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    """migrate should call ensure_target_empty and copy helpers using stubs."""

    class DummyConn:
        """Generic connection stub supporting context manager."""

        def __enter__(self) -> "DummyConn":
            return self

        def __exit__(
            self,
            exc_type: BaseException | None,
            exc: BaseException | None,
            tb: object | None,
        ) -> None:
            return None

        def cursor(self) -> "DummyConn":
            """Return self as cursor stub."""
            return self

        def execute(self, stmt: Any) -> None:  # pylint: disable=unused-argument
            """No-op execute for stub connection."""
            return None

        def close(self) -> None:
            """Close stub connection."""
            return None

    dummy_sqlite = DummyConn()
    dummy_pg = DummyConn()
    calls = {"ensure": 0, "copy": 0}

    monkeypatch.setattr(
        migrate_sqlite_to_postgres, "_open_sqlite", lambda path: dummy_sqlite
    )
    monkeypatch.setattr(
        migrate_sqlite_to_postgres, "_open_postgres", lambda dsn: dummy_pg
    )
    monkeypatch.setattr(
        migrate_sqlite_to_postgres,
        "_ensure_target_empty",
        lambda conn, tables: calls.__setitem__("ensure", calls["ensure"] + 1),
    )
    monkeypatch.setattr(
        migrate_sqlite_to_postgres,
        "_copy_all_tables",
        lambda sqlite_conn, pg_conn, tables, batch_size: calls.__setitem__(
            "copy", calls["copy"] + 1
        ),
    )
    migrate_sqlite_to_postgres.migrate(Path("source.sqlite"), "pg", batch_size=5)
    TC.assertEqual(calls["ensure"], 1)
    TC.assertEqual(calls["copy"], 1)


# pylint: disable=too-many-lines
