"""Tests for Codex action, message, and configuration components."""

# pylint: disable=import-error

from __future__ import annotations

from pathlib import Path
from datetime import datetime
import unittest

import pytest

from src.agents.codex.action import Action
from src.agents.codex.config import CodexConfig
from src.agents.codex.message import CodexMessage
from src.core.models.config_data import AgentConfigData, AgentRegistry
from src.core.models.base_types import AgentFeatures, AgentConfig
from src.agents.codex.errors import ParserError, InvalidEventError

TC = unittest.TestCase()


def test_action_roundtrip(sample_timestamp: datetime) -> None:
    """Ensure Action supports build/create/to_dict/from_dict."""
    data = Action.build_data(
        action_type="tool_call",
        session_id="sid-1",
        timestamp=sample_timestamp,
        details={"tool_name": "ls", "parameters": {"path": "."}},
        raw_data={"raw": True},
    )
    action = Action.create(data)
    serialized = action.to_dict()

    TC.assertEqual(serialized["action_type"], "tool_call")
    TC.assertEqual(serialized["tool_name"], "ls")
    TC.assertEqual(serialized["parameters"], {"path": "."})
    TC.assertEqual(serialized["raw_data"], {"raw": True})

    reconstructed = Action.from_dict(serialized)
    TC.assertEqual(reconstructed.event_type, "action.tool_call")
    TC.assertEqual(reconstructed.event_category.name, "TOOL_CALL")
    TC.assertEqual(reconstructed.session_id, "sid-1")


def test_message_roundtrip(sample_timestamp: datetime) -> None:
    """Ensure CodexMessage supports build/create/to_dict/from_dict."""
    data = CodexMessage.build_data(
        content="hello",
        is_user=True,
        session_id="sid-2",
        timestamp=sample_timestamp,
        raw_data={"raw": "msg"},
    )
    message = CodexMessage.create(data)
    serialized = message.to_dict()

    TC.assertEqual(serialized["event_type"], "user_message")
    TC.assertEqual(serialized["content"], "hello")
    TC.assertTrue(serialized["is_user"])

    reconstructed = CodexMessage.from_dict(serialized)
    TC.assertEqual(reconstructed.event_category.name, "USER_INPUT")
    TC.assertEqual(reconstructed.session_id, "sid-2")
    TC.assertEqual(reconstructed.raw_data, {"raw": "msg"})


def test_parser_error_str_includes_context(tmp_path: Path) -> None:
    """ParserError should format file and line context in __str__."""
    error = ParserError("boom", file_path=tmp_path / "log.jsonl", line_number=7)
    text = str(error)
    TC.assertIn("boom", text)
    TC.assertIn("log.jsonl", text)
    TC.assertIn("Line: 7", text)
    TC.assertIsInstance(InvalidEventError("x"), ParserError)


def test_codex_config_validate(tmp_path: Path) -> None:
    """Validate CodexConfig enforces existing directory."""
    valid_root = tmp_path / "logs"
    valid_root.mkdir()
    cfg = CodexConfig(root_path=valid_root)
    cfg.validate()  # should not raise

    missing_root = tmp_path / "missing"
    with pytest.raises(ValueError):
        CodexConfig(root_path=missing_root).validate()

    cfg_dict = cfg.to_dict()
    TC.assertEqual(cfg_dict["type"], "codex")
    TC.assertEqual(cfg_dict["root"], str(valid_root))
    TC.assertTrue(cfg_dict["features"]["streaming"])

    restored = CodexConfig.from_dict(cfg_dict)
    TC.assertEqual(restored.agent_type, "codex")
    TC.assertEqual(restored.root_path, valid_root)
    TC.assertEqual(
        restored.features.supports_streaming, cfg.features.supports_streaming
    )


def test_agent_config_data_validation() -> None:
    """AgentConfigData should reject empty agent_type."""
    with pytest.raises(ValueError):
        AgentConfigData(agent_type="", root_path=Path.cwd())


# pylint: disable=unused-argument
# tmp_path kept in signature for pytest fixture flexibility
def test_agent_registry_register_and_get(tmp_path: Path) -> None:
    """AgentRegistry should store and return config classes."""

    class DummyConfig(AgentConfig):
        """Minimal config for registry testing."""

        agent_type = "dummy"

        def __init__(self, root_path: Path) -> None:
            """Initialize with root path."""
            super().__init__("dummy", root_path, AgentFeatures())

        def validate(self) -> None:
            """No-op validation."""
            return None

        def to_dict(self) -> dict[str, str]:
            """Serialize to dictionary."""
            return {"root": str(self.root_path)}

        @classmethod
        def from_dict(cls, data: dict[str, str]) -> "DummyConfig":
            """Deserialize from dictionary."""
            return cls(Path(data["root"]))

    AgentRegistry.register(DummyConfig)
    retrieved = AgentRegistry.get("dummy")
    TC.assertIs(retrieved, DummyConfig)
    TC.assertIs(AgentRegistry.all().get("dummy"), DummyConfig)
