"""CLI to ingest Codex session logs into SQLite.

Purpose: Command-line entry for ingesting Codex session logs into SQLite storage.
Author: Codex with Lauren Parlett
Date: 2025-10-30
"""

from __future__ import annotations

import argparse
import logging
import os
from collections import Counter
from pathlib import Path
from typing import Any, List, Sequence

from src.parsers.session_parser import SessionDiscoveryError
from src.services.config import ConfigError, load_config, SessionsConfig
from src.services.ingest import (
    ingest_session_file,
    ingest_sessions_in_directory,
    SessionSummary,
)

__all__: list[str] = ["SessionDiscoveryError", "SessionSummary", "load_config", "main"]


def build_parser() -> argparse.ArgumentParser:
    """Builds the argument parser for the CLI.

    Returns:
        argparse.ArgumentParser: _parser instance
    """
    parser = argparse.ArgumentParser(
        description=("Ingest the earliest Codex session into an " "SQLite database."),
    )
    parser.add_argument(
        "--database",
        "-d",
        type=Path,
        default=None,
        help=(
            "Path to the SQLite database. "
            "Defaults to ingest.db_path from user/config.toml."
        ),
    )
    parser.add_argument(
        "--session",
        "-s",
        type=Path,
        help=("Optional explicit session file to ingest instead of " "auto-discovery."),
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Optional cap on the number of session files to ingest \
            (applies only when --session is not provided).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging during ingest.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help=("Debug mode: enable verbose logging and limit " "ingest to two files."),
    )
    return parser


def main() -> None:
    """Main entry point for the CLI."""

    args = build_parser().parse_args()
    verbose, limit = _resolve_runtime_options(args)
    _configure_logging(verbose)

    config = _load_configuration()

    database_path = _resolve_database_path(args.database, config)

    if args.session:
        _ingest_single_file(
            args.session,
            database_path,
            verbose,
            config.ingest_batch_size,
        )
        return

    summaries = _ingest_many_files(
        config.sessions_root,
        database_path,
        limit,
        verbose,
        config.ingest_batch_size,
    )
    _report_many_results(summaries, database_path)


def _resolve_runtime_options(
    args: argparse.Namespace,
) -> tuple[bool, int | None]:
    """Return normalized verbose flag and ingest limit from CLI arguments."""

    verbose = args.verbose or args.debug
    limit = args.limit
    if args.debug and (limit is None or limit > 2):
        limit = 2
    return verbose, limit


def _configure_logging(verbose: bool) -> None:
    """Configure logging based on verbosity setting."""
    if verbose:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def _load_configuration() -> SessionsConfig:
    """Load and return the sessions configuration."""
    try:
        return load_config()
    except ConfigError as err:
        print(f"Configuration error: {err}")
        raise SystemExit(1) from err


def _resolve_database_path(cli_database: Path | None, config: SessionsConfig) -> Path:
    """Choose the database path from CLI override or configuration."""

    chosen = (
        config.database.sqlite_path
        if cli_database is None
        else cli_database.expanduser().resolve()
    )
    validate_db_path(chosen)
    return chosen


def validate_db_path(path: Path) -> None:
    """Ensure SQLite database location is writable."""

    resolved = path.expanduser().resolve()
    if resolved.exists() and not os.access(resolved, os.W_OK):
        raise ConfigError(f"Database {resolved} exists but is not writable.")
    parent = resolved.parent
    if not parent.exists() or not os.access(parent, os.W_OK):
        raise ConfigError(f"Cannot create database in {parent}; not writable.")


def _ingest_single_file(
    session_file: Path,
    database: Path,
    verbose: bool,
    batch_size: int,
) -> None:
    """Ingest a single session file and print the summary."""
    summary = ingest_session_file(
        session_file,
        database,
        verbose=verbose,
        batch_size=batch_size,
    )
    _print_single_summary(session_file, database, summary)


def _ingest_many_files(
    sessions_root: Path,
    database: Path,
    limit: int | None,
    verbose: bool,
    batch_size: int,
) -> List[SessionSummary]:
    """Ingest multiple session files from a directory and return summaries."""
    try:
        return list(
            ingest_sessions_in_directory(
                sessions_root,
                database,
                limit=limit,
                verbose=verbose,
                batch_size=batch_size,
            )
        )
    except SessionDiscoveryError as err:
        print(f"Session discovery error: {err}")
        raise SystemExit(1) from err


def _print_error_details(errors: Any, indent: str = "  ") -> int:
    """Render structured error details and return the number of errors."""

    if not isinstance(errors, list):
        print(f"{indent}errors: 0")
        return 0

    count = len(errors)
    print(f"{indent}errors: {count}")

    for error in errors[:3]:
        if not isinstance(error, dict):
            continue
        severity = error.get("severity", "UNKNOWN")
        code = error.get("code", "<unknown>")
        message = error.get("message", "")
        print(f"{indent}  - {severity}/{code}: {message}")
    if count > 3:
        print(f"{indent}  - ... {count - 3} more")
    return count


def _report_many_results(
    summaries: Sequence[SessionSummary],
    database: Path,
) -> None:
    """Print a summary report for multiple ingested session files."""
    totals: Counter[str] = Counter()
    for summary in summaries:
        session_file = summary["session_file"]
        print(f"Ingested: {session_file}")
        for key, value in summary.items():
            if key in ("file_id", "session_file"):
                continue
            if key == "errors":
                totals["errors"] += _print_error_details(value)
                continue
            if isinstance(value, int):
                totals[key] += value
            print(f"  {key}: {value}")
        print()

    print(f"Database: {database}")
    print(f"Files processed: {len(summaries)}")
    print("Totals:")
    for key, value in totals.items():
        print(f"  {key}: {value}")


def _print_single_summary(
    session_file: Path,
    database: Path,
    summary: SessionSummary,
) -> None:
    """Print a summary report for a single ingested session file."""
    print(f"Ingested session file: {session_file}")
    print(f"Database: {database}")
    print("Inserted rows:")
    for key, value in summary.items():
        if key in {"file_id", "session_file"}:
            continue
        if key == "errors":
            _print_error_details(value)
            continue
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
