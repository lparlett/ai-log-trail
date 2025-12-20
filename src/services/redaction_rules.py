"""Rule-based redaction loader and applier.

Purpose: Load YAML/JSON redaction rules and apply them with deterministic
precedence (AI-assisted by Codex GPT-5).
Author: Codex with Lauren Parlett
Date: 2025-11-27
Related tests: tests/test_redaction_rules.py
"""

from __future__ import annotations

import importlib
import json
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence, TypedDict, cast

# Global defaults for redaction rules
DEFAULT_REPLACEMENT = "<REDACTED>"
DEFAULT_RULE_PATH = Path("user/redactions.yml")

# Allowed values for rule configuration
ALLOWED_TYPES = ("regex", "marker", "literal")
ALLOWED_SCOPES = ("prompt", "field", "global")

# SQL module and regex configuration
SQLITE_MODULE_NAME = "sqlite3"
REGEX_FLAGS_CONFIG = {"IGNORECASE": re.IGNORECASE, "DOTALL": re.DOTALL}


class RuleSummary(TypedDict):
    """Structured summary for a single rule application."""

    count: int


@dataclass(frozen=True)
class PayloadExtractionResult:
    """Result of extracting payload data from a raw event."""

    payload: dict[str, Any]
    success: bool = True
    error_message: str | None = None


@dataclass(frozen=True)
class RuleOptions:
    """Optional attributes for a rule."""

    scope: str = "prompt"
    replacement: str | None = None
    enabled: bool = True
    reason: str | None = None
    actor: str | None = None
    ignore_case: bool = True
    dotall: bool = False


@dataclass(frozen=True)
class RedactionRule:
    """Normalized redaction rule."""

    id: str
    type: str
    pattern: str
    options: RuleOptions = field(default_factory=RuleOptions)
    _compiled: re.Pattern[str] | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _fingerprint: str | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        _validate_rule(self)
        flags = 0
        if self.ignore_case:
            flags |= re.IGNORECASE
        if self.dotall:
            flags |= re.DOTALL
        pattern_text = self.pattern
        if self.type == "literal":
            pattern_text = re.escape(self.pattern)
        compiled = re.compile(pattern_text, flags=flags)
        object.__setattr__(self, "_compiled", compiled)

    @property
    def compiled(self) -> re.Pattern[str]:
        """Return the compiled regex pattern."""

        if self._compiled is None:
            raise RuntimeError("Rule was not compiled.")
        return self._compiled

    @property
    def effective_replacement(self) -> str:
        """Replacement text or the global default."""

        return self.replacement or DEFAULT_REPLACEMENT

    @property
    def scope(self) -> str:
        """Return the rule scope."""
        return self.options.scope

    @property
    def replacement(self) -> str | None:
        """Return the configured replacement text."""
        return self.options.replacement

    @property
    def enabled(self) -> bool:
        """Return True when the rule is enabled."""
        return self.options.enabled

    @property
    def reason(self) -> str | None:
        """Return the provenance reason, if any."""
        return self.options.reason

    @property
    def actor(self) -> str | None:
        """Return the actor metadata, if any."""
        return self.options.actor

    @property
    def ignore_case(self) -> bool:
        """Return True when the regex is case-insensitive."""
        return self.options.ignore_case

    @property
    def dotall(self) -> bool:
        """Return True when the regex dot matches newlines."""
        return self.options.dotall

    @property
    def fingerprint(self) -> str:
        """Stable fingerprint for deduplication of rule applications."""

        if self._fingerprint is None:
            payload = {
                "id": self.id,
                "type": self.type,
                "pattern": self.pattern,
                "scope": self.scope,
                "replacement": self.replacement,
                "ignore_case": self.ignore_case,
                "dotall": self.dotall,
            }
            serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
            object.__setattr__(self, "_fingerprint", digest)
        return cast(str, self._fingerprint)


def load_rules(path: Path | str) -> list[RedactionRule]:
    """Load rules from a YAML or JSON file.

    Args:
        path: File path to a YAML or JSON rules document.

    Raises:
        ValueError: When the file is missing, malformed, or contains duplicates.
        SystemExit: When YAML is requested but PyYAML is not installed.
    """

    rules_path = Path(path)
    if not rules_path.exists():
        raise ValueError(f"Rules file not found: {rules_path}")

    raw_rules = _load_raw(rules_path)
    rules = [_parse_rule(entry, source=str(rules_path)) for entry in raw_rules]
    _enforce_unique_ids(rules, source=str(rules_path))
    return rules


def _update_rule_summary(
    summary: dict[str, RuleSummary], rule_id: str, count: int
) -> None:
    """Update summary with rule application count if non-zero."""
    if count:
        summary[rule_id] = {"count": count}


def apply_rules(
    text: str, rules: Sequence[RedactionRule]
) -> tuple[str, dict[str, RuleSummary]]:
    """Apply rules in order and return the redacted text and per-rule counts.

    Manual database redactions should be applied *after* this function so they
    override file-based rules.
    """

    result = text
    summary: dict[str, RuleSummary] = {}

    for rule in rules:
        if not rule.enabled:
            continue

        if rule.type in {"regex", "literal"}:
            result, count = _apply_regex_rule(result, rule)
        else:
            result, count = _apply_marker_rule(result, rule)

        _update_rule_summary(summary, rule.id, count)

    return result, summary


# pylint: disable=too-many-locals
def load_rules_from_db(
    conn: Any, *, include_disabled: bool = False
) -> list[RedactionRule]:
    """Load rules from the database (sqlite or Postgres)."""

    query = """
        SELECT id, type, pattern, scope, replacement_text, rule_fingerprint, enabled, reason, actor
        FROM redaction_rules
        WHERE (? = 1 OR enabled = 1)
        ORDER BY id
    """
    cursor = _execute(conn, query, (1 if include_disabled else 0,))
    rows = cursor.fetchall()
    rules: list[RedactionRule] = []
    for row in rows:
        (
            rule_id,
            rule_type,
            pattern,
            scope,
            replacement_text,
            rule_fingerprint,
            enabled,
            reason,
            actor,
        ) = row
        options = RuleOptions(
            scope=str(scope),
            replacement=str(replacement_text),
            enabled=bool(enabled),
            reason=_optional_str(reason),
            actor=_optional_str(actor),
        )
        rules.append(
            RedactionRule(
                id=str(rule_id),
                type=str(rule_type),
                pattern=str(pattern),
                options=options,
            )
        )
        if rules[-1]._fingerprint is None:  # pylint: disable=protected-access
            object.__setattr__(rules[-1], "_fingerprint", str(rule_fingerprint))
    return rules


def sync_rules_to_db(conn: Any, rules: Sequence[RedactionRule]) -> None:
    """Upsert rules into the database and soft-disable missing ones."""

    active_ids: set[str] = set()
    for rule in rules:
        active_ids.add(rule.id)
        updated = _execute(
            conn,
            """
            UPDATE redaction_rules
            SET type = ?, pattern = ?, scope = ?, replacement_text = ?,
                rule_fingerprint = ?, enabled = ?, reason = ?, actor = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                rule.type,
                rule.pattern,
                rule.scope,
                rule.effective_replacement,
                rule.fingerprint,
                1 if rule.enabled else 0,
                rule.reason,
                rule.actor,
                rule.id,
            ),
        )
        if updated.rowcount == 0:
            _execute(
                conn,
                """
                INSERT INTO redaction_rules (
                    id, type, pattern, scope, replacement_text,
                    rule_fingerprint, enabled, reason, actor
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule.id,
                    rule.type,
                    rule.pattern,
                    rule.scope,
                    rule.effective_replacement,
                    rule.fingerprint,
                    1 if rule.enabled else 0,
                    rule.reason,
                    rule.actor,
                ),
            )
        _execute(
            conn,
            """
            UPDATE redactions
            SET active = 0, updated_at = CURRENT_TIMESTAMP
            WHERE rule_id = ? AND rule_fingerprint != ?
            """,
            (rule.id, rule.fingerprint),
        )
        _execute(
            conn,
            """
            UPDATE redactions
            SET active = 1, updated_at = CURRENT_TIMESTAMP
            WHERE rule_id = ?
            """,
            (rule.id,),
        )

    _soft_disable_missing_rules(conn, active_ids)
    _soft_disable_redactions_for_disabled_rules(conn)


def write_rules(path: Path, rules: Sequence[RedactionRule]) -> None:
    """Persist rules to YAML/JSON based on the file extension."""

    serializable = [rule_to_dict(rule) for rule in rules]
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in {".yml", ".yaml"}:
        try:
            yaml = importlib.import_module("yaml")
        except ModuleNotFoundError as exc:  # pragma: no cover - env dependent
            raise SystemExit(
                "PyYAML is required to write YAML rule files. Install with "
                "'pip install pyyaml'."
            ) from exc
        path.write_text(yaml.safe_dump(serializable, sort_keys=False), encoding="utf-8")
    else:
        path.write_text(json.dumps(serializable, indent=2), encoding="utf-8")


def rule_to_dict(rule: RedactionRule) -> dict[str, Any]:
    """Serialize a rule to a JSON/YAML friendly dict."""

    return {
        "id": rule.id,
        "type": rule.type,
        "pattern": rule.pattern,
        "scope": rule.scope,
        "replacement": rule.replacement,
        "enabled": rule.enabled,
        "reason": rule.reason,
        "actor": rule.actor,
        "ignore_case": rule.ignore_case,
        "dotall": rule.dotall,
    }


def _apply_regex_rule(text: str, rule: RedactionRule) -> tuple[str, int]:
    count = 0

    def _repl(_match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return rule.effective_replacement

    redacted = rule.compiled.sub(_repl, text)
    return redacted, count


def _apply_marker_rule(text: str, rule: RedactionRule) -> tuple[str, int]:
    count = 0

    def _repl(_match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return rule.effective_replacement

    redacted = rule.compiled.sub(_repl, text)
    return redacted, count


def _soft_disable_missing_rules(conn: Any, active_ids: set[str]) -> None:
    """Soft-disable rules missing from the latest file sync."""

    if not active_ids:
        _execute(
            conn,
            """
            UPDATE redaction_rules
            SET enabled = 0, updated_at = CURRENT_TIMESTAMP
            """,
        )
        return

    placeholders = ",".join(["?"] * len(active_ids))
    query = f"""
        UPDATE redaction_rules
        SET enabled = 0, updated_at = CURRENT_TIMESTAMP
        WHERE id NOT IN ({placeholders})
    """  # nosec B608
    _execute(conn, query, tuple(active_ids))


def _soft_disable_redactions_for_disabled_rules(conn: Any) -> None:
    """Mark redaction rows inactive when their rule is disabled."""

    _execute(
        conn,
        """
        UPDATE redactions
        SET active = 0, updated_at = CURRENT_TIMESTAMP
        WHERE rule_id IN (
            SELECT id FROM redaction_rules WHERE enabled = 0
        )
    """,
    )


def _execute(conn: Any, query: str, params: Iterable[Any] | None = None) -> Any:
    """Execute a query with placeholder adaptation for sqlite and psycopg2."""

    params = tuple(params or ())
    prepared = _prepare_query(conn, query)
    cursor = conn.cursor()
    cursor.execute(prepared, params)
    return cursor


def _prepare_query(conn: Any, query: str) -> str:
    """Convert sqlite-style ? placeholders to %s when needed."""

    module_name = conn.__class__.__module__
    if module_name.startswith(SQLITE_MODULE_NAME):
        return query
    return query.replace("?", "%s")


def _load_raw(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() in {".yml", ".yaml"}:
        try:
            yaml = importlib.import_module("yaml")
        except ModuleNotFoundError as exc:  # pragma: no cover - exercised in env
            raise SystemExit(
                "PyYAML is required to load YAML rule files. Install with "
                "'pip install pyyaml'."
            ) from exc
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    else:
        parsed = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(parsed, list):
        raise ValueError(f"Rules file must contain a list, got {type(parsed)}")
    return [dict(item) for item in parsed]


def _parse_rule(entry: dict[str, Any], *, source: str) -> RedactionRule:
    required = ("id", "type", "pattern")
    for key in required:
        if key not in entry:
            raise ValueError(f"Missing required key '{key}' in {source}")

    options = RuleOptions(
        scope=str(entry.get("scope", "prompt")),
        replacement=entry.get("replacement"),
        enabled=bool(entry.get("enabled", True)),
        reason=_optional_str(entry.get("reason")),
        actor=_optional_str(entry.get("actor")),
        ignore_case=bool(entry.get("ignore_case", True)),
        dotall=bool(entry.get("dotall", False)),
    )
    return RedactionRule(
        id=str(entry["id"]),
        type=str(entry["type"]).lower(),
        pattern=str(entry["pattern"]),
        options=options,
    )


def _validate_rule(rule: RedactionRule) -> None:
    if rule.type not in ALLOWED_TYPES:
        raise ValueError(f"Invalid rule type '{rule.type}'. Allowed: {ALLOWED_TYPES}")
    if not rule.pattern.strip():
        raise ValueError("Rule pattern must be non-empty.")
    if rule.scope not in ALLOWED_SCOPES:
        raise ValueError(f"Invalid scope '{rule.scope}'. Allowed: {ALLOWED_SCOPES}")


def _enforce_unique_ids(rules: Iterable[RedactionRule], *, source: str) -> None:
    seen: set[str] = set()
    for rule in rules:
        if rule.id in seen:
            raise ValueError(f"Duplicate rule id '{rule.id}' in {source}")
        seen.add(rule.id)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
