"""CLI to migrate session data from SQLite to Postgres with a required dry-run.

Purpose: Migrate data from local SQLite to Postgres (AI-assisted by Codex GPT-5).
Author: Codex with Lauren Parlett
Date: 2025-11-24
"""

# pylint: disable=import-error,import-outside-toplevel

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Callable

from src.services.config import ConfigError, SessionsConfig, load_config
from src.services.postgres_schema import POSTGRES_SCHEMA, TABLES_IN_COPY_ORDER

__all__: list[str] = ["sqlite3", "main"]


def build_parser() -> argparse.ArgumentParser:
    """Build the migration CLI parser."""

    parser = argparse.ArgumentParser(
        description=(
            "Migrate AI agent session data from SQLite to Postgres. "
            "A dry-run validation always executes before any data is copied."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("user") / "config.toml",
        help="Path to config.toml (default: user/config.toml).",
    )
    parser.add_argument(
        "--sqlite",
        type=Path,
        help="Optional override path to the SQLite source database.",
    )
    parser.add_argument(
        "--postgres-dsn",
        dest="postgres_dsn",
        help="Postgres DSN (overrides config.database.postgres_dsn).",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Perform the migration after dry-run validation. Without this flag, "
        "the command exits after the dry-run checks.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Number of rows per batch when copying (default: 1000).",
    )
    return parser


def main() -> None:
    """Entry point for the migration CLI."""

    args = build_parser().parse_args()
    config = _load_configuration(args.config)
    sqlite_path = args.sqlite or config.database.sqlite_path
    postgres_dsn = args.postgres_dsn or config.database.postgres_dsn

    if not postgres_dsn:
        raise SystemExit(
            "Postgres DSN is required. Set database.postgres_dsn in config.toml "
            "or pass --postgres-dsn."
        )

    print("Running dry-run validation...")
    dry_summary = run_dry_run(sqlite_path, postgres_dsn)
    _print_dry_run_summary(dry_summary, sqlite_path)

    if not args.execute:
        print("\nDry-run complete. Re-run with --execute to perform the migration.")
        return

    print("\nExecuting migration (schema + data copy)...")
    migrate(sqlite_path, postgres_dsn, batch_size=args.batch_size)
    print("Migration complete.")


def _load_configuration(config_path: Path) -> SessionsConfig:
    """Load config and surface errors cleanly."""

    try:
        return load_config(config_path)
    except ConfigError as err:
        print(f"Configuration error: {err}")
        raise SystemExit(1) from err


def run_dry_run(sqlite_path: Path, postgres_dsn: str) -> dict[str, Any]:
    """Validate connectivity and table row counts without copying data."""

    sqlite_conn = _open_sqlite(sqlite_path)
    pg_conn = _open_postgres(postgres_dsn)
    try:
        src_counts = _table_counts(sqlite_conn, TABLES_IN_COPY_ORDER)
        tgt_counts = _table_counts_postgres(pg_conn, TABLES_IN_COPY_ORDER)
        return {
            "source_counts": src_counts,
            "target_counts": tgt_counts,
        }
    finally:
        sqlite_conn.close()
        pg_conn.close()


def migrate(sqlite_path: Path, postgres_dsn: str, *, batch_size: int) -> None:
    """Create schema in Postgres and copy all data from SQLite."""

    sqlite_conn = _open_sqlite(sqlite_path)
    pg_conn = _open_postgres(postgres_dsn)
    try:
        with pg_conn:
            with pg_conn.cursor() as cur:
                cur.execute(POSTGRES_SCHEMA)
        _ensure_target_empty(pg_conn, TABLES_IN_COPY_ORDER)
        _copy_all_tables(sqlite_conn, pg_conn, TABLES_IN_COPY_ORDER, batch_size)
    finally:
        sqlite_conn.close()
        pg_conn.close()


def _open_sqlite(path: Path) -> sqlite3.Connection:
    """Open SQLite connection with FK enforcement."""

    if not path.exists():
        raise SystemExit(f"SQLite database not found: {path}")
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _open_postgres(dsn: str) -> Any:
    """Open Postgres connection lazily importing psycopg2."""

    try:
        import psycopg2  # pylint: disable=import-outside-toplevel
    except ModuleNotFoundError as exc:  # pragma: no cover - requires driver install
        raise SystemExit(
            "psycopg2 is required for migration. Install dependencies and retry."
        ) from exc

    conn = psycopg2.connect(dsn=dsn)
    conn.autocommit = False
    return conn


def _table_counts(conn: sqlite3.Connection, tables: Iterable[str]) -> dict[str, int]:
    """Return row counts for each table in SQLite."""

    counts: dict[str, int] = {}
    cursor = conn.cursor()
    for table in tables:
        if table not in TABLES_IN_COPY_ORDER:
            raise SystemExit(f"Unexpected table name: {table}")
        cursor.execute(f"SELECT COUNT(*) FROM {table}")  # nosec safe due to allowlist
        counts[table] = int(cursor.fetchone()[0])
    return counts


def _table_counts_postgres(conn: Any, tables: Iterable[str]) -> dict[str, int]:
    """Return row counts for each table in Postgres, treating missing tables as zero."""

    counts: dict[str, int] = {}
    with conn.cursor() as cur:
        for table in tables:
            if table not in TABLES_IN_COPY_ORDER:
                raise SystemExit(f"Unexpected table name: {table}")
            cur.execute(
                """
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_name = %s
                """,
                (table,),
            )
            exists = cur.fetchone()[0] == 1
            if not exists:
                counts[table] = 0
                continue
            cur.execute(f"SELECT COUNT(*) FROM {table}")  # nosec safe due to allowlist
            row = cur.fetchone()
            counts[table] = int(row[0] if row else 0)
    return counts


def _print_dry_run_summary(summary: dict[str, Any], sqlite_path: Path) -> None:
    """Log dry-run output in a human-friendly way."""

    print(f"SQLite source: {sqlite_path}")
    print("Source row counts:")
    for table, count in summary["source_counts"].items():
        print(f"  {table}: {count}")
    print("\nTarget row counts (Postgres):")
    for table, count in summary["target_counts"].items():
        print(f"  {table}: {count}")
    if any(summary["target_counts"].values()):
        print(
            "\nWARNING: Target tables are not empty. Migration will fail unless you "
            "clear them first."
        )


def _ensure_target_empty(pg_conn: Any, tables: Iterable[str]) -> None:
    """Prevent overwriting populated targets."""

    counts = _table_counts_postgres(pg_conn, tables)
    non_empty = {t: c for t, c in counts.items() if c > 0}
    if non_empty:
        details = ", ".join(f"{tbl}={cnt}" for tbl, cnt in non_empty.items())
        raise SystemExit(
            f"Target database is not empty. Clear data before migrating. ({details})"
        )


def _copy_all_tables(
    sqlite_conn: sqlite3.Connection,
    pg_conn: Any,
    tables: Iterable[str],
    batch_size: int,
) -> None:
    """Copy all tables in dependency order."""

    for table in tables:
        print(f"Copying table: {table}")
        _copy_table(sqlite_conn, pg_conn, table, batch_size=batch_size)
        _sync_identity(pg_conn, table)


def _copy_table(
    sqlite_conn: sqlite3.Connection,
    pg_conn: Any,
    table: str,
    batch_size: int,
) -> None:
    """Copy a single table from SQLite to Postgres in batches."""

    from psycopg2 import sql  # pylint: disable=import-outside-toplevel
    from psycopg2.extras import (
        execute_values,
    )  # pylint: disable=import-outside-toplevel

    src_cur = sqlite_conn.cursor()
    if table not in TABLES_IN_COPY_ORDER:
        raise SystemExit(f"Unexpected table name: {table}")
    src_cur.execute(f"SELECT * FROM {table}")  # nosec B608 validated allowlist
    columns = [col[0] for col in src_cur.description]
    column_list = sql.SQL(", ").join(sql.Identifier(col) for col in columns)

    rows: list[tuple[Any, ...]] = []
    for row in src_cur.fetchall():
        rows.append(tuple(row))
        if len(rows) >= batch_size:
            _execute_batch(pg_conn, table, column_list, rows, execute_values)
            rows.clear()
    if rows:
        _execute_batch(pg_conn, table, column_list, rows, execute_values)


def _execute_batch(
    pg_conn: Any,
    table: str,
    columns: Any,
    rows: list[tuple[Any, ...]],
    execute_values: Callable[..., Any],
) -> None:
    """Execute a batch insert with execute_values for performance."""

    from psycopg2 import sql  # pylint: disable=import-outside-toplevel

    placeholder = "(" + ", ".join(["%s"] * len(rows[0])) + ")"
    statement = sql.SQL("INSERT INTO {} ({}) VALUES %s").format(
        sql.Identifier(table),
        columns,
    )
    with pg_conn.cursor() as cur:
        execute_values(cur, statement, rows, template=placeholder)
    pg_conn.commit()


def _sync_identity(pg_conn: Any, table: str) -> None:
    """Advance identity sequence after manual id inserts."""

    from psycopg2 import sql  # pylint: disable=import-outside-toplevel

    statement = sql.SQL(
        """
        SELECT setval(
            pg_get_serial_sequence(%s, 'id'),
            GREATEST(COALESCE((SELECT MAX(id) FROM {}), 0), 1)
        )
        """
    ).format(sql.Identifier(table))
    with pg_conn.cursor() as cur:
        cur.execute(statement, (table,))
    pg_conn.commit()


if __name__ == "__main__":
    main()
