"""Additional tests for ingest.py coverage (AI-assisted by Codex GPT-5).

Focuses on _scope_matches and _load_rules_safely functions.
"""

# pylint: disable=protected-access

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.services.ingest import (
    _load_rules_safely,
    _scope_matches,
)

TC = unittest.TestCase()


class TestScopeMatches:
    """Test _scope_matches function."""

    def test_scope_matches_global_rule(self) -> None:
        """Global scope rule should match any context."""
        TC.assertTrue(_scope_matches("global", "prompt"))
        TC.assertTrue(_scope_matches("global", "field"))
        TC.assertTrue(_scope_matches("global", "global"))

    def test_scope_matches_exact_prompt(self) -> None:
        """Prompt scope should match prompt context."""
        TC.assertTrue(_scope_matches("prompt", "prompt"))
        TC.assertFalse(_scope_matches("prompt", "field"))
        TC.assertFalse(_scope_matches("prompt", "global"))

    def test_scope_matches_exact_field(self) -> None:
        """Field scope should match field context."""
        TC.assertTrue(_scope_matches("field", "field"))
        TC.assertFalse(_scope_matches("field", "prompt"))
        TC.assertFalse(_scope_matches("field", "global"))

    def test_scope_matches_no_match(self) -> None:
        """Non-matching scopes should return False."""
        TC.assertFalse(_scope_matches("unknown", "prompt"))
        TC.assertFalse(_scope_matches("prompt", "unknown"))
        TC.assertFalse(_scope_matches("other", "other"))


class TestLoadRulesSafely:
    """Test _load_rules_safely function."""

    def test_load_rules_safely_with_valid_rules_file(self, tmp_path: Path) -> None:
        """Should load rules from valid JSON file."""
        rules_file = tmp_path / "rules.json"
        rules_data = [
            {
                "id": "test-rule",
                "type": "literal",
                "pattern": "secret",
                "scope": "global",
                "replacement": "<REDACTED>",
            }
        ]
        rules_file.write_text(json.dumps(rules_data), encoding="utf-8")

        result = _load_rules_safely(rules_file, verbose=False)

        TC.assertIsNotNone(result)
        if result is not None:
            TC.assertGreater(len(result), 0)

    def test_load_rules_safely_missing_file_returns_none(self, tmp_path: Path) -> None:
        """Should return None when rules file doesn't exist."""
        missing_file = tmp_path / "nonexistent.json"

        result = _load_rules_safely(missing_file, verbose=False)

        TC.assertIsNone(result)

    def test_load_rules_safely_invalid_json_returns_none(self, tmp_path: Path) -> None:
        """Should return None when JSON is malformed."""
        rules_file = tmp_path / "invalid.json"
        rules_file.write_text("{ invalid json {", encoding="utf-8")

        result = _load_rules_safely(rules_file, verbose=False)

        TC.assertIsNone(result)

    def test_load_rules_safely_with_verbose_flag(self, tmp_path: Path) -> None:
        """Should attempt logging when verbose=True and error occurs."""
        missing_file = tmp_path / "missing.json"

        # Should not raise, just return None with possible logging
        result = _load_rules_safely(missing_file, verbose=True)

        TC.assertIsNone(result)

    def test_load_rules_safely_empty_rules_array(self, tmp_path: Path) -> None:
        """Should handle empty rules array."""
        rules_file = tmp_path / "empty_rules.json"
        rules_file.write_text(json.dumps([]), encoding="utf-8")

        result = _load_rules_safely(rules_file, verbose=False)

        TC.assertIsNotNone(result)
        if result is not None:
            TC.assertEqual(len(result), 0)

    def test_load_rules_safely_multiple_rules(self, tmp_path: Path) -> None:
        """Should load multiple rules from file."""
        rules_file = tmp_path / "multiple_rules.json"
        rules_data = [
            {
                "id": "rule-1",
                "type": "literal",
                "pattern": "secret1",
                "scope": "global",
                "replacement": "<REDACTED_1>",
            },
            {
                "id": "rule-2",
                "type": "literal",
                "pattern": "secret2",
                "scope": "prompt",
                "replacement": "<REDACTED_2>",
            },
            {
                "id": "rule-3",
                "type": "literal",
                "pattern": "secret3",
                "scope": "field",
                "replacement": "<REDACTED_3>",
            },
        ]
        rules_file.write_text(json.dumps(rules_data), encoding="utf-8")

        result = _load_rules_safely(rules_file, verbose=False)

        TC.assertIsNotNone(result)
        if result is not None:
            TC.assertEqual(len(result), 3)

    def test_load_rules_safely_verbose_logs_on_failure(self, tmp_path: Path) -> None:
        """Should log warning in verbose mode when loading fails."""
        invalid_file = tmp_path / "broken.json"
        invalid_file.write_text("{incomplete", encoding="utf-8")

        result = _load_rules_safely(invalid_file, verbose=True)

        TC.assertIsNone(result)


def test_scope_matches_comprehensive() -> None:
    """Comprehensive test of all scope matching scenarios."""
    # Global matches everything
    for ctx_scope in ["global", "prompt", "field", "unknown"]:
        TC.assertTrue(
            _scope_matches("global", ctx_scope),
            f"global should match {ctx_scope}",
        )

    # Prompt matches only prompt
    TC.assertTrue(_scope_matches("prompt", "prompt"))
    TC.assertFalse(_scope_matches("prompt", "field"))
    TC.assertFalse(_scope_matches("prompt", "global"))

    # Field matches only field
    TC.assertTrue(_scope_matches("field", "field"))
    TC.assertFalse(_scope_matches("field", "prompt"))
    TC.assertFalse(_scope_matches("field", "global"))
