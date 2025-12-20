"""Tests for core base types (AI-assisted by Codex GPT-5)."""

# pylint: disable=abstract-method

from __future__ import annotations

from pathlib import Path
import unittest

from src.core.models.base_types import AgentConfig, AgentFeatures

TC = unittest.TestCase()


def test_agent_features_defaults_false() -> None:
    """AgentFeatures should default all flags to False."""

    features = AgentFeatures()
    TC.assertFalse(features.supports_streaming)
    TC.assertFalse(features.supports_function_calls)
    TC.assertFalse(features.supports_tool_usage)
    TC.assertFalse(features.supports_context_window)
    TC.assertFalse(features.supports_file_edits)


def test_agent_config_requires_validate() -> None:
    """AgentConfig subclasses must implement abstract methods."""

    class DummyConfig(AgentConfig):
        """Stub AgentConfig for abstract checks."""

        def __init__(self) -> None:
            super().__init__("dummy", Path.cwd(), features=None)

    TC.assertTrue(getattr(DummyConfig, "__abstractmethods__", None))


def test_agent_config_assigns_fields() -> None:
    """AgentConfig should persist constructor arguments."""

    class MinimalConfig(AgentConfig):
        """Concrete AgentConfig for serialization tests."""

        def __init__(self) -> None:
            """Initialize with default workspace and streaming enabled."""
            super().__init__(
                agent_type="mini",
                root_path=Path("/workspace"),
                features=AgentFeatures(supports_streaming=True),
            )

        def validate(self) -> None:
            """No-op validation."""
            return None

        def to_dict(self) -> dict[str, str]:
            """Serialize to dictionary."""
            return {"type": self.agent_type, "root": str(self.root_path)}

        @classmethod
        def from_dict(
            cls, data: dict[str, str]  # pylint: disable=unused-argument
        ) -> "MinimalConfig":
            """Deserialize from dictionary."""
            return cls()

    cfg = MinimalConfig()
    TC.assertEqual(cfg.agent_type, "mini")
    TC.assertEqual(cfg.root_path, Path("/workspace"))
    TC.assertTrue(cfg.features and cfg.features.supports_streaming)
