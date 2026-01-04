"""CoPilot ingestion configuration (AI-assisted by Claude Haiku 4.5).

Defines configuration options for parsing and ingesting GitHub CoPilot
chat sessions into the database.
"""

# pylint: disable=too-few-public-methods

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass
class CoPilotConfig:
    """Configuration for CoPilot session ingestion.

    Attributes:
        root_path: Path to VS Code workspaceStorage directory containing
                   chatSessions subdirectories. If None, CoPilot parsing
                   is disabled.
        enabled: Whether to parse CoPilot sessions at all.
        verbose: Enable verbose logging during parsing.
        batch_size: Number of sessions to process per batch.
        workspace_id: Optional workspace identifier to tag all ingested sessions.
        preserve_raw_json: Store raw JSON alongside structured data for auditing.
    """

    root_path: Optional[Path] = None
    enabled: bool = False
    verbose: bool = False
    batch_size: int = 10
    workspace_id: Optional[str] = None
    preserve_raw_json: bool = True

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        # Note: root_path is already Path type from dataclass, no conversion needed
        if self.root_path is not None and not self.root_path.exists():
            raise ValueError(f"CoPilot root_path does not exist: {self.root_path}")

        if self.batch_size < 1:
            raise ValueError("batch_size must be at least 1")

    @classmethod
    def from_dict(cls, config_dict: dict[str, Any]) -> CoPilotConfig:
        """Create a CoPilotConfig from a dictionary (e.g., from TOML).

        Args:
            config_dict: Configuration dictionary with optional keys:
                        - root_path (str or Path)
                        - enabled (bool)
                        - verbose (bool)
                        - batch_size (int)
                        - workspace_id (str)
                        - preserve_raw_json (bool)

        Returns:
            CoPilotConfig instance.
        """
        root_path_value = config_dict.get("root_path")
        root_path: Optional[Path] = None
        if root_path_value:
            if isinstance(root_path_value, str):
                root_path = Path(root_path_value).expanduser()
            elif isinstance(root_path_value, Path):
                root_path = root_path_value

        return cls(
            root_path=root_path,
            enabled=config_dict.get("enabled", False),
            verbose=config_dict.get("verbose", False),
            batch_size=config_dict.get("batch_size", 10),
            workspace_id=config_dict.get("workspace_id"),
            preserve_raw_json=config_dict.get("preserve_raw_json", True),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization.

        Returns:
            Configuration as a dictionary.
        """
        return {
            "root_path": str(self.root_path) if self.root_path else None,
            "enabled": self.enabled,
            "verbose": self.verbose,
            "batch_size": self.batch_size,
            "workspace_id": self.workspace_id,
            "preserve_raw_json": self.preserve_raw_json,
        }
