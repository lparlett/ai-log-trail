"""Tests for agent configuration models."""

# pylint: disable=import-error

from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from src.core.models.config_data import AgentConfigData, AgentFeatures


def test_agent_features_validation() -> None:
    """Test AgentFeatures validation."""
    test_case = unittest.TestCase()

    # Test valid features with defaults
    features = AgentFeatures()
    test_case.assertFalse(features.supports_streaming)
    test_case.assertFalse(features.supports_function_calls)
    test_case.assertFalse(features.supports_tool_usage)
    test_case.assertFalse(features.supports_context_window)
    test_case.assertFalse(features.supports_file_edits)

    # Test explicit values
    features = AgentFeatures(supports_streaming=True, supports_file_edits=True)
    test_case.assertTrue(features.supports_streaming)
    test_case.assertTrue(features.supports_file_edits)
    test_case.assertFalse(features.supports_function_calls)

    # Test immutability
    with test_case.assertRaises(FrozenInstanceError):
        features.supports_streaming = False  # type: ignore # Raises FrozenInstanceError


def test_agent_config_validation() -> None:
    """Test AgentConfigData validation."""
    test_case = unittest.TestCase()
    test_path = Path("/test/path")

    # Test valid config
    features = AgentFeatures(supports_streaming=True, supports_file_edits=True)
    config = AgentConfigData(agent_type="test", root_path=test_path, features=features)

    test_case.assertEqual(config.agent_type, "test")
    test_case.assertEqual(config.root_path, test_path)
    test_case.assertEqual(config.features, features)

    # Test validation rules
    with test_case.assertRaises(ValueError):
        AgentConfigData(
            agent_type="",  # Empty string should fail
            root_path=test_path,
            features=features,
        )

    # Test optional features
    config_no_features = AgentConfigData(agent_type="test", root_path=test_path)
    test_case.assertIsNone(config_no_features.features)
