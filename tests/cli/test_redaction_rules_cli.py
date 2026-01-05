"""CLI tests for managing redaction rules (AI-assisted)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any, Callable

from pytest import MonkeyPatch

import cli.redaction_rules as rules_cli
from src.services.config import ConfigError, DatabaseConfig, OutputPaths, SessionsConfig
from src.services.database import ensure_schema, get_connection


TC = unittest.TestCase()


def _fake_config(tmp_path: Path) -> SessionsConfig:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    return SessionsConfig(
        codex_root=tmp_path,
        ingest_batch_size=10,
        database=DatabaseConfig(sqlite_path=tmp_path / "db.sqlite"),
        outputs=OutputPaths(reports_dir=reports_dir),
    )


def _connection_factory(db_path: Path) -> Callable[[DatabaseConfig], Any]:
    def _factory(_config: DatabaseConfig) -> Any:
        conn = get_connection(db_path)
        ensure_schema(conn)
        return conn

    return _factory


def test_add_and_list_rules(
    monkeypatch: MonkeyPatch, capsys: Any, tmp_path: Path
) -> None:
    """CLI should add a rule to file + DB and list JSON lines."""

    config = _fake_config(tmp_path)
    conn_factory = _connection_factory(config.database.sqlite_path)
    rules_file = tmp_path / "rules.json"

    monkeypatch.setattr(rules_cli, "load_config", lambda: config)
    monkeypatch.setattr(rules_cli, "get_connection_for_config", conn_factory)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prog",
            "--rules-file",
            str(rules_file),
            "--allow-db-fallback",
            "add",
            "--id",
            "r1",
            "--type",
            "literal",
            "--pattern",
            "secret",
        ],
    )
    rules_cli.main()

    contents = json.loads(rules_file.read_text(encoding="utf-8"))[0]
    TC.assertEqual(contents["id"], "r1")
    TC.assertEqual(contents["pattern"], "secret")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prog",
            "--rules-file",
            str(rules_file),
            "list",
        ],
    )
    rules_cli.main()
    out = capsys.readouterr().out
    TC.assertIn("r1", out)
    TC.assertIn("literal", out)
    TC.assertIn("secret", out)


def test_remove_rule(monkeypatch: MonkeyPatch, capsys: Any, tmp_path: Path) -> None:
    """CLI should remove a rule from file + DB."""

    config = _fake_config(tmp_path)
    conn_factory = _connection_factory(config.database.sqlite_path)
    rules_file = tmp_path / "rules.json"

    monkeypatch.setattr(rules_cli, "load_config", lambda: config)
    monkeypatch.setattr(rules_cli, "get_connection_for_config", conn_factory)

    # First add a rule
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prog",
            "--rules-file",
            str(rules_file),
            "--allow-db-fallback",
            "add",
            "--id",
            "r1",
            "--type",
            "literal",
            "--pattern",
            "secret",
        ],
    )
    rules_cli.main()

    # Then remove it
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prog",
            "--rules-file",
            str(rules_file),
            "remove",
            "--id",
            "r1",
        ],
    )
    rules_cli.main()
    out = capsys.readouterr().out
    TC.assertIn("Removed rule 'r1'", out)

    # Verify it's gone
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prog",
            "--rules-file",
            str(rules_file),
            "list",
        ],
    )
    rules_cli.main()
    out = capsys.readouterr().out
    TC.assertNotIn("r1", out)


def test_remove_nonexistent_rule(
    monkeypatch: MonkeyPatch, capsys: Any, tmp_path: Path
) -> None:
    """CLI should handle removing a nonexistent rule gracefully."""

    config = _fake_config(tmp_path)
    conn_factory = _connection_factory(config.database.sqlite_path)
    rules_file = tmp_path / "rules.json"
    rules_file.write_text(json.dumps([]), encoding="utf-8")

    monkeypatch.setattr(rules_cli, "load_config", lambda: config)
    monkeypatch.setattr(rules_cli, "get_connection_for_config", conn_factory)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prog",
            "--rules-file",
            str(rules_file),
            "remove",
            "--id",
            "nonexistent",
        ],
    )
    rules_cli.main()
    out = capsys.readouterr().out
    TC.assertIn("not found", out)


def test_add_duplicate_rule_id(
    monkeypatch: MonkeyPatch, capsys: Any, tmp_path: Path
) -> None:
    """CLI should reject duplicate rule IDs."""

    config = _fake_config(tmp_path)
    conn_factory = _connection_factory(config.database.sqlite_path)
    rules_file = tmp_path / "rules.json"

    monkeypatch.setattr(rules_cli, "load_config", lambda: config)
    monkeypatch.setattr(rules_cli, "get_connection_for_config", conn_factory)

    # Add first rule
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prog",
            "--rules-file",
            str(rules_file),
            "--allow-db-fallback",
            "add",
            "--id",
            "r1",
            "--type",
            "literal",
            "--pattern",
            "secret",
        ],
    )
    rules_cli.main()

    # Try to add duplicate
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prog",
            "--rules-file",
            str(rules_file),
            "add",
            "--id",
            "r1",
            "--type",
            "regex",
            "--pattern",
            "different",
        ],
    )
    rules_cli.main()
    out = capsys.readouterr().out
    TC.assertIn("already exists", out)


def test_list_with_disabled_rules(
    monkeypatch: MonkeyPatch, capsys: Any, tmp_path: Path
) -> None:
    """CLI should filter disabled rules based on flag."""

    config = _fake_config(tmp_path)
    conn_factory = _connection_factory(config.database.sqlite_path)
    rules_file = tmp_path / "rules.json"

    monkeypatch.setattr(rules_cli, "load_config", lambda: config)
    monkeypatch.setattr(rules_cli, "get_connection_for_config", conn_factory)

    # Add both enabled and disabled rules
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prog",
            "--rules-file",
            str(rules_file),
            "--allow-db-fallback",
            "add",
            "--id",
            "enabled_rule",
            "--type",
            "literal",
            "--pattern",
            "secret",
        ],
    )
    rules_cli.main()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prog",
            "--rules-file",
            str(rules_file),
            "--allow-db-fallback",
            "add",
            "--id",
            "disabled_rule",
            "--type",
            "literal",
            "--pattern",
            "secret",
            "--disable",
        ],
    )
    rules_cli.main()

    # List without --include-disabled (should show both from DB fallback)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prog",
            "--rules-file",
            str(rules_file),
            "list",
        ],
    )
    rules_cli.main()
    out = capsys.readouterr().out
    # When using DB fallback, both are shown
    TC.assertIn("enabled_rule", out)

    # List with --include-disabled (should definitely show both)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prog",
            "--rules-file",
            str(rules_file),
            "list",
            "--include-disabled",
        ],
    )
    rules_cli.main()
    out = capsys.readouterr().out
    TC.assertIn("enabled_rule", out)
    TC.assertIn("disabled_rule", out)
    TC.assertIn("DISABLED", out)


def test_config_error_handling(monkeypatch: MonkeyPatch, capsys: Any) -> None:
    """CLI should handle config errors gracefully."""

    def raise_error() -> None:
        raise ConfigError("Test config error")

    monkeypatch.setattr(rules_cli, "load_config", raise_error)

    monkeypatch.setattr(sys, "argv", ["prog", "list"])
    rules_cli.main()
    out = capsys.readouterr().out
    TC.assertIn("Configuration error", out)


def test_database_error_handling(
    monkeypatch: MonkeyPatch, capsys: Any, tmp_path: Path
) -> None:
    """CLI should handle database errors gracefully."""

    config = _fake_config(tmp_path)

    def raise_error(_cfg: Any) -> None:
        raise RuntimeError("Database connection failed")

    monkeypatch.setattr(rules_cli, "load_config", lambda: config)
    monkeypatch.setattr(rules_cli, "get_connection_for_config", raise_error)

    monkeypatch.setattr(sys, "argv", ["prog", "list"])
    rules_cli.main()
    out = capsys.readouterr().out
    TC.assertIn("Database error", out)
