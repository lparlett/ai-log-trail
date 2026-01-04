"""Additional tests for ingest.py coverage (AI-assisted).

Focuses on agent detection with various input scenarios.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.services.ingest import detect_agent_type


def test_detect_agent_type_codex_sample_session() -> None:
    """Test agent detection with Codex sample session fixture."""
    session_file = Path("tests/fixtures/codex_sample_session.jsonl")
    result = detect_agent_type(session_file)
    if result != "codex":
        raise AssertionError(f"Expected 'codex', got '{result}'")


def test_detect_agent_type_codex_file_updates() -> None:
    """Test agent detection with Codex file updates fixture."""
    session_file = Path("tests/fixtures/codex_file_updates.jsonl")
    result = detect_agent_type(session_file)
    if result != "codex":
        raise AssertionError(f"Expected 'codex', got '{result}'")


def test_detect_agent_type_copilot_session() -> None:
    """Test agent detection with CoPilot sanitized session fixture."""
    session_file = Path("tests/fixtures/copilot_sanitized_session.json")
    result = detect_agent_type(session_file)
    if result != "copilot":
        raise AssertionError(f"Expected 'copilot', got '{result}'")


def test_detect_agent_type_missing_file() -> None:
    """Test agent detection raises error for missing files."""
    with pytest.raises(FileNotFoundError):
        detect_agent_type(Path("nonexistent.jsonl"))


def test_detect_agent_type_empty_file(tmp_path: Path) -> None:
    """Test agent detection raises error for empty files."""
    empty_file = tmp_path / "empty.jsonl"
    empty_file.write_text("")
    with pytest.raises(ValueError, match="Empty file"):
        detect_agent_type(empty_file)


def test_detect_agent_type_unrecognized_format(tmp_path: Path) -> None:
    """Test agent detection raises error for unrecognized formats."""
    bad_file = tmp_path / "bad.jsonl"
    bad_file.write_text('{"type": "unknown_event_type"}')
    with pytest.raises(ValueError, match="No recognized event types"):
        detect_agent_type(bad_file)
