"""CoPilot agent support (AI-assisted by Claude Haiku 4.5).

GitHub CoPilot chat session parsing and ingestion for transparency auditing.

Modules:
    config: Configuration for CoPilot ingestion.
    models: Data models representing CoPilot session structure.
    parser: Session discovery and parsing logic.
"""

from src.agents.copilot.config import CoPilotConfig
from src.agents.copilot.models import Request, ResponsePart, Session
from src.agents.copilot.parser import (
    CoPilotParseError,
    find_copilot_session_files,
    parse_copilot_session,
    parse_copilot_session_from_file,
    parse_copilot_request,
    parse_copilot_variable_data,
    parse_copilot_response_part,
)

__all__ = [
    "CoPilotConfig",
    "CoPilotParseError",
    "Request",
    "ResponsePart",
    "Session",
    "find_copilot_session_files",
    "parse_copilot_session",
    "parse_copilot_session_from_file",
    "parse_copilot_request",
    "parse_copilot_variable_data",
    "parse_copilot_response_part",
]
