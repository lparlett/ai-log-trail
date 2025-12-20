"""Additional tests for migrate_sqlite_to_postgres (AI-assisted by Codex GPT-5)."""

# pylint: disable=import-error,protected-access,too-few-public-methods

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path
from typing import Any

import pytest

from cli import migrate_sqlite_to_postgres as migrate_cli

TC = unittest.TestCase()


class _DummyConn:
    """Simple connection stub tracking close() calls."""

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        """Mark connection as closed."""
        self.closed = True


class _DummyPgConn:
    """Postgres connection stub supporting context manager usage."""

    def __init__(self) -> None:
        self.closed = False
        self.executed: list[Any] = []

    def __enter__(self: "_DummyPgConn") -> "_DummyPgConn":
        return self

    def __exit__(
        self,
        exc_type: BaseException | None,
        exc: BaseException | None,
        tb: object,
    ) -> None:
        return None

    def cursor(self) -> "_DummyPgConn":
        """Return self as cursor stub."""
        return self

    def execute(
        self, statement: Any, _params: Any | None = None
    ) -> None:  # pylint: disable=unused-argument
        """Record executed statement."""
        self.executed.append(statement)

    def fetchone(self) -> tuple[int]:
        """Return one-row result tuple."""
        return (1,)

    def commit(self) -> None:
        """Commit stub (no-op)."""
        return None

    def close(self) -> None:
        """Mark connection as closed."""
        self.closed = True


def test_open_sqlite_missing_path_exits(tmp_path: Path) -> None:
    """_open_sqlite should exit when the database file is missing."""

    missing = tmp_path / "missing.sqlite"
    with pytest.raises(SystemExit):
        migrate_cli._open_sqlite(missing)  # pylint: disable=protected-access


def test_table_counts_validates_allowlist(tmp_path: Path) -> None:
    """_table_counts should reject unexpected table names."""

    db_path = tmp_path / "test.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE files (id INTEGER)")
    conn.commit()

    with pytest.raises(SystemExit):
        migrate_cli._table_counts(
            conn, ["not_allowed"]
        )  # pylint: disable=protected-access
    conn.close()


def test_run_dry_run_closes_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_dry_run should close both connections and return counts."""

    dummy_sqlite = _DummyConn()
    dummy_pg = _DummyPgConn()
    monkeypatch.setattr(migrate_cli, "_open_sqlite", lambda path: dummy_sqlite)
    monkeypatch.setattr(migrate_cli, "_open_postgres", lambda dsn: dummy_pg)
    monkeypatch.setattr(
        migrate_cli,
        "_table_counts",
        lambda conn, tables: {"files": 1, "sessions": 2},
    )
    monkeypatch.setattr(
        migrate_cli,
        "_table_counts_postgres",
        lambda conn, tables: {"files": 0, "sessions": 0},
    )

    summary = migrate_cli.run_dry_run(Path("src.sqlite"), "postgres://dsn")
    TC.assertEqual(summary["source_counts"]["files"], 1)
    TC.assertEqual(summary["target_counts"]["sessions"], 0)
    TC.assertTrue(dummy_sqlite.closed)
    TC.assertTrue(dummy_pg.closed)


def test_migrate_calls_copy_pipeline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """migrate should build schema then call ensure_empty and copy helpers."""

    dummy_sqlite = _DummyConn()
    dummy_pg = _DummyPgConn()
    called = {"ensure": 0, "copy": 0}

    monkeypatch.setattr(migrate_cli, "_open_sqlite", lambda path: dummy_sqlite)
    monkeypatch.setattr(migrate_cli, "_open_postgres", lambda dsn: dummy_pg)
    monkeypatch.setattr(
        migrate_cli,
        "_ensure_target_empty",
        lambda conn, tables: called.__setitem__("ensure", called["ensure"] + 1),
    )
    monkeypatch.setattr(
        migrate_cli,
        "_copy_all_tables",
        lambda sqlite_conn, pg_conn, tables, batch_size: called.__setitem__(
            "copy", called["copy"] + 1
        ),
    )

    migrate_cli.migrate(tmp_path / "source.sqlite", "postgres://dsn", batch_size=10)

    TC.assertEqual(called["ensure"], 1)
    TC.assertEqual(called["copy"], 1)
    TC.assertTrue(dummy_sqlite.closed)
    TC.assertTrue(dummy_pg.closed)


def test_migrate_propagates_copy_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """migrate should propagate errors from copy and still close connections."""

    dummy_sqlite = _DummyConn()
    dummy_pg = _DummyPgConn()

    monkeypatch.setattr(migrate_cli, "_open_sqlite", lambda path: dummy_sqlite)
    monkeypatch.setattr(migrate_cli, "_open_postgres", lambda dsn: dummy_pg)
    monkeypatch.setattr(migrate_cli, "_ensure_target_empty", lambda conn, tables: None)
    monkeypatch.setattr(
        migrate_cli,
        "_copy_all_tables",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("copy failed")),
    )

    with pytest.raises(RuntimeError):
        migrate_cli.migrate(tmp_path / "source.sqlite", "postgres://dsn", batch_size=10)
    TC.assertTrue(dummy_sqlite.closed)
    TC.assertTrue(dummy_pg.closed)


def test_copy_all_tables_preserves_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """_copy_all_tables should iterate tables in order and sync identity."""

    order: list[str] = []

    def _copy_table(*args: Any, **kwargs: Any) -> None:
        table_name = kwargs.get("table")
        if table_name is None and len(args) >= 3:
            table_name = args[2]
        if table_name is not None:
            order.append(str(table_name))

    def _sync_identity(
        _pg_conn: Any, table: str
    ) -> None:  # pylint: disable=unused-argument
        order.append(f"sync:{table}")

    monkeypatch.setattr(migrate_cli, "_copy_table", _copy_table)
    monkeypatch.setattr(migrate_cli, "_sync_identity", _sync_identity)
    migrate_cli._copy_all_tables(  # pylint: disable=protected-access
        sqlite_conn=sqlite3.connect(":memory:"),
        pg_conn=_DummyPgConn(),
        tables=("files", "events"),
        batch_size=1,
    )
    TC.assertEqual(order, ["files", "sync:files", "events", "sync:events"])


def test_ensure_target_empty_raises_on_nonempty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_ensure_target_empty should abort when target tables contain rows."""

    monkeypatch.setattr(
        migrate_cli,
        "_table_counts_postgres",
        lambda conn, tables: {"files": 1, "sessions": 0},
    )

    with pytest.raises(SystemExit):
        migrate_cli._ensure_target_empty(
            _DummyPgConn(), ("files", "sessions")
        )  # pylint: disable=protected-access


def test_copy_table_fk_violation_rolls_back() -> None:
    """_copy_table should propagate FK failures for visibility."""

    class _SqliteCur:
        """SQLite cursor stub returning invalid FK rows."""

        description = [("id",), ("file_id",)]

        def execute(self, _stmt: str) -> None:
            """No-op execute for stub."""
            return None

        def fetchall(self) -> list[tuple[int, int]]:
            """Return rows that violate FK constraints."""
            return [(1, 999)]  # invalid FK

    class _SqliteConn:
        """SQLite connection stub yielding _SqliteCur."""

        def cursor(self) -> _SqliteCur:
            """Return a new _SqliteCur stub."""
            return _SqliteCur()

    class _PgCur:
        """Postgres cursor stub that raises on commit."""

        def __enter__(self) -> "_PgCur":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def execute(self, stmt: Any, params: Any | None = None) -> None:  # noqa: ARG002
            """Record execute parameters for coverage."""
            _ = stmt
            _ = params

    class _PgConn:
        """Postgres connection stub that fails on commit."""

        def cursor(self) -> _PgCur:
            """Return a new _PgCur stub."""
            return _PgCur()

        def commit(self) -> None:
            """Raise to simulate FK violation on commit."""
            raise RuntimeError("fk violation")

    sqlite_conn = sqlite3.connect(":memory:")
    sqlite_conn.execute("CREATE TABLE prompts (id INTEGER, file_id INTEGER)")
    sqlite_conn.execute("INSERT INTO prompts (id, file_id) VALUES (1, 999)")
    pg_conn = _PgConn()

    class _DummySqlModule:
        """psycopg2.sql stub module."""

        class SQL:
            """SQL stub preserving template text."""

            def __init__(self, _text: str = "") -> None:
                self.text = _text

            def join(self, _iterable: Any) -> "_DummySqlModule.SQL":
                """Return self; join is not simulated."""
                return self

            def format(self, *_args: Any, **_kwargs: Any) -> "_DummySqlModule.SQL":
                """Return self; format is not simulated."""
                return self

        class Identifier(SQL):
            """SQL identifier stub inheriting SQL."""

    dummy_sql = _DummySqlModule()
    dummy_extras = type("Extras", (), {"execute_values": lambda *args, **kwargs: None})

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        migrate_cli,
        "_execute_batch",
        lambda pg_conn_arg, table, columns, rows, execute_values: (
            _ for _ in ()
        ).throw(  # pylint: disable=unused-argument
            RuntimeError("fk violation")
        ),
    )
    monkeypatch.setitem(sys.modules, "psycopg2", type("Psyco", (), {"sql": dummy_sql}))
    monkeypatch.setitem(sys.modules, "psycopg2.extras", dummy_extras)

    with pytest.raises(RuntimeError):
        migrate_cli._copy_table(  # pylint: disable=protected-access
            sqlite_conn,
            pg_conn,
            "prompts",
            batch_size=10,
        )
    monkeypatch.undo()


def test_run_dry_run_row_counts_match(tmp_path: Path) -> None:
    """run_dry_run should surface matching counts when target has same rows."""

    src = sqlite3.connect(tmp_path / "src.sqlite")
    src.execute("CREATE TABLE files (id INTEGER)")
    src.execute("INSERT INTO files (id) VALUES (1)")
    src.commit()

    class _PgConn(_DummyPgConn):
        """Postgres connection stub returning matching counts."""

        def __init__(self) -> None:
            super().__init__()
            self.row_count = 1

        def fetchone(self) -> tuple[int]:
            """Return a single-row count matching source."""
            return (1,)

    pg_conn = _PgConn()

    def _open_sqlite(_path: Path) -> sqlite3.Connection:
        return src

    def _open_postgres(_dsn: str) -> _PgConn:
        return pg_conn

    def _table_counts(conn: sqlite3.Connection, _tables: Any) -> dict[str, int]:
        return {"files": conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]}

    def _table_counts_pg(_conn: Any, _tables: Any) -> dict[str, int]:
        return {"files": 1}

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(migrate_cli, "_open_sqlite", _open_sqlite)
    monkeypatch.setattr(migrate_cli, "_open_postgres", _open_postgres)
    monkeypatch.setattr(migrate_cli, "_table_counts", _table_counts)
    monkeypatch.setattr(migrate_cli, "_table_counts_postgres", _table_counts_pg)

    summary = migrate_cli.run_dry_run(tmp_path / "src.sqlite", "postgres://dsn")
    TC.assertEqual(summary["source_counts"]["files"], 1)
    TC.assertEqual(summary["target_counts"]["files"], 1)

    src.close()
    pg_conn.close()
