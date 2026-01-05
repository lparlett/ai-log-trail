"""Load user configuration for AI Log Trail.

Purpose: Load and validate user configuration for locating AI agent session data.
Author: Codex with Lauren Parlett
Date: 2025-10-30
AI-assisted: Updated with Codex (GPT-5) and Claude Haiku 4.5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import os
from pathlib import Path
from typing import Any

from src.agents.copilot.config import CoPilotConfig

try:
    _toml_module = importlib.import_module("tomllib")
except ModuleNotFoundError:  # pragma: no cover - exercised via test shim
    _toml_module = importlib.import_module("tomli")

_toml_loads = _toml_module.loads
_TOMLDecodeError = _toml_module.TOMLDecodeError


class ConfigError(RuntimeError):
    """Raised when configuration cannot be loaded or validated."""


@dataclass(frozen=True)
class DatabaseConfig:
    """Database connection preferences."""

    backend: str = "sqlite"  # sqlite or postgres
    sqlite_path: Path = Path("reports") / "session_data.sqlite"
    postgres_dsn: str | None = None


@dataclass(frozen=True)
class OutputPaths:
    """Output destinations for generated artifacts."""

    reports_dir: Path = Path("reports")


@dataclass(frozen=True)
class SessionsConfig:
    """User-defined settings for locating Codex and CoPilot session logs."""

    codex_root: Path | None = None  # Codex sessions path
    copilot_root: Path | None = None  # CoPilot sessions path
    ingest_batch_size: int = 1000
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    outputs: OutputPaths = field(default_factory=OutputPaths)
    copilot_config: CoPilotConfig = field(default_factory=CoPilotConfig)


def load_config(config_path: Path | None = None) -> SessionsConfig:
    """Load configuration from ``user/config.toml`` unless overridden."""

    path = config_path or Path("user") / "config.toml"
    if not path.exists():
        raise ConfigError(
            f"Configuration file not found at {path}. "
            "Copy user/config.example.toml to user/config.toml and set "
            "codex_root and/or copilot_root."
        )

    try:
        data = _toml_loads(path.read_text(encoding="utf-8"))
    except _TOMLDecodeError as exc:
        raise ConfigError(f"Config at {path} is not valid TOML: {exc}") from exc

    sessions = data.get("sessions")
    if not isinstance(sessions, dict):
        raise ConfigError("Missing [sessions] table in configuration.")

    # Load Codex and CoPilot roots (at least one should be specified)
    codex_root_value = sessions.get("codex_root")
    codex_root = (
        Path(codex_root_value).expanduser().resolve() if codex_root_value else None
    )
    if codex_root and not codex_root.exists():
        raise ConfigError(f"Configured codex_root does not exist: {codex_root}")

    copilot_root_value = sessions.get("copilot_root")
    copilot_root = (
        Path(copilot_root_value).expanduser().resolve() if copilot_root_value else None
    )
    if copilot_root and not copilot_root.exists():
        raise ConfigError(f"Configured copilot_root does not exist: {copilot_root}")

    if not codex_root and not copilot_root:
        raise ConfigError(
            "Configuration requires at least one of codex_root or copilot_root under [sessions]."
        )

    ingest_config = data.get("ingest", {})
    batch_size = _load_batch_size(ingest_config)
    database_cfg = _load_database_config(ingest_config, data.get("database", {}))
    outputs_cfg = _load_outputs_config(data.get("outputs", {}))
    copilot_cfg = _load_copilot_config(
        data.get("agents", {}).get("copilot", {}), copilot_root
    )

    return SessionsConfig(
        codex_root=codex_root,
        copilot_root=copilot_root,
        ingest_batch_size=batch_size,
        database=database_cfg,
        outputs=outputs_cfg,
        copilot_config=copilot_cfg,
    )


def _load_batch_size(ingest_config: dict[str, Any] | None) -> int:
    """Return validated ingest batch size."""

    batch_size = 1000
    if isinstance(ingest_config, dict):
        override = ingest_config.get("batch_size")
        if override is not None:
            if not isinstance(override, int) or override <= 0:
                raise ConfigError(
                    "ingest.batch_size must be a positive integer when provided."
                )
            batch_size = override
    return batch_size


def _load_database_config(
    ingest_config: dict[str, Any] | None, database_table: dict[str, Any] | None
) -> DatabaseConfig:
    """Load database configuration with sensible defaults."""

    sqlite_path, user_supplied_sqlite = _determine_sqlite_path(
        ingest_config, database_table
    )
    backend, postgres_dsn = _determine_backend(database_table)

    _validate_backend(backend, postgres_dsn)

    sqlite_path = _validate_sqlite_path(
        sqlite_path,
        create_if_missing=not user_supplied_sqlite,
    )

    return DatabaseConfig(
        backend=backend,
        sqlite_path=sqlite_path,
        postgres_dsn=postgres_dsn,
    )


def _determine_sqlite_path(
    ingest_config: dict[str, Any] | None, database_table: dict[str, Any] | None
) -> tuple[Path, bool]:
    """Return sqlite path and whether the user supplied it."""

    sqlite_path = Path("reports") / "session_data.sqlite"
    user_supplied = False

    if isinstance(ingest_config, dict):
        db_path = ingest_config.get("db_path")
        if isinstance(db_path, str) and db_path.strip():
            sqlite_path = Path(db_path)
            user_supplied = True

    if isinstance(database_table, dict):
        sqlite_override = database_table.get("sqlite_path")
        if isinstance(sqlite_override, str) and sqlite_override.strip():
            sqlite_path = Path(sqlite_override)
            user_supplied = True

    return sqlite_path, user_supplied


def _determine_backend(
    database_table: dict[str, Any] | None,
) -> tuple[str, str | None]:
    """Return backend and optional Postgres DSN from the database table."""

    backend = "sqlite"
    postgres_dsn: str | None = None

    if isinstance(database_table, dict):
        backend_value = database_table.get("backend")
        if isinstance(backend_value, str) and backend_value.strip():
            backend = backend_value.strip().lower()
        dsn_value = database_table.get("postgres_dsn")
        if isinstance(dsn_value, str) and dsn_value.strip():
            postgres_dsn = dsn_value.strip()

    return backend, postgres_dsn


def _validate_backend(backend: str, postgres_dsn: str | None) -> None:
    """Validate backend choice and required DSN."""

    if backend not in {"sqlite", "postgres"}:
        raise ConfigError("database.backend must be either 'sqlite' or 'postgres'.")

    if backend == "postgres" and not postgres_dsn:
        raise ConfigError("database.postgres_dsn is required when backend=postgres.")


def _load_outputs_config(outputs_table: dict[str, Any] | None) -> OutputPaths:
    """Load and validate output directory configuration."""

    reports_dir = Path("reports")
    if isinstance(outputs_table, dict):
        reports_value = outputs_table.get("reports_dir")
        if isinstance(reports_value, str) and reports_value.strip():
            reports_dir = Path(reports_value)

    resolved_reports_dir = _validate_existing_directory(
        reports_dir,
        "outputs.reports_dir",
        create_if_missing=True,
    )
    return OutputPaths(reports_dir=resolved_reports_dir)


def _validate_existing_directory(
    path: Path, label: str, *, create_if_missing: bool
) -> Path:
    """Ensure a path exists and is a directory with write permission."""

    resolved = path.expanduser().resolve()
    if not resolved.exists():
        if create_if_missing:
            resolved.mkdir(parents=True, exist_ok=True)
        else:
            raise ConfigError(f"{label} does not exist: {resolved}")
    if not resolved.is_dir():
        raise ConfigError(f"{label} is not a directory: {resolved}")
    if not os.access(resolved, os.W_OK):
        raise ConfigError(f"{label} is not writable: {resolved}")
    return resolved


def _validate_sqlite_path(
    sqlite_path: Path,
    *,
    create_if_missing: bool,
) -> Path:
    """Validate SQLite database path and parent directory accessibility."""

    resolved = sqlite_path.expanduser().resolve()
    if resolved.exists() and resolved.is_dir():
        raise ConfigError(f"Configured database path is a directory: {resolved}")

    parent = resolved.parent
    if not parent.exists():
        if create_if_missing:
            parent.mkdir(parents=True, exist_ok=True)
        else:
            raise ConfigError(f"Database parent directory does not exist: {parent}")
    if not parent.is_dir():
        raise ConfigError(f"Database parent is not a directory: {parent}")
    if not os.access(parent, os.W_OK):
        raise ConfigError(f"Database parent directory is not writable: {parent}")
    return resolved


def _load_copilot_config(
    copilot_table: dict[str, Any] | None,
    copilot_root: Path | None,
) -> CoPilotConfig:
    """Load CoPilot-specific configuration.

    Args:
        copilot_table: [agents.copilot] section from config.toml.
        copilot_root: Resolved path to CoPilot sessions directory.

    Returns:
        CoPilotConfig instance with sensible defaults.
    """
    if not copilot_table:
        copilot_table = {}

    config_dict = {
        "root_path": copilot_root,
        "enabled": bool(copilot_root),
        "verbose": copilot_table.get("verbose", False),
        "batch_size": copilot_table.get("batch_size", 10),
        "workspace_id": copilot_table.get("workspace_id"),
        "preserve_raw_json": copilot_table.get("preserve_raw_json", True),
    }

    return CoPilotConfig.from_dict(config_dict)
