"""CLI tests for managing redaction rules (AI-assisted by Codex GPT-5)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any, Callable

from pytest import MonkeyPatch

import cli.redaction_rules as rules_cli
from src.services.config import DatabaseConfig, OutputPaths, SessionsConfig
from src.services.database import ensure_schema, get_connection


TC = unittest.TestCase()


def _fake_config(tmp_path: Path) -> SessionsConfig:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    return SessionsConfig(
        sessions_root=tmp_path,
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
