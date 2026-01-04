"""Codex-specific log parser implementation."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, cast, Generator

from ...core.interfaces.parser import AgentLogMetadata, ILogParser
from ...core.models.base_event import BaseEvent
from .errors import InvalidEventError, InvalidMetadataError
from .models import CodexMessage, CodexAction


class CodexParser(ILogParser):
    """Parser for Codex session logs."""

    @property
    def agent_type(self) -> str:
        """Get the type identifier for this agent parser."""
        return "codex"

    def get_metadata(self, file_path: Path) -> AgentLogMetadata:
        """Extract metadata from a Codex log file.

        Args:
            file_path: Path to the log file

        Returns:
            Metadata about the log file

        Raises:
            InvalidMetadataError: If metadata cannot be extracted
            FileNotFoundError: If the file doesn't exist
            PermissionError: If the file can't be read
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                first_line = f.readline().strip()
                if not first_line:
                    raise InvalidMetadataError("Empty log file", file_path)

                try:
                    event = json.loads(first_line)
                except json.JSONDecodeError as e:
                    raise InvalidMetadataError(
                        f"Invalid JSON: {e}", file_path, line_number=1
                    ) from e

                if not isinstance(event, dict):
                    raise InvalidMetadataError(
                        "Event must be a JSON object", file_path, line_number=1
                    )

                if event.get("type") != "session_meta":
                    raise InvalidMetadataError(
                        "First event must be session_meta", file_path, line_number=1
                    )

                payload = event.get("payload", {})
                if not isinstance(payload, dict):
                    raise InvalidMetadataError(
                        "Session meta payload must be a JSON object",
                        file_path,
                        line_number=1,
                    )

                timestamp_str = event.get("timestamp")
                if not isinstance(timestamp_str, str):
                    raise InvalidMetadataError(
                        "Invalid timestamp format", file_path, line_number=1
                    )

                try:
                    timestamp = datetime.fromisoformat(timestamp_str)
                except ValueError as e:
                    raise InvalidMetadataError(
                        f"Invalid timestamp format: {e}", file_path, line_number=1
                    ) from e

                session_id = payload.get("id")
                if not isinstance(session_id, str):
                    raise InvalidMetadataError(
                        "Missing or invalid session ID", file_path, line_number=1
                    )

                return AgentLogMetadata(
                    agent_type=self.agent_type,
                    session_id=session_id,
                    timestamp=timestamp,
                    workspace_path=cast(str | None, payload.get("cwd")),
                    version=cast(str | None, payload.get("version")),
                )
        except (OSError, IOError) as e:
            raise InvalidMetadataError(f"Failed to read file: {e}", file_path) from e

    def parse_file(self, file_path: Path) -> Iterator[BaseEvent]:
        """Parse a Codex log file into a sequence of events.

        Args:
            file_path: Path to the log file to parse

        Returns:
            Iterator of parsed events

        Raises:
            InvalidMetadataError: If metadata cannot be extracted
            InvalidEventError: If an event fails validation
            OSError: If file operations fail
        """
        metadata = self.get_metadata(file_path)
        session_id = metadata.session_id

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError as e:
                        raise InvalidEventError(
                            f"Invalid JSON: {e}", file_path, line_number=line_num
                        ) from e

                    if not self.validate_event(event):
                        raise InvalidEventError(
                            "Event failed validation", file_path, line_number=line_num
                        )

                    try:
                        yield from self._process_event(event, session_id, line_num)
                    except (ValueError, TypeError, KeyError) as e:
                        raise InvalidEventError(
                            f"Failed to process event: {e}",
                            file_path,
                            line_number=line_num,
                        ) from e
        except OSError as e:
            raise InvalidEventError(f"Failed to read file: {e}", file_path) from e

    def _process_event(
        self, event: dict[str, Any], session_id: str, line_num: int
    ) -> Iterator[BaseEvent]:
        """Process a single event into one or more BaseEvent instances.

        Args:
            event: The event data to process
            session_id: The session ID from metadata
            line_num: Line number for error reporting

        Returns:
            Iterator of parsed events

        Raises:
            ValueError: If event data is invalid
        """
        event_type = event.get("type")
        if not isinstance(event_type, str):
            raise ValueError(f"Missing or invalid event type at line {line_num}")

        timestamp_str = event.get("timestamp")
        if not isinstance(timestamp_str, str):
            raise ValueError(f"Missing or invalid timestamp at line {line_num}")

        try:
            timestamp = datetime.fromisoformat(timestamp_str)
        except ValueError as e:
            raise ValueError(f"Invalid timestamp format at line {line_num}: {e}") from e

        payload = event.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("Missing or invalid payload")

        if event_type == "event_msg":
            msg_type = payload.get("type")

            if msg_type == "user_message":
                yield CodexMessage.create(
                    CodexMessage.build_data(
                        content=payload.get("message", ""),
                        timestamp=timestamp,
                        is_user=True,
                        session_id=session_id,
                        raw_data=event,
                    )
                )
            elif msg_type == "ai_response":
                yield CodexMessage.create(
                    CodexMessage.build_data(
                        content=payload.get("message", ""),
                        timestamp=timestamp,
                        is_user=False,
                        session_id=session_id,
                        raw_data=event,
                    )
                )
            elif msg_type in ("tool_call", "tool_result"):
                tool_payload = payload.get("tool", {}) or {}
                details: dict[str, Any] = {
                    "tool_name": tool_payload.get("name"),
                    "parameters": tool_payload.get("parameters"),
                    "result": payload.get("result"),
                }
                yield CodexAction.create(
                    CodexAction.build_data(
                        action_type=msg_type,
                        session_id=session_id,
                        timestamp=timestamp,
                        details=details,
                        raw_data=event,
                    )
                )

    def _validate_base_structure(self, event_data: Any) -> bool:
        """Validate the base structure and common fields of an event.

        Args:
            event_data: Raw event data to validate

        Returns:
            True if valid, False if not
        """
        if not isinstance(event_data, dict):
            return False

        # Required fields
        required_fields = {"type", "timestamp"}
        if not all(field in event_data for field in required_fields):
            return False

        # Timestamp validation
        timestamp = event_data["timestamp"]
        if not isinstance(timestamp, str):
            return False

        try:
            datetime.fromisoformat(timestamp)
        except ValueError:
            return False

        return True

    def _validate_message_event(self, payload: dict[str, Any]) -> bool:
        """Validate a message event payload.

        Args:
            payload: Event payload to validate

        Returns:
            True if valid, False if not
        """
        msg_type = payload.get("type", "")
        if not isinstance(msg_type, str):
            return False

        if msg_type in ("user_message", "ai_response"):
            return isinstance(payload.get("message"), str)

        if msg_type in ("tool_call", "tool_result"):
            tool = payload.get("tool", {})
            if not isinstance(tool, dict):
                return False
            return isinstance(tool.get("name"), str)

        return False

    def validate_event(self, event_data: Any) -> bool:
        """Validate that an event matches Codex schema.

        Args:
            event_data: Raw event data to validate

        Returns:
            True if valid, False if not
        """
        if not self._validate_base_structure(event_data):
            return False

        event_type = event_data.get("type")
        if not isinstance(event_type, str):
            return False

        payload = event_data.get("payload")
        if not isinstance(payload, dict):
            return False

        # Type-specific validation
        if event_type == "session_meta":
            # Session meta only requires a dict payload
            return True

        if event_type == "event_msg":
            return self._validate_message_event(payload)

        return False

    def find_log_files(self, root_path: Path) -> Generator[Path, None, None]:
        """Find all Codex session files in the given root directory.

        Codex stores JSONL logs in a date-based hierarchy:
        /YYYY/MM/DD/*.jsonl

        Args:
            root_path: Root directory to search

        Returns:
            Generator yielding Path objects for session files
        """
        # Codex uses JSONL files organized by date (year/month/day)
        for jsonl_file in root_path.glob("**/*.jsonl"):
            yield jsonl_file

    def get_agent_type(self) -> str:
        """Get the agent type identifier.

        Returns:
            String identifier for this agent type ("codex")
        """
        return self.agent_type
