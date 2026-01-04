"""Plain-text export CLI with redactions applied.

Purpose: Export grouped prompts/actions with rule-based redactions applied
by default (AI-assisted by Codex GPT-5).
Author: Codex with Lauren Parlett
Date: 2025-11-27
Related tests: tests/cli/test_export_session_core.py, tests/cli/test_export_session_rendering.py
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from src.parsers.session_parser import (
    SessionDiscoveryError,
    find_first_session_file,
    group_by_user_messages,
    load_session_events,
)
from src.services.config import ConfigError, SessionsConfig, load_config
from src.services.database import get_connection_for_config
from src.services.redaction_rules import (
    DEFAULT_RULE_PATH,
    RedactionRule,
    apply_rules,
    load_rules,
    load_rules_from_db,
    sync_rules_to_db,
)
from src.services.redactions import (
    RedactionCreate,
    insert_redaction_application,
)

__all__: list[str] = ["main"]


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the export CLI."""

    parser = argparse.ArgumentParser(
        description="Export prompts and related events with redactions applied."
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Write export to the given text file (default: reports/export.txt).",
    )
    parser.add_argument(
        "--rules-file",
        type=Path,
        default=DEFAULT_RULE_PATH,
        help=f"Path to rules file (default: {DEFAULT_RULE_PATH}).",
    )
    parser.add_argument(
        "--no-redact",
        action="store_true",
        help="Skip redaction (not recommended).",
    )
    parser.add_argument(
        "--allow-db-fallback",
        action="store_true",
        help=(
            "Use stored database rules when the rules file is missing or invalid. "
            "Otherwise the export fails with guidance."
        ),
    )
    return parser


def main() -> None:
    """Entry point for the export CLI."""

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
        rules = _load_rules_with_fallback(
            rules_file,
            conn,
            allow_db_fallback=args.allow_db_fallback,
            no_redact=args.no_redact,
        )
    except Exception as exc:  # pylint: disable=broad-except
        print(f"Failed to load rules: {exc}")
        conn.close()
        return

    try:
        if args.no_redact:
            rules = []
        else:
            sync_rules_to_db(conn, rules)

        export_lines, summary = _render_export(
            config,
            rules,
            conn,
        )
        if summary:
            export_lines.append("")
            export_lines.extend(summary)

        output_path = args.output or (config.outputs.reports_dir / "export.txt")
        _write_output(output_path, export_lines)
    finally:
        try:
            conn.commit()
        finally:
            conn.close()


# pylint: disable=too-many-locals,too-many-branches
def _render_export(
    config: SessionsConfig,
    rules: list[RedactionRule],
    conn: Any,
) -> tuple[list[str], list[str]]:
    """Render the prompt log export and redaction summary."""

    try:
        session_file = find_first_session_file(config.sessions_root)
    except SessionDiscoveryError as err:
        return [f"Session discovery error: {err}"], []

    file_id = _lookup_file_id(conn, session_file)
    events = load_session_events(session_file)
    prelude, groups = group_by_user_messages(events)

    lines: list[str] = [f"Session file: {session_file}"]
    redaction_counts: Counter[str] = Counter()
    manual_counts: Counter[str] = Counter()

    if prelude:
        lines.append("-- Prelude --")
        for event in prelude:
            rendered, counts, manual = _render_event(
                event,
                rules,
                conn=conn,
                file_id=file_id,
                prompt_id=None,
                session_file_path=str(session_file),
            )
            lines.extend(rendered)
            redaction_counts.update(counts)
            manual_counts.update(manual)

    for index, group in enumerate(groups, start=1):
        user_event = group.get("user", {})
        prompt_text = ""
        if isinstance(user_event, dict):
            payload = user_event.get("payload") or {}
            if isinstance(payload, dict):
                prompt_text = payload.get("message", "") or ""

        # Look up the prompt_id for this group (1-indexed in export, 1-indexed in DB)
        prompt_id_for_group = _lookup_prompt_id(conn, file_id, index)

        redacted_prompt, prompt_counts, prompt_manual = _apply_all_redactions(
            prompt_text,
            rules,
            conn,
            file_id=file_id,
            prompt_id=prompt_id_for_group,
            session_file_path=str(session_file),
            scope="prompt",
            field_path="prompt.message",
        )
        redaction_counts.update(prompt_counts)
        manual_counts.update(prompt_manual)

        timestamp = user_event.get("timestamp", "?")
        lines.append(f"\n== Prompt {index} @ {timestamp} ==")
        lines.append(_indent(redacted_prompt or "<empty prompt>", "  "))

        events_list = group.get("events", [])
        if not events_list:
            lines.append("  (No subsequent events recorded.)")
            continue

        lines.append("  -- Following events --")
        for event in events_list:
            rendered, counts, manual = _render_event(
                event,
                rules,
                conn=conn,
                file_id=file_id,
                prompt_id=prompt_id_for_group,
                session_file_path=str(session_file),
            )
            redaction_counts.update(counts)
            manual_counts.update(manual)
            lines.extend([_indent(line, "  ") for line in rendered])

    summary_lines: list[str] = []
    if redaction_counts or manual_counts:
        summary_lines.append("-- Redaction summary --")
        if redaction_counts:
            summary_lines.append("rules:")
            for rule_id, count in sorted(redaction_counts.items()):
                summary_lines.append(f"  {rule_id}: {count}")
        if manual_counts:
            summary_lines.append("manual:")
            for ref, count in sorted(manual_counts.items()):
                summary_lines.append(f"  {ref}: {count}")
    return lines, summary_lines


# pylint: disable=too-many-locals,too-many-branches,too-many-statements
def _render_event(
    event: dict[str, Any],
    rules: list[RedactionRule],
    *,
    conn: Any,
    file_id: int | None,
    prompt_id: int | None,
    session_file_path: str,
) -> tuple[list[str], Counter[str], Counter[str]]:
    # pylint: disable=too-many-arguments
    # Justification: Needs event data, rules, connection, file/prompt context IDs,
    # and session path to apply redactions and track applications per field.
    """Render an individual event applying redactions."""

    summary_lines: list[str] = []
    rule_counts: Counter[str] = Counter()
    manual_counts: Counter[str] = Counter()

    event_type = event.get("type", "<unknown>")
    timestamp = event.get("timestamp", "?")
    payload = event.get("payload") if isinstance(event, dict) else None
    payload_type = payload.get("type") if isinstance(payload, dict) else None

    header = f"{event_type}"
    if payload_type:
        header += f" ({payload_type})"
    header += f" @ {timestamp}"
    summary_lines.append(header)

    if not isinstance(payload, dict):
        return summary_lines, rule_counts, manual_counts

    def _apply(text: str, field_path: str) -> str:
        redacted_text, counts, manuals = _apply_all_redactions(
            text,
            rules,
            conn,
            file_id=file_id,
            prompt_id=prompt_id,
            session_file_path=session_file_path,
            scope="field",
            field_path=field_path,
        )
        rule_counts.update(counts)
        manual_counts.update(manuals)
        return redacted_text

    if event_type == "event_msg":
        if payload_type == "agent_reasoning":
            text = payload.get("text")
            if isinstance(text, str) and text.strip():
                summary_lines.append(_indent("reasoning:", "  "))
                summary_lines.append(
                    _indent(_apply(text, "agent.reasoning.text"), "    ")
                )
        elif payload_type == "agent_message":
            message = payload.get("message")
            if isinstance(message, str) and message.strip():
                summary_lines.append(_indent(_apply(message, "agent.message"), "  "))

    elif event_type == "response_item":
        if payload_type == "message":
            content = payload.get("content")
            if isinstance(content, list):
                texts = [
                    str(item.get("text"))
                    for item in content
                    if isinstance(item, dict) and isinstance(item.get("text"), str)
                ]
                if texts:
                    summary_lines.append(_indent("message:", "  "))
                    summary_lines.append(
                        _indent(
                            _apply(" ".join(texts), "response.message"),
                            "    ",
                        )
                    )
        elif payload_type == "function_call":
            name = payload.get("name")
            if name:
                summary_lines.append(_indent(f"function: {name}", "  "))
            arguments = payload.get("arguments")
            if isinstance(arguments, str) and arguments.strip():
                summary_lines.append(_indent("args:", "  "))
                summary_lines.append(
                    _indent(_apply(arguments, "function_call.arguments"), "    ")
                )
        elif payload_type == "function_call_output":
            output = payload.get("output")
            if isinstance(output, str):
                summary_lines.append(_indent("output:", "  "))
                summary_lines.append(
                    _indent(_apply(output, "function_call.output"), "    ")
                )
    elif event_type == "turn_context":
        cwd = payload.get("cwd")
        if isinstance(cwd, str):
            redacted_cwd = _apply(cwd, "turn_context.cwd")
            summary_lines.append(_indent(f"cwd: {redacted_cwd}", "  "))

    return summary_lines, rule_counts, manual_counts


def _apply_all_redactions(
    text: str,
    rules: list[RedactionRule],
    conn: Any,
    *,
    file_id: int | None,
    prompt_id: int | None,
    session_file_path: str,
    scope: str,
    field_path: str,
) -> tuple[str, Counter[str], Counter[str]]:
    # pylint: disable=too-many-arguments
    # Justification: Needs text to redact, rules list, DB connection, file/prompt
    # context IDs, session path, scope, and field path for audit trail recording.
    """Apply rule-based and manual redactions with precedence."""

    rule_counts: Counter[str] = Counter()
    manual_counts: Counter[str] = Counter()
    result = text

    scoped_rules = [rule for rule in rules if _scope_matches(rule.scope, scope)]
    if scoped_rules:
        result, summary = apply_rules(result, scoped_rules)
        for rule in scoped_rules:
            if rule.id in summary:
                _record_rule_application(
                    conn=conn,
                    rule=rule,
                    file_id=file_id,
                    prompt_id=prompt_id,
                    field_path=field_path,
                    replacement_text=rule.effective_replacement,
                    session_file_path=session_file_path,
                )
        rule_counts.update({rid: data["count"] for rid, data in summary.items()})

    return result, rule_counts, manual_counts


def _scope_matches(rule_scope: str, context_scope: str) -> bool:
    """Return True when a rule scope applies to the current context."""

    if rule_scope == "global":
        return True
    if rule_scope == "interaction" and context_scope == "interaction":
        return True
    if rule_scope == "field" and context_scope == "field":
        return True
    return False


def _record_rule_application(
    *,
    conn: Any,
    rule: RedactionRule,
    file_id: int | None,
    prompt_id: int | None,
    field_path: str,
    replacement_text: str,  # pylint: disable=unused-argument
    session_file_path: str,
) -> None:
    # pylint: disable=too-many-arguments
    # Justification: Needs connection, rule metadata, file/prompt IDs, field path,
    # replacement text, and session path for comprehensive audit trail recording.
    """Persist a rule application using the append-only table with upsert."""

    normalized_field_path = field_path
    if rule.scope == "global":
        normalized_field_path = "*"

    payload = RedactionCreate(
        file_id=file_id,
        prompt_id=prompt_id,
        rule_id=rule.id,
        rule_fingerprint=rule.fingerprint,
        field_path=normalized_field_path,
        reason=rule.reason,
        actor=rule.actor,
        session_file_path=session_file_path,
        applied_at=None,
    )
    insert_redaction_application(conn, payload)


def _lookup_file_id(conn: Any, session_file: Path) -> int | None:
    """Return file id for the session file path, if present."""

    placeholder = "?" if conn.__class__.__module__.startswith("sqlite3") else "%s"
    cursor = conn.cursor()
    cursor.execute(
        f"SELECT id FROM files WHERE path = {placeholder}",  # nosec B608
        (str(session_file),),
    )
    row = cursor.fetchone()
    cursor.close()
    if row and row[0] is not None:
        return int(row[0])
    return None


def _lookup_prompt_id(conn: Any, file_id: int | None, prompt_index: int) -> int | None:
    """Return prompt id for the given file and prompt index, if present."""

    if file_id is None:
        return None
    placeholder = "?" if conn.__class__.__module__.startswith("sqlite3") else "%s"
    cursor = conn.cursor()
    cursor.execute(
        f"SELECT id FROM prompts WHERE file_id = {placeholder} "
        f"AND prompt_index = {placeholder}",  # nosec B608
        (file_id, prompt_index),
    )
    row = cursor.fetchone()
    cursor.close()
    if row and row[0] is not None:
        return int(row[0])
    return None


def _load_rules_with_fallback(
    rules_file: Path,
    conn: Any,
    *,
    allow_db_fallback: bool,
    no_redact: bool,
) -> list[RedactionRule]:
    """Load rules from file, optionally falling back to DB-stored rules."""

    if no_redact:
        return []

    try:
        rules = load_rules(rules_file)
        return rules
    except Exception as exc:  # pylint: disable=broad-except
        stored_rules = load_rules_from_db(conn)
        if stored_rules and allow_db_fallback:
            print(
                "Rules file missing or invalid; using rules stored in the database. "
                f"Details: {exc}"
            )
            return stored_rules
        print(
            f"Failed to load rules file ({exc}). "
            "Provide a valid rules file or pass --no-redact to proceed."
        )
        raise


def _indent(text: str, prefix: str) -> str:
    """Indent helper for readability."""

    return prefix + text


def _write_output(output_path: Path, lines: Iterable[str]) -> None:
    """Write the export to disk and echo the path."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    normalized = "\n".join(lines)
    output_path.write_text(normalized + "\n", encoding="utf-8")
    print(f"Export written to {output_path}")


if __name__ == "__main__":
    main()
