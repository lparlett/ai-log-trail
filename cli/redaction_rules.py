"""Redaction rules CLI for listing, adding, and removing rules.

Purpose: Manage rule-based redactions stored in user/redactions.yml and keep the
database in sync (AI-assisted by Codex GPT-5).
Author: Codex with Lauren Parlett
Date: 2025-11-27
Related tests: tests/cli/test_redaction_rules_cli.py
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Sequence

from src.services.config import ConfigError, load_config
from src.services.database import get_connection_for_config
from src.services.redaction_rules import (
    DEFAULT_RULE_PATH,
    RedactionRule,
    RuleOptions,
    load_rules,
    load_rules_from_db,
    sync_rules_to_db,
    write_rules,
)

__all__: list[str] = ["main"]


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level parser."""

    parser = argparse.ArgumentParser(
        description="Manage rule-based redactions and sync them to the database."
    )
    parser.add_argument(
        "--rules-file",
        type=Path,
        default=DEFAULT_RULE_PATH,
        help=f"Path to the rules file (default: {DEFAULT_RULE_PATH}).",
    )
    parser.add_argument(
        "--allow-db-fallback",
        action="store_true",
        help=(
            "Use stored database rules when the rules file is missing or invalid. "
            "Otherwise the command fails."
        ),
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List rules as JSON lines.")
    list_parser.add_argument(
        "--include-disabled",
        action="store_true",
        help="Include disabled rules when listing.",
    )

    add_parser = subparsers.add_parser("add", help="Add a rule to the rules file.")
    add_parser.add_argument("--id", required=True, help="Unique rule id.")
    add_parser.add_argument(
        "--type",
        required=True,
        choices=["regex", "marker", "literal"],
        help="Rule matching type.",
    )
    add_parser.add_argument("--pattern", required=True, help="Pattern for the rule.")
    add_parser.add_argument(
        "--replacement",
        default=None,
        help="Replacement text (defaults to <REDACTED>).",
    )
    add_parser.add_argument(
        "--scope",
        choices=["interaction", "field", "global"],
        default="interaction",
        help="Scope that governs where the rule applies.",
    )
    add_parser.add_argument(
        "--reason",
        default=None,
        help="Reason for provenance (optional).",
    )
    add_parser.add_argument(
        "--actor",
        default=None,
        help="Actor applying the rule (optional).",
    )
    add_parser.add_argument(
        "--disable",
        action="store_true",
        help="Create the rule in a disabled state.",
    )
    add_parser.add_argument(
        "--case-sensitive",
        action="store_true",
        help="Treat the pattern as case-sensitive (default is ignore case).",
    )
    add_parser.add_argument(
        "--dotall",
        action="store_true",
        help="Enable DOTALL ('.' matches newlines).",
    )

    remove_parser = subparsers.add_parser(
        "remove", help="Remove a rule from the rules file."
    )
    remove_parser.add_argument("--id", required=True, help="Rule id to remove.")

    return parser


def main() -> None:
    """Entry point for the redaction rules CLI."""

    args = build_parser().parse_args()

    try:
        config = load_config()
    except ConfigError as err:
        print(f"Configuration error: {err}")
        return

    rules_file: Path = args.rules_file

    try:
        conn = get_connection_for_config(config.database)
    except Exception as exc:  # pylint: disable=broad-except
        print(f"Database error: {exc}")
        return

    try:
        if args.command == "list":
            rules = _load_rules_with_fallback(
                rules_file,
                conn,
                allow_db_fallback=args.allow_db_fallback,
                include_disabled=args.include_disabled,
            )
            _emit_rules(rules)
            return

        if args.command == "add":
            _handle_add(args, rules_file, conn)
            return

        if args.command == "remove":
            _handle_remove(args.id, rules_file, conn, args.allow_db_fallback)
            return
    except Exception as exc:  # pylint: disable=broad-except
        print(f"Error: {exc}")
    finally:
        try:
            conn.commit()
        finally:
            conn.close()


def _handle_add(args: argparse.Namespace, rules_file: Path, conn: Any) -> None:
    """Add a rule and sync to the database."""

    rules = _load_rules_with_fallback(
        rules_file, conn, allow_db_fallback=True, include_disabled=True
    )
    if any(rule.id == args.id for rule in rules):
        print(f"Rule id '{args.id}' already exists; aborting.")
        return

    options = RuleOptions(
        scope=args.scope,
        replacement=args.replacement,
        enabled=not args.disable,
        reason=args.reason,
        actor=args.actor,
        ignore_case=not args.case_sensitive,
        dotall=args.dotall,
    )
    rules.append(
        RedactionRule(
            id=args.id,
            type=args.type,
            pattern=args.pattern,
            options=options,
        )
    )
    write_rules(rules_file, rules)
    sync_rules_to_db(conn, rules)
    print(f"Added rule '{args.id}' and synced to database.")


def _handle_remove(
    rule_id: str, rules_file: Path, conn: Any, allow_db_fallback: bool
) -> None:
    """Remove a rule and sync database state."""

    rules = _load_rules_with_fallback(
        rules_file, conn, allow_db_fallback=allow_db_fallback, include_disabled=True
    )
    remaining = [rule for rule in rules if rule.id != rule_id]
    if len(remaining) == len(rules):
        print(f"Rule '{rule_id}' not found; no changes made.")
        return

    write_rules(rules_file, remaining)
    sync_rules_to_db(conn, remaining)
    print(f"Removed rule '{rule_id}' and synced to database.")


def _emit_rules(rules: Sequence[RedactionRule]) -> None:
    """Emit rules in a human-friendly format."""

    if not rules:
        print("No rules found.")
        return

    print(f"\nFound {len(rules)} rule(s):\n")

    for idx, rule in enumerate(rules, 1):
        status = "✓ ENABLED" if rule.enabled else "✗ DISABLED"
        print(f"{idx}. [{status}] {rule.id}")
        print(f"   Type:        {rule.type}")
        print(
            f"   Pattern:     {rule.pattern[:60]}{'...' if len(rule.pattern) > 60 else ''}"
        )
        print(f"   Scope:       {rule.scope}")
        print(f"   Replacement: {rule.effective_replacement}")

        if rule.reason:
            print(f"   Reason:      {rule.reason}")
        if rule.actor:
            print(f"   Actor:       {rule.actor}")

        options = []
        if rule.ignore_case:
            options.append("ignore-case")
        if rule.dotall:
            options.append("dotall")
        if options:
            print(f"   Options:     {', '.join(options)}")

        print()


def _load_rules_with_fallback(
    rules_file: Path,
    conn: Any,
    *,
    allow_db_fallback: bool,
    include_disabled: bool,
) -> list[RedactionRule]:
    """Load rules from file or (optionally) fall back to DB."""

    try:
        rules = load_rules(rules_file)
        sync_rules_to_db(conn, rules)
        return rules
    except Exception as exc:  # pylint: disable=broad-except
        db_rules = load_rules_from_db(conn, include_disabled=include_disabled)
        if allow_db_fallback:
            print(
                "Rules file missing or invalid; using rules stored in the database. "
                f"Details: {exc}"
            )
            return db_rules
        raise


if __name__ == "__main__":
    main()
