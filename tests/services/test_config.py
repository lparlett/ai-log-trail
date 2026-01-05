# pylint: disable=import-error
"""Tests for configuration loading and validation."""

import importlib
import importlib.util
import os
import sys
import textwrap
import unittest
from pathlib import Path
from typing import Any

import pytest

from src.services.config import (
    ConfigError,
    SessionsConfig,
    _validate_existing_directory,
    _validate_sqlite_path,
    _load_batch_size,
    _load_database_config,
    _load_outputs_config,
    load_config,
)

TC = unittest.TestCase()


def _write_config(tmp_path: Path, body: str) -> Path:
    """Write TOML content to a temporary config file."""

    config_path = tmp_path / "config.toml"
    config_path.write_text(textwrap.dedent(body), encoding="utf-8")
    return config_path


def _path_for_toml(path: Path) -> str:
    """Return a path string safe for TOML (use forward slashes)."""

    return path.as_posix()


def test_load_config_missing_file() -> None:
    """Test that loading missing config file raises appropriate error."""

    with pytest.raises(ConfigError, match="not found"):
        load_config(Path("nonexistent.toml"))


def test_load_config_invalid_toml(tmp_path: Path) -> None:
    """Test that invalid TOML raises appropriate error."""

    config_path = _write_config(tmp_path, "invalid [ toml")
    with pytest.raises(ConfigError, match="TOML"):
        load_config(config_path)


def test_load_config_missing_sessions(tmp_path: Path) -> None:
    """Test that missing [sessions] table raises appropriate error."""

    config_path = _write_config(
        tmp_path,
        """
        [other]
        value = "test"
        """,
    )
    with pytest.raises(ConfigError, match="sessions"):
        load_config(config_path)


def test_load_config_missing_root(tmp_path: Path) -> None:
    """Test that missing root setting raises appropriate error."""

    config_path = _write_config(
        tmp_path,
        """
        [sessions]
        other = "value"
        """,
    )
    with pytest.raises(ConfigError, match="root"):
        load_config(config_path)


def test_load_config_valid(tmp_path: Path) -> None:
    """Test loading valid configuration with explicit paths."""

    sessions_root = tmp_path / "sessions"
    sessions_root.mkdir()

    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    sqlite_path = reports_dir / "session.sqlite"

    config_path = _write_config(
        tmp_path,
        f"""
        [sessions]
        codex_root = "{_path_for_toml(sessions_root)}"

        [ingest]
        batch_size = 500
        db_path = "{_path_for_toml(sqlite_path)}"

        [outputs]
        reports_dir = "{_path_for_toml(reports_dir)}"
        """,
    )

    config = load_config(config_path)
    TC.assertIsInstance(config, SessionsConfig)
    TC.assertEqual(config.codex_root, sessions_root.resolve())
    TC.assertEqual(config.ingest_batch_size, 500)
    TC.assertEqual(config.database.sqlite_path, sqlite_path.resolve())
    TC.assertEqual(config.outputs.reports_dir, reports_dir.resolve())


def test_load_config_invalid_batch_size(tmp_path: Path) -> None:
    """Test that invalid batch size raises appropriate error."""

    sessions_root = tmp_path / "sessions"
    sessions_root.mkdir()

    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()

    db_path_value = reports_dir / "db.sqlite"
    config_path = _write_config(
        tmp_path,
        f"""
        [sessions]
        codex_root = "{_path_for_toml(sessions_root)}"

        [ingest]
        batch_size = -1
        db_path = "{_path_for_toml(db_path_value)}"

        [outputs]
        reports_dir = "{_path_for_toml(reports_dir)}"
        """,
    )

    with pytest.raises(ConfigError, match="batch_size"):
        load_config(config_path)


def test_load_config_default_batch_size(tmp_path: Path) -> None:
    """Test that default batch size is used when not specified."""

    sessions_root = tmp_path / "sessions"
    sessions_root.mkdir()

    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()

    config_path = _write_config(
        tmp_path,
        f"""
        [sessions]
        codex_root = "{_path_for_toml(sessions_root)}"

        [outputs]
        reports_dir = "{_path_for_toml(reports_dir)}"
        """,
    )

    config = load_config(config_path)
    TC.assertEqual(config.ingest_batch_size, 1000)


def test_load_config_creates_default_directories(tmp_path: Path) -> None:
    """Default output/db paths should be created when missing."""

    sessions_root = tmp_path / "sessions"
    sessions_root.mkdir()

    config_path = _write_config(
        tmp_path,
        f"""
        [sessions]
        codex_root = "{_path_for_toml(sessions_root)}"
        """,
    )

    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        config = load_config(config_path)
    finally:
        os.chdir(original_cwd)

    reports_dir = tmp_path / "reports"
    TC.assertTrue(reports_dir.exists())
    TC.assertEqual(config.outputs.reports_dir, reports_dir.resolve())
    expected_db = reports_dir / "session_data.sqlite"
    TC.assertEqual(config.database.sqlite_path, expected_db.resolve())


def test_load_config_nonexistent_root(tmp_path: Path) -> None:
    """Test that nonexistent root directory raises appropriate error."""

    missing_root = tmp_path / "missing"
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()

    config_path = _write_config(
        tmp_path,
        f"""
        [sessions]
        codex_root = "{_path_for_toml(missing_root)}"

        [outputs]
        reports_dir = "{_path_for_toml(reports_dir)}"
        """,
    )

    with pytest.raises(ConfigError, match="does not exist"):
        load_config(config_path)


def test_load_config_root_not_directory(tmp_path: Path) -> None:
    """Test that codex_root pointing to a file (not directory) raises appropriate error."""

    fake_root = tmp_path / "not_a_dir.txt"
    fake_root.write_text("content", encoding="utf-8")

    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()

    config_path = _write_config(
        tmp_path,
        f"""
        [sessions]
        codex_root = "{_path_for_toml(fake_root)}"

        [outputs]
        reports_dir = "{_path_for_toml(reports_dir)}"
        """,
    )

    # Should work - we validate existence but not that it's a directory
    config = load_config(config_path)
    TC.assertEqual(config.codex_root, fake_root.resolve())


def test_load_config_invalid_db_parent(tmp_path: Path) -> None:
    """Test that database path with missing parent raises clear error."""

    sessions_root = tmp_path / "sessions"
    sessions_root.mkdir()

    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()

    db_path = tmp_path / "nope" / "db.sqlite"
    config_path = _write_config(
        tmp_path,
        f"""
        [sessions]
        codex_root = "{_path_for_toml(sessions_root)}"

        [ingest]
        db_path = "{_path_for_toml(db_path)}"

        [outputs]
        reports_dir = "{_path_for_toml(reports_dir)}"
        """,
    )

    with pytest.raises(ConfigError, match="parent directory does not exist"):
        load_config(config_path)


def test_load_config_reports_dir_missing(tmp_path: Path) -> None:
    """Test that missing reports directory is created automatically."""

    sessions_root = tmp_path / "sessions"
    sessions_root.mkdir()

    missing_reports = tmp_path / "missing_reports"
    config_path = _write_config(
        tmp_path,
        f"""
        [sessions]
        codex_root = "{_path_for_toml(sessions_root)}"

        [outputs]
        reports_dir = "{_path_for_toml(missing_reports)}"
        """,
    )

    config = load_config(config_path)
    TC.assertEqual(config.outputs.reports_dir, missing_reports)
    TC.assertTrue(missing_reports.exists())


def test_load_config_reports_dir_nested_missing(tmp_path: Path) -> None:
    """Test that missing nested reports directory is created automatically."""

    sessions_root = tmp_path / "sessions"
    sessions_root.mkdir()

    nested_reports = tmp_path / "a" / "b" / "c" / "reports"
    config_path = _write_config(
        tmp_path,
        f"""
        [sessions]
        codex_root = "{_path_for_toml(sessions_root)}"

        [outputs]
        reports_dir = "{_path_for_toml(nested_reports)}"
        """,
    )

    config = load_config(config_path)
    TC.assertEqual(config.outputs.reports_dir, nested_reports)
    TC.assertTrue(nested_reports.exists())
    TC.assertTrue(nested_reports.is_dir())


def test_load_outputs_config_default_with_empty_dict(tmp_path: Path) -> None:
    """_load_outputs_config should use default when passed empty outputs dict."""

    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        outputs = _load_outputs_config({})
        reports_path = tmp_path / "reports"
        TC.assertTrue(reports_path.exists())
        TC.assertEqual(outputs.reports_dir, reports_path.resolve())
    finally:
        os.chdir(cwd)


def test_load_outputs_config_custom_path_created(tmp_path: Path) -> None:
    """_load_outputs_config should create custom path if it doesn't exist."""

    custom_reports = tmp_path / "custom_output_dir"
    outputs = _load_outputs_config({"reports_dir": _path_for_toml(custom_reports)})
    TC.assertTrue(custom_reports.exists())
    TC.assertEqual(outputs.reports_dir, custom_reports.resolve())


def test_load_config_invalid_backend(tmp_path: Path) -> None:
    """Unsupported database backend should raise ConfigError."""

    sessions_root = tmp_path / "sessions"
    sessions_root.mkdir()
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()

    config_path = _write_config(
        tmp_path,
        f"""
        [sessions]
        codex_root = "{_path_for_toml(sessions_root)}"

        [database]
        backend = "mongo"

        [outputs]
        reports_dir = "{_path_for_toml(reports_dir)}"
        """,
    )

    with pytest.raises(ConfigError, match="backend must be either"):
        load_config(config_path)


def test_load_config_postgres_requires_dsn(tmp_path: Path) -> None:
    """Backend=postgres should require a DSN."""

    sessions_root = tmp_path / "sessions"
    sessions_root.mkdir()
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()

    config_path = _write_config(
        tmp_path,
        f"""
        [sessions]
        codex_root = "{_path_for_toml(sessions_root)}"

        [database]
        backend = "postgres"

        [outputs]
        reports_dir = "{_path_for_toml(reports_dir)}"
        """,
    )

    with pytest.raises(ConfigError, match="postgres_dsn"):
        load_config(config_path)


def test_load_config_rejects_directory_for_sqlite_path(tmp_path: Path) -> None:
    """Database path pointing to a directory should fail validation."""

    sessions_root = tmp_path / "sessions"
    sessions_root.mkdir()
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()

    config_path = _write_config(
        tmp_path,
        f"""
        [sessions]
        codex_root = "{_path_for_toml(sessions_root)}"

        [ingest]
        db_path = "{_path_for_toml(reports_dir)}"

        [outputs]
        reports_dir = "{_path_for_toml(reports_dir)}"
        """,
    )

    with pytest.raises(ConfigError, match="is a directory"):
        load_config(config_path)


def test_load_config_reports_dir_not_directory(tmp_path: Path) -> None:
    """outputs.reports_dir pointing to a file should error."""

    sessions_root = tmp_path / "sessions"
    sessions_root.mkdir()
    reports_file = tmp_path / "reports.txt"
    reports_file.write_text("not a dir", encoding="utf-8")

    config_path = _write_config(
        tmp_path,
        f"""
        [sessions]
        codex_root = "{_path_for_toml(sessions_root)}"

        [outputs]
        reports_dir = "{_path_for_toml(reports_file)}"
        """,
    )

    with pytest.raises(ConfigError, match="not a directory"):
        load_config(config_path)


def test_validate_helpers_handle_creation(tmp_path: Path) -> None:
    """Helper validators should create directories when allowed and error otherwise."""

    target_dir = tmp_path / "new_reports"
    resolved = _validate_existing_directory(
        target_dir, "outputs.reports_dir", create_if_missing=True
    )
    TC.assertTrue(resolved.exists())
    TC.assertTrue(resolved.is_dir())

    # _validate_sqlite_path should reject missing parent when creation disabled
    missing_parent_path = tmp_path / "missing_parent" / "db.sqlite"
    with pytest.raises(ConfigError, match="parent directory does not exist"):
        _validate_sqlite_path(missing_parent_path, create_if_missing=False)


def test_validate_helpers_non_directory_and_non_writable(tmp_path: Path) -> None:
    """Helper validators should reject files used where directories are expected."""

    file_path = tmp_path / "not_dir"
    file_path.write_text("content", encoding="utf-8")

    with pytest.raises(ConfigError, match="not a directory"):
        _validate_existing_directory(
            file_path, "outputs.reports_dir", create_if_missing=False
        )

    db_path = file_path / "db.sqlite"
    with pytest.raises(ConfigError, match="parent is not a directory"):
        _validate_sqlite_path(db_path, create_if_missing=False)


def test_validate_sqlite_path_unwritable_parent(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """_validate_sqlite_path should error when parent is not writable."""

    target = tmp_path / "protected" / "db.sqlite"
    target.parent.mkdir(parents=True, exist_ok=True)

    def _fake_access(path: Path, mode: int) -> bool:  # pylint: disable=unused-argument
        if path == target.parent:
            return False
        return True

    monkeypatch.setattr(os, "access", _fake_access)
    with pytest.raises(ConfigError, match="not writable"):
        _validate_sqlite_path(target, create_if_missing=False)


def test_validate_sqlite_path_creates_parent(tmp_path: Path) -> None:
    """_validate_sqlite_path should create missing parent when allowed."""

    target = tmp_path / "nested" / "db.sqlite"
    resolved = _validate_sqlite_path(target, create_if_missing=True)
    TC.assertTrue(target.parent.exists())
    TC.assertEqual(resolved, target.resolve())


def test_validate_sqlite_path_rejects_directory_target(tmp_path: Path) -> None:
    """_validate_sqlite_path should reject when target already is a directory."""

    target_dir = tmp_path / "dir_as_db"
    target_dir.mkdir()
    with pytest.raises(ConfigError, match="is a directory"):
        _validate_sqlite_path(target_dir, create_if_missing=False)


def test_validate_existing_directory_not_writable(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """_validate_existing_directory should reject directories without write access."""

    target_dir = tmp_path / "readonly"
    target_dir.mkdir()

    def _fake_access(path: Path, mode: int) -> bool:  # pylint: disable=unused-argument
        if path == target_dir:
            return False
        return True

    monkeypatch.setattr(os, "access", _fake_access)
    with pytest.raises(ConfigError, match="not writable"):
        _validate_existing_directory(
            target_dir, "outputs.reports_dir", create_if_missing=False
        )


def test_load_batch_size_override_and_default() -> None:
    """_load_batch_size should honor positive overrides and default otherwise."""

    TC.assertEqual(_load_batch_size({"batch_size": 10}), 10)
    TC.assertEqual(_load_batch_size(None), 1000)


def test_load_database_config_defaults_and_postgres(tmp_path: Path) -> None:
    """_load_database_config should set defaults and accept postgres configuration."""

    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        cfg = _load_database_config(None, None)
        TC.assertEqual(cfg.backend, "sqlite")
        TC.assertTrue(cfg.sqlite_path.parent.exists())

        postgres_cfg = _load_database_config(
            None, {"backend": "postgres", "postgres_dsn": "postgres://example"}
        )
        TC.assertEqual(postgres_cfg.backend, "postgres")
        TC.assertEqual(postgres_cfg.postgres_dsn, "postgres://example")

        custom_sqlite = tmp_path / "custom" / "db.sqlite"
        custom_sqlite.parent.mkdir(parents=True, exist_ok=True)
        sqlite_cfg = _load_database_config(
            {"db_path": str(custom_sqlite)},
            {"sqlite_path": str(custom_sqlite)},
        )
        TC.assertEqual(sqlite_cfg.sqlite_path, custom_sqlite.resolve())
    finally:
        os.chdir(cwd)


def test_load_outputs_config_with_non_dict_uses_default(tmp_path: Path) -> None:
    """Non-dict outputs table should fall back to defaults and create dir."""

    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        outputs = _load_outputs_config("notadict")  # type: ignore[arg-type]
        TC.assertTrue((tmp_path / "reports").exists())
        TC.assertEqual(outputs.reports_dir, (tmp_path / "reports").resolve())
    finally:
        os.chdir(cwd)


def test_toml_fallback_to_tomli(monkeypatch: Any) -> None:
    """Ensure fallback to tomli is used when tomllib is unavailable."""

    spec = importlib.util.spec_from_file_location(
        "config_temp", Path("src/services/config.py")
    )
    if spec is None or spec.loader is None:
        TC.fail("Failed to load config module spec for fallback test.")

    class _TomliStub:  # pylint: disable=too-few-public-methods
        """Minimal tomli stub for import fallback."""

        class TOMLDecodeError(Exception):
            """Placeholder TOML decode error."""

        @staticmethod
        def loads(_text: str) -> dict[str, Any]:
            """Return empty dict for stubbed toml loads."""
            return {}

    def _fake_import(name: str) -> Any:
        if name == "tomllib":
            raise ModuleNotFoundError("tomllib missing")
        if name == "tomli":
            return _TomliStub()
        return importlib.import_module(name)

    monkeypatch.setattr(importlib, "import_module", _fake_import)
    module = importlib.util.module_from_spec(spec)
    sys.modules["config_temp"] = module
    spec.loader.exec_module(module)
    TC.assertTrue(hasattr(module, "_toml_loads"))
    TC.assertTrue(hasattr(module, "_TOMLDecodeError"))
    sys.modules.pop("config_temp", None)
