"""Utilities for discovering and grouping Codex session logs.

Purpose: Discover Codex session files and transform JSONL events into grouped structures.
Author: Codex with Lauren Parlett
Date: 2025-10-30
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Iterator


class SessionDiscoveryError(RuntimeError):
    """Raised when the requested session file cannot be found."""


def iter_sorted_directories(parent: Path) -> Iterable[Path]:
    """Yield child directories sorted by name."""

    for child in sorted(parent.iterdir(), key=lambda p: p.name):
        if child.is_dir():
            yield child


def find_first_session_file(root: Path) -> Path:
    """Return the earliest (year/month/day) session file found under root."""

    for year_dir in iter_sorted_directories(root):
        for month_dir in iter_sorted_directories(year_dir):
            for day_dir in iter_sorted_directories(month_dir):
                files = sorted(
                    (p for p in day_dir.iterdir() if p.is_file()),
                    key=lambda p: p.name,
                )
                if files:
                    return files[0]
    raise SessionDiscoveryError(f"No session files found under {root}")


def iter_session_files(root: Path) -> Iterator[Path]:
    """Yield all session files under ``root`` sorted by year/month/day/file."""

    for year_dir in iter_sorted_directories(root):
        for month_dir in iter_sorted_directories(year_dir):
            for day_dir in iter_sorted_directories(month_dir):
                for file_path in sorted(day_dir.iterdir(), key=lambda p: p.name):
                    if file_path.is_file():
                        yield file_path


def load_session_events(file_path: Path) -> list[dict[str, Any]]:
    """Load JSONL session events from disk."""

    events: list[dict[str, Any]] = []
    with file_path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                events.append(json.loads(raw_line))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Failed to parse JSON on line {line_number} of {file_path}: {exc}"
                ) from exc
    return events


def group_by_user_messages(
    events: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Group event stream so each user_message anchors the subsequent events.

    Returns:
        A tuple containing:
            - A list of events that occurred before the first user message.
            - A list of groups. Each group is a dict with keys:
              ``user`` (the user_message event) and ``events`` (list of following events
              until the next user_message).
    """

    prelude: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    current_group: dict[str, Any] | None = None

    for event in events:
        if (
            event.get("type") == "event_msg"
            and isinstance(event.get("payload"), dict)
            and event["payload"].get("type") == "user_message"
        ):
            current_group = {"user": event, "events": []}
            groups.append(current_group)
            continue

        if current_group is None:
            prelude.append(event)
        else:
            current_group["events"].append(event)

    return prelude, groups
