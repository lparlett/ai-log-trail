"""Simple CLI to group AI agent session events by user prompts.

Purpose: Provide human-readable grouping of session logs for quick review.
Author: Codex with Lauren Parlett
Date: 2025-10-30
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from textwrap import indent
from typing import Any

from src.parsers.session_parser import (
    SessionDiscoveryError,
    find_first_session_file,
    group_by_user_messages,
    load_session_events,
)
from src.services.config import ConfigError, SessionsConfig, load_config

__all__: list[str] = ["SessionDiscoveryError", "main"]


def shorten(text: str, limit: int = 120) -> str:
    """Return text truncated to ``limit`` characters with ellipsis."""

    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def describe_event(event: dict[str, Any]) -> str:
    """Build a concise description for an event."""

    event_type = event.get("type", "<unknown>")
    timestamp = event.get("timestamp", "?")
    payload = event.get("payload", {})
    payload_type = payload.get("type") if isinstance(payload, dict) else None

    summary_lines: list[str] = []
    header = f"{event_type}"
    if payload_type:
        header += f" ({payload_type})"
    header += f" @ {timestamp}"
    summary_lines.append(header)

    if isinstance(payload, dict):
        summary_lines.extend(_describe_payload(event_type, payload_type, payload))

    return "\n".join(summary_lines)


def _describe_payload(
    event_type: str, payload_type: str | None, payload: dict[str, Any]
) -> list[str]:
    """Route payload description to the appropriate helper."""

    if event_type == "event_msg":
        return _describe_event_msg(payload_type, payload)
    if event_type == "response_item":
        return _describe_response_item(payload_type, payload)
    if event_type == "turn_context":
        return _describe_turn_context(payload)
    if payload_type == "turn_context":
        return _describe_turn_context(payload)
    return []


def _describe_event_msg(payload_type: str | None, payload: dict[str, Any]) -> list[str]:
    """Describe payloads attached to event_msg entries, such as reasoning or messages."""

    result = []

    if payload_type == "agent_reasoning":
        text = payload.get("text")
        if isinstance(text, str) and text.strip():
            result.append(indent("reasoning: " + shorten(text, 500), "    "))

    elif payload_type == "token_count":
        result.extend(_describe_token_count(payload))

    elif payload_type == "agent_message":
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            result.append(indent(shorten(message, 500), "    message: "))

    elif payload_type == "turn_aborted":
        reason = payload.get("reason")
        if isinstance(reason, str):
            result.append(indent(f"reason: {reason}", "    "))

    return result


def _describe_token_count(payload: dict[str, Any]) -> list[str]:
    """Render token utilization information for token_count payloads."""

    lines: list[str] = []
    rate_limits = payload.get("rate_limits", {})
    if not isinstance(rate_limits, dict):
        return lines
    for label in ("primary", "secondary"):
        data = rate_limits.get(label)
        if not isinstance(data, dict):
            continue
        used_percent = data.get("used_percent")
        window_minutes = data.get("window_minutes")
        resets = data.get("resets_at") or data.get("resets_in_seconds")
        detail = f"{label}: {used_percent}% used of {window_minutes} min window"
        if resets is not None:
            detail += f", resets {resets}"
        lines.append(indent(detail, "    "))
    return lines


def _describe_response_item(
    payload_type: str | None, payload: dict[str, Any]
) -> list[str]:
    """Describe response_item payload contents (messages, function calls, outputs)."""

    lines: list[str] = []
    if payload_type == "reasoning":
        summary_texts = payload.get("summary")
        if isinstance(summary_texts, list) and summary_texts:
            text_entry = summary_texts[0]
            text = text_entry.get("text") if isinstance(text_entry, dict) else None
            if isinstance(text, str):
                lines.append(indent("summary: " + shorten(text, 500), "    "))

    if payload_type == "message":
        content = payload.get("content")
        if isinstance(content, list):
            texts = [
                str(item.get("text"))
                for item in content
                if isinstance(item, dict) and isinstance(item.get("text"), str)
            ]
            if texts:
                joined_text = " ".join(texts)
                lines.append(indent(shorten(joined_text, 500), "    message: "))

    if payload_type == "function_call":
        name = payload.get("name")
        arguments = payload.get("arguments")
        if name:
            lines.append(indent(f"function: {name}", "    "))
        if isinstance(arguments, str) and arguments.strip():
            lines.append(indent("args: " + shorten(arguments, 500), "    "))

    if payload_type == "function_call_output":
        output = payload.get("output")
        if isinstance(output, str):
            lines.append(indent("output: " + shorten(output, 500), "    "))

    return lines


def _describe_turn_context(payload: dict[str, Any]) -> list[str]:
    """Render turn context metadata for display."""

    cwd = payload.get("cwd")
    if isinstance(cwd, str):
        return [indent(f"cwd: {cwd}", "    ")]
    return []


def build_parser() -> argparse.ArgumentParser:
    """Build argument parser for the CLI."""

    parser = argparse.ArgumentParser(
        description="Group AI agent session events by user prompts.",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Write grouped output to the given text file (in addition to console).",
    )
    return parser


def write_report(output_path: Path, lines: list[str]) -> None:
    """Write grouped output to file with parent directory creation."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport written to {output_path}")


def main() -> None:
    """Entry point for the grouping CLI."""

    _reconfigure_stdout()
    args = build_parser().parse_args()

    config: SessionsConfig | None = None
    output_path: Path | None = args.output
    try:
        config = _load_configuration()
        if output_path is None:
            output_path = config.outputs.reports_dir / "session.txt"
        # Use first available session root
        sessions_root = config.codex_root or config.copilot_root
        if not sessions_root:
            raise ConfigError(
                "No session roots configured (codex_root or copilot_root required)"
            )
        session_file = find_first_session_file(sessions_root)
    except (ConfigError, SessionDiscoveryError) as err:
        if isinstance(err, ConfigError):
            message = f"Configuration error: {err}"
        else:
            message = f"Session discovery error: {err}"
        print(message)
        if output_path:
            write_report(output_path, [message])
        return

    captured_output = _render_session(session_file)

    if output_path:
        write_report(output_path, captured_output)


def _reconfigure_stdout() -> None:
    """Ensure stdout can emit UTF-8 characters."""

    try:
        reconfigure = getattr(sys.stdout, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")
    except ValueError:
        # Some streams (like redirected output) may not support reconfigure.
        pass


def _load_configuration() -> SessionsConfig:
    """Load sessions configuration with user-friendly error handling."""

    try:
        return load_config()
    except ConfigError as err:
        raise ConfigError(err) from err


def _render_session(session_file: Path) -> list[str]:
    """Print and capture the grouped session output."""

    events = load_session_events(session_file)
    prelude, groups = group_by_user_messages(events)
    captured: list[str] = []

    _emit(f"Session file: {session_file}", captured)
    _render_prelude(prelude, captured)
    _render_groups(groups, captured)

    return captured


def _render_prelude(prelude: list[dict[str, Any]], captured: list[str]) -> None:
    """Render prelude events that occur before the first user prompt."""

    if not prelude:
        return

    _emit("", captured)
    _emit("-- Session Prelude --", captured)
    for event in prelude:
        _emit(indent(describe_event(event), "  "), captured)


def _render_groups(groups: list[dict[str, Any]], captured: list[str]) -> None:
    """Render all prompt groups or emit a notice when none are present."""

    if not groups:
        _emit("\nNo user messages found in session.", captured)
        return

    for index, group in enumerate(groups, start=1):
        _render_prompt_group(index, group, captured)


def _render_prompt_group(
    index: int, group: dict[str, Any], captured: list[str]
) -> None:
    """Render a single prompt group and its subsequent events."""

    user_event = group.get("user", {})
    user_payload = user_event.get("payload", {}) if isinstance(user_event, dict) else {}
    prompt_message = (
        user_payload.get("message", "") if isinstance(user_payload, dict) else ""
    )
    prompt = prompt_message.strip()

    title = f"\n== Prompt {index} @ {user_event.get("timestamp", "?")} =="
    prompt_text = indent(shorten(prompt, limit=500) or "<empty prompt>", "  ")

    _emit(title, captured)
    _emit(prompt_text, captured)

    events = group.get("events", [])
    if not events:
        _emit("  (No subsequent events recorded.)", captured)
        return

    _emit("  -- Following events --", captured)
    for event in events:
        _emit(indent(describe_event(event), "    "), captured)


def _emit(line: str, captured: list[str]) -> None:
    """Print a line and append it to the captured output buffer."""

    print(line)
    captured.append(line)


if __name__ == "__main__":
    main()
