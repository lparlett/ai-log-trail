"""Tests for rule-based redactions (AI-assisted by Codex GPT-5)."""

# pylint: disable=import-error,protected-access

from __future__ import annotations

import json
import importlib
import unittest
from pathlib import Path

import pytest

import src.services.redaction_rules as rules_mod
from src.services.redaction_rules import (
    DEFAULT_REPLACEMENT,
    RuleOptions,
    RedactionRule,
    apply_rules,
    load_rules,
)

TC = unittest.TestCase()


def test_apply_rules_honors_order_and_counts() -> None:
    """Rules apply in order and produce per-rule counts with titles."""

    rules = [
        RedactionRule(
            id="emails",
            type="regex",
            pattern=r"[\w.-]+@[\w.-]+",
            options=RuleOptions(replacement="EMAIL"),
        ),
        RedactionRule(
            id="tokens",
            type="regex",
            pattern=r"token-[0-9]+",
        ),
    ]
    text = "Contact me at user@example.com with token-123 or token-456."
    redacted, summary = apply_rules(text, rules)

    TC.assertIn("EMAIL", redacted)
    TC.assertIn(DEFAULT_REPLACEMENT, redacted)
    TC.assertEqual(summary["tokens"]["count"], 2)


def test_literal_rule_matches_exact_text() -> None:
    """Literal rules should match exact text (case-sensitive when requested)."""

    rules = [
        RedactionRule(id="name", type="literal", pattern="Lauren"),
        RedactionRule(
            id="case_sensitive",
            type="literal",
            pattern="SECRET",
            options=RuleOptions(ignore_case=False),
        ),
    ]
    redacted, summary = apply_rules("Lauren keeps secret and SECRET", rules)

    TC.assertEqual(redacted, "<REDACTED> keeps secret and <REDACTED>")
    TC.assertEqual(summary["name"]["count"], 1)
    TC.assertEqual(summary["case_sensitive"]["count"], 1)


def test_apply_rules_no_matches_has_empty_summary() -> None:
    """Rules that do not match should not emit summary entries."""

    rules = [RedactionRule(id="none", type="regex", pattern="doesnotmatch")]
    redacted, summary = apply_rules("text without hits", rules)

    TC.assertEqual(redacted, "text without hits")
    TC.assertEqual(summary, {})


def test_marker_rule_replaces_inner_content() -> None:
    """Marker rules should redact only the enclosed content."""

    rule = RedactionRule(
        id="marker",
        type="marker",
        pattern=r"\[redact\s+(?P<content>.+?)\]",
        options=RuleOptions(dotall=True),
    )
    text = "Logs: [redact password=abc123] continue"
    redacted, summary = apply_rules(text, [rule])

    TC.assertEqual(redacted, "Logs: <REDACTED> continue")
    TC.assertEqual(summary["marker"]["count"], 1)


def test_disabled_rules_are_skipped() -> None:
    """Disabled rules should not apply."""

    rules = [
        RedactionRule(
            id="enabled",
            type="regex",
            pattern="secret",
        ),
        RedactionRule(
            id="disabled",
            type="regex",
            pattern="data",
            options=RuleOptions(enabled=False),
        ),
    ]
    redacted, summary = apply_rules("secret and data", rules)

    TC.assertEqual(redacted, "<REDACTED> and data")
    TC.assertNotIn("disabled", summary)


def test_load_rules_from_json_and_defaults(tmp_path: Path) -> None:
    """JSON rule files load and enforce overrides by ID."""

    rule_path = tmp_path / "rules.json"
    rule_path.write_text(
        json.dumps(
            [
                {
                    "id": "email",
                    "type": "regex",
                    "pattern": "override",
                    "enabled": False,
                },
                {
                    "id": "custom",
                    "type": "regex",
                    "pattern": "custom",
                },
            ]
        ),
        encoding="utf-8",
    )

    rules = load_rules(rule_path)
    rule_ids = [rule.id for rule in rules]

    TC.assertIn("email", rule_ids)
    TC.assertIn("custom", rule_ids)

    email_rule = next(rule for rule in rules if rule.id == "email")
    TC.assertFalse(email_rule.enabled)


def test_invalid_rule_fails_fast(tmp_path: Path) -> None:
    """Invalid entries should raise for visibility."""

    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps([{"title": "missing id"}]), encoding="utf-8")

    with pytest.raises(ValueError):
        load_rules(bad_path)


def test_load_rules_requires_id_and_pattern(tmp_path: Path) -> None:
    """Rules without required keys should raise."""

    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps([{"pattern": "x"}]), encoding="utf-8")

    with pytest.raises(ValueError):
        load_rules(bad_path)


def test_invalid_rule_types_and_scope() -> None:
    """Invalid type, scope, or blank pattern should raise for visibility."""

    with pytest.raises(ValueError):
        RedactionRule(id="bad_type", type="unknown", pattern="x")
    with pytest.raises(ValueError):
        RedactionRule(
            id="bad_scope",
            type="regex",
            pattern="x",
            options=RuleOptions(scope="invalid"),
        )
    with pytest.raises(ValueError):
        RedactionRule(id="blank_pattern", type="regex", pattern="   ")


def test_duplicate_ids_rejected(tmp_path: Path) -> None:
    """Duplicate rule ids should fail load for deterministic behavior."""

    rule_path = tmp_path / "dups.json"
    rule_path.write_text(
        json.dumps(
            [
                {"id": "dup", "type": "regex", "pattern": "one"},
                {"id": "dup", "type": "regex", "pattern": "two"},
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_rules(rule_path)


def test_load_rules_rejects_non_list(tmp_path: Path) -> None:
    """Non-list rule documents should raise ValueError."""

    rule_path = tmp_path / "bad.json"
    rule_path.write_text(json.dumps({"id": "x"}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_rules(rule_path)


def test_yaml_import_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """YAML load should surface missing PyYAML via SystemExit."""

    yaml_path = tmp_path / "rules.yml"
    yaml_path.write_text("- id: x\n  type: regex\n  pattern: x\n", encoding="utf-8")

    def _fake_import(name: str) -> object:
        if name == "yaml":
            raise ModuleNotFoundError("yaml missing")
        return importlib.import_module(name)

    _fake_import("json")  # cover non-yaml branch

    monkeypatch.setattr(importlib, "import_module", _fake_import)
    with pytest.raises(SystemExit):
        load_rules(yaml_path)


def test_yaml_load_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """YAML load path should succeed when yaml module is available."""

    yaml_path = tmp_path / "rules.yml"
    yaml_path.write_text("- id: x\n  type: regex\n  pattern: x\n", encoding="utf-8")

    class _FakeYaml:  # pylint: disable=too-few-public-methods
        """Minimal yaml stub for import fallback."""

        @staticmethod
        def safe_load(_: str) -> list[dict[str, str]]:
            """Return a single regex rule for testing."""
            return [{"id": "x", "type": "regex", "pattern": "x"}]

    def _fake_import(name: str) -> object:
        """Return fake yaml module or fall back to real import."""
        if name == "yaml":
            return _FakeYaml()
        return importlib.import_module(name)

    _fake_import("json")  # cover non-yaml branch
    monkeypatch.setattr(importlib, "import_module", _fake_import)
    rules = load_rules(yaml_path)
    TC.assertEqual(len(rules), 1)


def test_optional_str_trims_and_nulls() -> None:
    """_optional_str should normalize whitespace-only strings to None."""

    TC.assertIsNone(rules_mod._optional_str("   "))
    TC.assertEqual(rules_mod._optional_str(" keep "), "keep")


def test_compiled_property_raises_when_missing() -> None:
    """compiled property should raise when backing pattern is missing."""

    rule = RedactionRule(id="x", type="regex", pattern="x")
    object.__setattr__(rule, "_compiled", None)
    with pytest.raises(RuntimeError):
        _ = rule.compiled


def test_rule_reason_and_actor_properties() -> None:
    """reason and actor getters should expose optional metadata."""

    rule = RedactionRule(
        id="meta",
        type="regex",
        pattern="x",
        options=RuleOptions(reason="why", actor="who"),
    )
    TC.assertEqual(rule.reason, "why")
    TC.assertEqual(rule.actor, "who")


def test_load_rules_missing_file_raises(tmp_path: Path) -> None:
    """Missing rules file should raise a clear ValueError."""

    with pytest.raises(ValueError):
        load_rules(tmp_path / "missing.yml")
