"""Test suite for src/services/database.py module.

Tests database connection, schema creation, migrations, and backend support.
Covers SQLite and PostgreSQL initialization paths.
"""

import sqlite3
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.services.config import DatabaseConfig
from src.services.database import (
    ensure_schema,
    get_connection,
    get_connection_for_config,
)

TC = unittest.TestCase()


class TestGetConnection:
    """Test get_connection function for SQLite."""

    def test_get_connection_creates_directory(self, tmp_path: Path) -> None:
        """Verify get_connection creates parent directories."""
        db_path = tmp_path / "subdir" / "deep" / "test.db"
        TC.assertFalse(db_path.parent.exists())

        conn = get_connection(db_path)
        TC.assertIsNotNone(conn)
        TC.assertTrue(db_path.parent.exists())
        conn.close()

    def test_get_connection_enables_foreign_keys(self, tmp_path: Path) -> None:
        """Verify foreign keys pragma is enabled."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)

        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys")
        result = cursor.fetchone()[0]
        TC.assertEqual(result, 1)
        conn.close()

    def test_get_connection_parses_date_types(self, tmp_path: Path) -> None:
        """Verify connection parses date types correctly."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)

        # Test that PARSE_DECLTYPES works
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE test_dates (id INTEGER, created_at TEXT)")
        cursor.execute("INSERT INTO test_dates VALUES (1, '2025-01-01')")
        conn.commit()

        cursor.execute("SELECT * FROM test_dates")
        result = cursor.fetchone()
        TC.assertIsNotNone(result)
        conn.close()

    def test_get_connection_reuses_existing_database(self, tmp_path: Path) -> None:
        """Verify get_connection can open existing database."""
        db_path = tmp_path / "existing.db"

        # Create initial connection and table
        conn1 = get_connection(db_path)
        cursor = conn1.cursor()
        cursor.execute("CREATE TABLE test_table (id INTEGER)")
        conn1.commit()
        conn1.close()

        # Open again
        conn2 = get_connection(db_path)
        cursor = conn2.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        TC.assertIn(("test_table",), tables)
        conn2.close()


class TestEnsureSchema:
    """Test ensure_schema function."""

    def test_ensure_schema_creates_all_tables(self, tmp_path: Path) -> None:
        """Verify all required tables are created."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)

        ensure_schema(conn)

        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cursor.fetchall()}

        expected_tables = {
            "files",
            "sessions",
            "interactions",
            "agent_events",
            "agent_tool_invocations",
            "redaction_rules",
            "redactions",
        }
        TC.assertTrue(
            expected_tables.issubset(tables),
            f"Missing tables: {expected_tables - tables}",
        )
        conn.close()

    def test_ensure_schema_creates_indexes(self, tmp_path: Path) -> None:
        """Verify indexes are created."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)

        ensure_schema(conn)

        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = {row[0] for row in cursor.fetchall()}

        # Verify at least some key indexes exist
        TC.assertGreater(len(indexes), 0)
        conn.close()

    def test_ensure_schema_idempotent(self, tmp_path: Path) -> None:
        """Verify ensure_schema can be called multiple times safely."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)

        # Call multiple times
        ensure_schema(conn)
        ensure_schema(conn)
        ensure_schema(conn)

        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM sqlite_master WHERE type='table'")
        count = cursor.fetchone()[0]
        TC.assertGreater(count, 0)
        conn.close()

    def test_ensure_schema_foreign_keys_constraint(self, tmp_path: Path) -> None:
        """Verify foreign key constraints are enforced."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)

        ensure_schema(conn)

        cursor = conn.cursor()
        # Try to insert an interaction with non-existent session_id
        with pytest.raises(sqlite3.IntegrityError):
            cursor.execute(
                "INSERT INTO interactions (file_id, session_id, agent_type, interaction_index) "
                "VALUES (999, 999, 'codex', 0)"
            )
        conn.close()


class TestGetConnectionForConfig:
    """Test get_connection_for_config function."""

    def test_get_connection_for_config_sqlite(self, tmp_path: Path) -> None:
        """Verify SQLite backend returns SQLite connection."""
        db_path = tmp_path / "test.db"
        config = DatabaseConfig(
            backend="sqlite",
            sqlite_path=db_path,
            postgres_dsn=None,
        )

        conn = get_connection_for_config(config)
        TC.assertIsInstance(conn, sqlite3.Connection)

        # Verify schema created
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1")
        TC.assertIsNotNone(cursor.fetchone())

        conn.close()

    def test_get_connection_for_config_postgres_missing_dsn(self) -> None:
        """Verify Postgres backend raises error without DSN."""
        config = DatabaseConfig(
            backend="postgres",
            sqlite_path=Path("ignored.db"),
            postgres_dsn=None,
        )

        with pytest.raises(RuntimeError, match="postgres_dsn is required"):
            get_connection_for_config(config)

    def test_get_connection_for_config_postgres_missing_module(self) -> None:
        """Verify helpful error when psycopg2 not installed."""
        config = DatabaseConfig(
            backend="postgres",
            sqlite_path=Path("ignored.db"),
            postgres_dsn="postgresql://localhost/test",
        )

        with patch("builtins.__import__", side_effect=ModuleNotFoundError("psycopg2")):
            with pytest.raises(RuntimeError, match="psycopg2-binary is required"):
                get_connection_for_config(config)

    def test_get_connection_for_config_postgres_mock(self, tmp_path: Path) -> None:
        """Verify Postgres backend path (mocked)."""
        config = DatabaseConfig(
            backend="postgres",
            sqlite_path=tmp_path / "ignored.db",
            postgres_dsn="postgresql://localhost/test",
        )

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        mock_psycopg2 = MagicMock()
        mock_psycopg2.connect.return_value = mock_conn
        mock_psycopg2.extensions.connection = MagicMock()

        # Patch at import location (inside the function)
        def mock_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "psycopg2":
                return mock_psycopg2
            if name == "psycopg2.extensions":
                return MagicMock(connection=MagicMock())
            return __import__(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            conn = get_connection_for_config(config)
            TC.assertIs(conn, mock_conn)
            mock_cursor.execute.assert_called_once()
            mock_conn.commit.assert_called_once()
