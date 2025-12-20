"""Tests for CLI helper functions and utilities (AI-assisted by Codex GPT-5).

Tests core CLI functionality including argument parsing, configuration loading,
path resolution, and output formatting for ingest_session and group_session.
"""

# pylint: disable=import-error,protected-access

from __future__ import annotations

import argparse
import textwrap
from pathlib import Path

import unittest

import pytest

from cli import ingest_session
from cli import group_session
from src.services import ingest
from src.services.config import ConfigError, SessionsConfig, load_config
from src.services.ingest import SessionSummary

TC = unittest.TestCase()


def _write_cli_config(tmp_path: Path) -> tuple[Path, Path]:
    """Write a minimal config file and return its path and db path."""

    sessions_root = tmp_path / "sessions"
    sessions_root.mkdir()
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    db_path = reports_dir / "session.sqlite"

    config_file = tmp_path / "config.toml"
    config_file.write_text(
        textwrap.dedent(
            f"""
            [sessions]
            root = "{sessions_root.as_posix()}"

            [ingest]
            db_path = "{db_path.as_posix()}"

            [outputs]
            reports_dir = "{reports_dir.as_posix()}"
            """
        ),
        encoding="utf-8",
    )
    return config_file, db_path.resolve()


def test_resolve_runtime_options_debug_caps_limit() -> None:
    """Debug mode should cap limit at 2 and enable verbose."""
    args = argparse.Namespace(verbose=False, debug=True, limit=None)
    verbose, limit = ingest_session._resolve_runtime_options(
        args
    )  # pylint: disable=protected-access
    TC.assertTrue(verbose)
    TC.assertEqual(limit, 2)


def test_validate_db_path_rejects_missing_parent(tmp_path: Path) -> None:
    """validate_db_path should raise when parent folder is absent."""
    target = tmp_path / "missing_dir" / "session.sqlite"
    with pytest.raises(ConfigError):
        ingest_session.validate_db_path(target)


def test_print_error_details_renders_and_counts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_print_error_details should summarize a list of structured errors."""
    errors = [
        {"severity": "ERROR", "code": "bad", "message": "oops"},
        {"severity": "WARNING", "code": "warn", "message": "hmm"},
        {"severity": "ERROR", "code": "another", "message": "more"},
        {"severity": "ERROR", "code": "extra", "message": "extra"},
    ]
    count = ingest_session._print_error_details(
        errors, indent=""
    )  # pylint: disable=protected-access
    captured = capsys.readouterr().out
    TC.assertEqual(count, 4)
    TC.assertIn("ERROR/bad: oops", captured)
    TC.assertIn("... 1 more", captured)


def test_report_many_results(capsys: pytest.CaptureFixture[str]) -> None:
    """_report_many_results should aggregate totals and print them."""
    s1: SessionSummary = (
        ingest._create_empty_summary(  # pylint: disable=protected-access
            Path("file1.jsonl"), 1
        )
    )
    s1["errors"] = [{"severity": "ERROR", "code": "x", "message": "m"}]
    s2: SessionSummary = (
        ingest._create_empty_summary(  # pylint: disable=protected-access
            Path("file2.jsonl"), 2
        )
    )
    summaries: list[SessionSummary] = [s1, s2]
    ingest_session._report_many_results(
        summaries, Path("db.sqlite")
    )  # pylint: disable=protected-access
    captured = capsys.readouterr().out
    TC.assertIn("Ingested: file1.jsonl", captured)
    TC.assertIn("Ingested: file2.jsonl", captured)
    TC.assertIn("Files processed: 2", captured)
    TC.assertIn("errors: 1", captured)


def test_shorten_truncates_long_text() -> None:
    """shorten should ellipsize text exceeding the limit."""
    text = "a" * 10
    TC.assertEqual(group_session.shorten(text, limit=5), "aa...")


def test_shorten_handles_whitespace_and_zero_limit() -> None:
    """shorten should handle whitespace-only and small/zero limits safely."""

    TC.assertEqual(group_session.shorten("   "), "")
    TC.assertEqual(group_session.shorten("abc", limit=0), "...")
    TC.assertEqual(group_session.shorten("abc", limit=2), "ab...")


def test_load_config_honors_batch_override(tmp_path: Path) -> None:
    """load_config should parse TOML and apply ingest batch size override."""
    config_dir = tmp_path / "user"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    config_file.write_text(
        '[sessions]\nroot = "."\n[ingest]\nbatch_size = 50\n',
        encoding="utf-8",
    )

    # ensure cwd so load_config finds file via explicit path
    cfg = ingest_session.load_config(config_file)  # reuse to exercise wrapper
    TC.assertIsInstance(cfg, SessionsConfig)
    TC.assertEqual(cfg.ingest_batch_size, 50)


def test_load_config_invalid_root(tmp_path: Path) -> None:
    """load_config should raise when sessions.root is missing."""
    config_dir = tmp_path / "user"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    config_file.write_text('[sessions]\nroot = "./missing"\n', encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(config_file)


def test_resolve_database_path_defaults_to_config(tmp_path: Path) -> None:
    """_resolve_database_path should fall back to config when CLI is None."""

    config_file, db_path = _write_cli_config(tmp_path)
    config = load_config(config_file)

    resolved = (
        ingest_session._resolve_database_path(  # pylint: disable=protected-access
            None, config
        )
    )
    TC.assertEqual(resolved, db_path)


def test_resolve_database_path_prefers_cli_override(tmp_path: Path) -> None:
    """_resolve_database_path should honor CLI override when provided."""

    config_file, _ = _write_cli_config(tmp_path)
    config = load_config(config_file)

    override_dir = tmp_path / "override"
    override_dir.mkdir()
    override_path = override_dir / "override.sqlite"

    resolved = (
        ingest_session._resolve_database_path(  # pylint: disable=protected-access
            override_path, config
        )
    )
    TC.assertEqual(resolved, override_path.resolve())
