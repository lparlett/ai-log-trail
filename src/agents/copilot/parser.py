"""CoPilot session parser (AI-assisted by Claude Haiku 4.5).

Loads and parses GitHub CoPilot chat session JSON files from VS Code
workspaceStorage directories. Normalizes sessions into structured models.

Two APIs available:
1. Module-level functions (backward compatible):
    session = parse_session_from_file(Path("...session.json"))
    for request in session.requests:
        print(request.message.text)

2. Class-based ILogParser interface (parallel to CodexParser):
    parser = CoPilotParser()
    metadata = parser.get_metadata(file_path)
    for event in parser.parse_file(file_path):
        ...

Typical usage (recommended):
    session = parse_session_from_file(Path("...session.json"))
    for request in session.requests:
        print(request.message.text)
        for response_part in request.response:
            if response_part.value:
                print(response_part.value)
"""

# pylint: disable=logging-fstring-interpolation

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional, cast, Generator

from src.agents.copilot.models import (
    Message,
    Request,
    ResponsePart,
    Session,
    URI,
    Variable,
    VariableData,
    parse_message,
    parse_uri,
)
from src.core.interfaces.parser import AgentLogMetadata, ILogParser
from src.core.models.base_event import BaseEvent

logger = logging.getLogger(__name__)


class CoPilotParseError(Exception):
    """Raised when CoPilot session parsing fails."""


class CoPilotParser(ILogParser):
    """Parser for CoPilot session files following the ILogParser interface.

    Provides the same parallel API as CodexParser for consistent usage across agents.
    """

    @property
    def agent_type(self) -> str:
        """Get the type identifier for this agent parser."""
        return "copilot"

    def get_metadata(self, file_path: Path) -> AgentLogMetadata:
        """Extract metadata from a CoPilot session file.

        Args:
            file_path: Path to the CoPilot session JSON file

        Returns:
            Metadata about the session file

        Raises:
            CoPilotParseError: If metadata cannot be extracted
        """
        try:
            session = parse_session_from_file(file_path)
            # Generate session ID from file path (CoPilot doesn't track session ID in data)
            session_id = file_path.stem

            # Use first request timestamp if available, otherwise use file mtime
            timestamp = None
            if session.requests:
                request_ts = session.requests[0].timestamp
                if request_ts:
                    timestamp = datetime.fromtimestamp(request_ts / 1000.0)

            if not timestamp:
                # Fallback to file modification time
                timestamp = datetime.fromtimestamp(file_path.stat().st_mtime)

            return AgentLogMetadata(
                agent_type=self.agent_type,
                session_id=session_id,
                timestamp=timestamp,
                version=None,  # CoPilot sessions don't track version in metadata
            )
        except CoPilotParseError:
            raise
        except Exception as e:
            raise CoPilotParseError(
                f"Failed to extract metadata from {file_path}: {e}"
            ) from e

    def parse_file(self, file_path: Path) -> Iterator[BaseEvent]:
        """Parse a CoPilot session file into a sequence of events.

        Note: This method yields Session objects via an Iterator wrapper.
        CoPilot Session objects contain the full parsed chat history and are
        compatible with the ingest pipeline via ingest_copilot.py.

        Args:
            file_path: Path to the CoPilot session JSON file

        Returns:
            Iterator that yields the parsed Session object

        Raises:
            CoPilotParseError: If the file cannot be parsed
        """
        try:
            session = parse_session_from_file(file_path)
            # Yield Session object cast as BaseEvent for interface compatibility
            # The ingest pipeline knows how to handle Session objects
            yield cast(BaseEvent, session)
        except CoPilotParseError:
            raise
        except Exception as e:
            raise CoPilotParseError(f"Failed to parse file {file_path}: {e}") from e

    def find_log_files(self, root_path: Path) -> Generator[Path, None, None]:
        """Find all CoPilot session files in the given root directory.

        CoPilot stores session JSON files in VS Code's workspaceStorage.
        This method searches for *.json files that contain CoPilot sessions.

        Args:
            root_path: Root directory to search

        Returns:
            Generator yielding Path objects for session files
        """
        # CoPilot sessions are JSON files (not JSONL) in chatSessions directories
        for json_file in root_path.glob("**/*.json"):
            # For CoPilot, we can check if the file is in a chatSessions directory
            # or simply yield JSON files found - validation happens at parse time
            if "chatSessions" in json_file.parts:
                yield json_file

    def validate_event(self, event_data: Any) -> bool:
        """Validate that event data is from a CoPilot session.

        For now, this is a simple heuristic - a file is considered valid
        if it can be parsed as a CoPilot session.

        Args:
            event_data: Event or file data to validate

        Returns:
            True if the data appears to be from a CoPilot session
        """
        # CoPilot sessions should have requester/responder and version fields
        # This is a basic validation - real validation happens in parse_session()
        return isinstance(event_data, dict)

    def get_agent_type(self) -> str:
        """Get the agent type identifier.

        Returns:
            String identifier for this agent type ("copilot")
        """
        return self.agent_type


def parse_copilot_session_from_file(file_path: Path) -> Session:
    """Load and parse a CoPilot chat session from a JSON file.

    Args:
        file_path: Path to a CoPilot session JSON file.

    Returns:
        Parsed Session object.

    Raises:
        CoPilotParseError: If the file cannot be read or parsed.
    """
    if not file_path.exists():
        raise CoPilotParseError(f"File not found: {file_path}")

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise CoPilotParseError(f"Invalid JSON in {file_path}: {e}") from e
    except OSError as e:
        raise CoPilotParseError(f"Cannot read {file_path}: {e}") from e

    return parse_copilot_session(data)


def parse_copilot_session(data: dict[str, Any]) -> Session:
    """Parse a CoPilot session from deserialized JSON data.

    Args:
        data: Deserialized session JSON as a dictionary.

    Returns:
        Parsed Session object.

    Raises:
        CoPilotParseError: If the data structure is invalid.
    """
    if not isinstance(data, dict):
        raise CoPilotParseError("Session data must be a dictionary")

    requests = []
    if "requests" in data:
        for req_data in data["requests"]:
            try:
                req = parse_copilot_request(req_data)
                requests.append(req)
            except CoPilotParseError as e:
                logger.warning("Failed to parse request: %s", e)
                continue

    requester_avatar = parse_uri(data.get("requesterAvatarIconUri"))
    responder_avatar = data.get("responderAvatarIconUri")

    session = Session(
        version=data.get("version", 3),
        requesterUsername=data.get("requesterUsername", ""),
        requesterAvatarIconUri=requester_avatar,
        responderUsername=data.get("responderUsername", "GitHub Copilot"),
        responderAvatarIconUri=responder_avatar,
        initialLocation=data.get("initialLocation", "panel"),
        requests=requests,
        metadata=data.get("metadata", {}),
    )

    return session


def parse_copilot_request(data: dict[str, Any]) -> Request:
    """Parse a single CoPilot request from session data.

    Args:
        data: Request dictionary.

    Returns:
        Parsed Request object.

    Raises:
        CoPilotParseError: If required fields are missing.
    """
    if "requestId" not in data:
        raise CoPilotParseError("Request missing 'requestId' field")

    message = Message()
    if "message" in data:
        message = parse_message(data["message"])

    variable_data = VariableData()
    if "variableData" in data:
        variable_data = parse_copilot_variable_data(data["variableData"])

    response = []
    if "response" in data:
        for resp_data in data["response"]:
            try:
                resp = parse_copilot_response_part(resp_data)
                response.append(resp)
            except CoPilotParseError as e:
                logger.warning("Failed to parse response part: %s", e)
                continue

    return Request(
        requestId=data["requestId"],
        message=message,
        variableData=variable_data,
        response=response,
        timestamp=data.get("timestamp"),
    )


def parse_copilot_variable_data(data: dict[str, Any]) -> VariableData:
    """Parse CoPilot variable context data from a request.

    Args:
        data: variableData dictionary.

    Returns:
        Parsed VariableData object.
    """
    variables = []
    if "variables" in data:
        for var_data in data["variables"]:
            try:
                var = Variable(
                    kind=var_data.get("kind", ""),
                    id=var_data.get("id", ""),
                    name=var_data.get("name", ""),
                    value=var_data.get("value"),
                    modelDescription=var_data.get("modelDescription", ""),
                )
                variables.append(var)
            except (KeyError, TypeError, ValueError) as e:
                logger.warning("Failed to parse variable: %s", e)
                continue

    return VariableData(variables=variables)


def parse_copilot_response_part(data: dict[str, Any]) -> ResponsePart:
    """Parse a single CoPilot response part from an assistant response.

    Args:
        data: Response part dictionary.

    Returns:
        Parsed ResponsePart object.
    """
    kind = data.get("kind", "text")

    # Parse URIs if present
    base_uri = parse_uri(data.get("baseUri")) if "baseUri" in data else None
    uri = parse_uri(data.get("uri")) if "uri" in data else None
    inline_ref = (
        parse_uri(data.get("inlineReference")) if "inlineReference" in data else None
    )

    uris: Optional[dict[str, URI]] = None
    if "uris" in data and isinstance(data["uris"], dict):
        uris = {}
        for key, uri_data in data["uris"].items():
            if parsed_uri := parse_uri(uri_data):
                uris[key] = parsed_uri

    return ResponsePart(
        kind=kind,
        value=data.get("value"),
        id=data.get("id"),
        supportThemeIcons=data.get("supportThemeIcons", False),
        supportHtml=data.get("supportHtml", False),
        baseUri=base_uri,
        uris=uris,
        toolName=data.get("toolName"),
        invocationMessage=data.get("invocationMessage"),
        pastTenseMessage=data.get("pastTenseMessage"),
        isConfirmed=data.get("isConfirmed"),
        isComplete=data.get("isComplete", False),
        source=data.get("source"),
        toolCallId=data.get("toolCallId", ""),
        toolId=data.get("toolId", ""),
        presentation=data.get("presentation", "default"),
        uri=uri,
        isEdit=data.get("isEdit", False),
        edits=data.get("edits"),
        inlineReference=inline_ref,
        done=data.get("done", False),
    )


def find_copilot_session_files(root_path: Path) -> list[Path]:
    """Find all CoPilot chat session files in a directory tree.

    Searches for chatSessions subdirectories and returns all *.json files.

    Args:
        root_path: Root directory to search (typically workspaceStorage parent).

    Returns:
        List of paths to CoPilot session JSON files.
    """
    sessions = []
    try:
        for chat_dir in root_path.glob("*/chatSessions"):
            if chat_dir.is_dir():
                for json_file in chat_dir.glob("*.json"):
                    sessions.append(json_file)
    except OSError as e:
        logger.warning("Failed to discover sessions in %s: %s", root_path, e)

    return sorted(sessions)


# Backward compatibility aliases (deprecated - use new names with agent type prefix)
discover_copilot_sessions = find_copilot_session_files
parse_session = parse_copilot_session
parse_session_from_file = parse_copilot_session_from_file
parse_request = parse_copilot_request
parse_variable_data = parse_copilot_variable_data
parse_response_part = parse_copilot_response_part
