"""CoPilot chat session data models (AI-assisted by Claude Haiku 4.5).

Defines the structure of GitHub CoPilot chat session JSON files stored in
VS Code workspaceStorage/*/chatSessions/ directories.

Schemas:
- Session: Top-level container for a single chat session
- Message: A user or assistant message with parts and optional variables
- Request: User request with message, context (variableData), and responses
- Response: Assistant response, including tool invocations, text edits, etc.
- ToolInvocation: Represents a tool call (copilot_readFile, copilot_replaceString, etc.)
"""

# pylint: disable=too-many-instance-attributes,invalid-name

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Range:
    """Text range or selection in an editor."""

    start: int
    endExclusive: int


@dataclass
class EditorRange:
    """Editor-specific range with line/column positions."""

    startLineNumber: int
    startColumn: int
    endLineNumber: int
    endColumn: int
    selectionStartLineNumber: Optional[int] = None
    selectionStartColumn: Optional[int] = None
    positionLineNumber: Optional[int] = None
    positionColumn: Optional[int] = None


@dataclass
class MessagePart:
    """A part of a message (text, code block, reference, etc.)."""

    text: str
    kind: str = "text"
    range: Optional[Range] = None
    editorRange: Optional[EditorRange] = None


@dataclass
class Message:
    """A message in the chat (user or assistant)."""

    parts: list[MessagePart] = field(default_factory=list)
    text: str = ""


@dataclass
class URI:
    """A URI representation for files and references."""

    mid: int = 1
    path: str = ""
    scheme: str = "file"
    authority: Optional[str] = None
    query: Optional[str] = None
    fsPath: Optional[str] = None
    _sep: Optional[int] = None
    external: Optional[str] = None


@dataclass
class FileReference:
    """Reference to a file with URI and optional range."""

    uri: URI
    range: Optional[dict[str, Any]] = None


@dataclass
class Variable:
    """A variable in variableData (file selection, workspace, etc.)."""

    kind: str
    id: str
    name: str
    value: Any
    modelDescription: str = ""


@dataclass
class VariableData:
    """Context variables available in a request."""

    variables: list[Variable] = field(default_factory=list)


@dataclass
class ToolInvocationResponse:
    """Response from a tool invocation (e.g., copilot_readFile)."""

    kind: str
    toolName: Optional[str] = None
    invocationMessage: Optional[Any] = None
    isConfirmed: Optional[dict[str, int]] = None
    isComplete: bool = False
    source: Optional[dict[str, str]] = None
    toolCallId: str = ""
    toolId: str = ""
    presentation: str = "default"
    pastTenseMessage: Optional[Any] = None


@dataclass
class TextEditGroup:
    """A group of text edits applied to a file."""

    kind: str
    uri: URI
    edits: list[list[dict[str, Any]]] = field(default_factory=list)
    done: bool = False


@dataclass
class ResponsePart:
    """A single part of an assistant response."""

    kind: str
    value: Optional[str] = None
    id: Optional[str] = None
    supportThemeIcons: bool = False
    supportHtml: bool = False
    baseUri: Optional[URI] = None
    uris: Optional[dict[str, URI]] = None
    toolName: Optional[str] = None
    invocationMessage: Optional[Any] = None
    pastTenseMessage: Optional[Any] = None
    isConfirmed: Optional[dict[str, int]] = None
    isComplete: bool = False
    source: Optional[dict[str, str]] = None
    toolCallId: str = ""
    toolId: str = ""
    presentation: str = "default"
    uri: Optional[URI] = None
    isEdit: bool = False
    edits: Optional[list[Any]] = None
    inlineReference: Optional[URI] = None
    # For textEditGroup
    done: bool = False
    # For undoStop
    # For codeblockUri


@dataclass
class Request:
    """A user request in a chat session."""

    requestId: str
    message: Message
    variableData: VariableData = field(default_factory=VariableData)
    response: list[ResponsePart] = field(default_factory=list)
    timestamp: Optional[int] = None


@dataclass
class Session:
    """A complete CoPilot chat session."""

    version: int = 3
    requesterUsername: str = ""
    requesterAvatarIconUri: Optional[URI] = None
    responderUsername: str = "GitHub Copilot"
    responderAvatarIconUri: Optional[dict[str, Any]] = None
    initialLocation: str = "panel"
    requests: list[Request] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def parse_uri(data: Any) -> Optional[URI]:
    """Parse a URI object from session data."""
    if not isinstance(data, dict):
        return None
    return URI(
        mid=data.get("$mid", 1),
        path=data.get("path", ""),
        scheme=data.get("scheme", "file"),
        authority=data.get("authority"),
        query=data.get("query"),
        fsPath=data.get("fsPath"),
        _sep=data.get("_sep"),
        external=data.get("external"),
    )


def parse_message(data: dict[str, Any]) -> Message:
    """Parse a message from session data."""
    parts = []
    if "parts" in data:
        for part_data in data["parts"]:
            range_obj = None
            if "range" in part_data:
                r = part_data["range"]
                range_obj = Range(start=r["start"], endExclusive=r["endExclusive"])

            editor_range_obj = None
            if "editorRange" in part_data:
                er = part_data["editorRange"]
                editor_range_obj = EditorRange(
                    startLineNumber=er.get("startLineNumber", 0),
                    startColumn=er.get("startColumn", 0),
                    endLineNumber=er.get("endLineNumber", 0),
                    endColumn=er.get("endColumn", 0),
                    selectionStartLineNumber=er.get("selectionStartLineNumber"),
                    selectionStartColumn=er.get("selectionStartColumn"),
                    positionLineNumber=er.get("positionLineNumber"),
                    positionColumn=er.get("positionColumn"),
                )

            parts.append(
                MessagePart(
                    text=part_data.get("text", ""),
                    kind=part_data.get("kind", "text"),
                    range=range_obj,
                    editorRange=editor_range_obj,
                )
            )

    return Message(parts=parts, text=data.get("text", ""))
