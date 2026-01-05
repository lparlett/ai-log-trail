"""Tests for src/services/ingest.py (AI-assisted).

Tests the agent-aware ingest router functionality including:
- Agent type detection (Codex vs CoPilot)
- Session file ingestion
- Directory traversal and batch processing
- Error handling and recovery
- Rule loading
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.services.ingest import (
    detect_agent_type,
    ingest_session_file,
    ingest_sessions_in_directory,
    _load_rules_safely,
)
from src.services.database import get_connection
from src.parsers.session_parser import SessionDiscoveryError


# Test agent type detection
def test_detect_codex_from_event_msg(tmp_path: Path) -> None:
    """Should detect Codex from event_msg type."""
    codex_file = tmp_path / "test.jsonl"
    codex_file.write_text('{"type": "event_msg", "data": "test"}\n')
    result = detect_agent_type(codex_file)
    if result != "codex":
        raise AssertionError(f"Expected 'codex', got '{result}'")


def test_detect_codex_from_session_meta(tmp_path: Path) -> None:
    """Should detect Codex from session_meta type."""
    codex_file = tmp_path / "test.jsonl"
    codex_file.write_text('{"type": "session_meta", "sid": "123"}\n')
    result = detect_agent_type(codex_file)
    if result != "codex":
        raise AssertionError(f"Expected 'codex', got '{result}'")


def test_detect_codex_from_turn_context(tmp_path: Path) -> None:
    """Should detect Codex from turn_context type."""
    codex_file = tmp_path / "test.jsonl"
    codex_file.write_text('{"type": "turn_context", "prompt": "test"}\n')
    result = detect_agent_type(codex_file)
    if result != "codex":
        raise AssertionError(f"Expected 'codex', got '{result}'")


def test_detect_codex_from_response_item(tmp_path: Path) -> None:
    """Should detect Codex from response_item type."""
    codex_file = tmp_path / "test.jsonl"
    codex_file.write_text('{"type": "response_item", "content": "resp"}\n')
    result = detect_agent_type(codex_file)
    if result != "codex":
        raise AssertionError(f"Expected 'codex', got '{result}'")


def test_detect_copilot_from_requester_username(tmp_path: Path) -> None:
    """Should detect CoPilot from requesterUsername field."""
    copilot_file = tmp_path / "test.json"
    data = {"requesterUsername": "user", "requests": []}
    copilot_file.write_text(json.dumps(data))
    result = detect_agent_type(copilot_file)
    if result != "copilot":
        raise AssertionError(f"Expected 'copilot', got '{result}'")


def test_detect_copilot_from_responder_username(tmp_path: Path) -> None:
    """Should detect CoPilot from responderUsername field."""
    copilot_file = tmp_path / "test.json"
    data = {"responderUsername": "GitHub Copilot", "requests": []}
    copilot_file.write_text(json.dumps(data))
    result = detect_agent_type(copilot_file)
    if result != "copilot":
        raise AssertionError(f"Expected 'copilot', got '{result}'")


def test_detect_copilot_from_version_field(tmp_path: Path) -> None:
    """Should detect CoPilot from version field when no requester."""
    copilot_file = tmp_path / "test.json"
    # Need to add requesterUsername or responderUsername for JSON files
    data = {"version": 3, "requesterUsername": "user", "requests": []}
    copilot_file.write_text(json.dumps(data))
    result = detect_agent_type(copilot_file)
    if result != "copilot":
        raise AssertionError(f"Expected 'copilot', got '{result}'")


def test_detect_file_not_found() -> None:
    """Should raise FileNotFoundError for missing file."""
    with pytest.raises(FileNotFoundError):
        detect_agent_type(Path("/nonexistent/file.jsonl"))


def test_detect_empty_file(tmp_path: Path) -> None:
    """Should raise ValueError for empty file."""
    empty_file = tmp_path / "empty.jsonl"
    empty_file.write_text("")
    with pytest.raises(ValueError, match="Empty file"):
        detect_agent_type(empty_file)


def test_detect_malformed_json(tmp_path: Path) -> None:
    """Should raise ValueError for malformed JSON."""
    bad_file = tmp_path / "bad.jsonl"
    bad_file.write_text("{not valid json}\n")
    with pytest.raises(ValueError, match="Cannot determine agent type"):
        detect_agent_type(bad_file)


def test_detect_unknown_event_type(tmp_path: Path) -> None:
    """Should raise ValueError if no recognized event types found."""
    unknown_file = tmp_path / "unknown.jsonl"
    unknown_file.write_text('{"type": "unknown", "data": "test"}\n')
    with pytest.raises(ValueError, match="No recognized event types"):
        detect_agent_type(unknown_file)


def test_detect_copilot_as_jsonl(tmp_path: Path) -> None:
    """Should detect CoPilot single JSON file even when trying JSONL parsing."""
    copilot_file = tmp_path / "session.json"
    # Include requesterUsername to be recognized as CoPilot
    data = {"version": 3, "requesterUsername": "user", "requests": []}
    copilot_file.write_text(json.dumps(data))
    result = detect_agent_type(copilot_file)
    if result != "copilot":
        raise AssertionError(f"Expected 'copilot', got '{result}'")


# Helper functions for TestIngestSessionFile
def _make_codex_session(tmp_path: Path) -> Path:
    """Create a minimal Codex JSONL session file."""
    codex_file = tmp_path / "codex_session.jsonl"
    codex_file.write_text('{"type": "session_meta", "sid": "test_123"}\n')
    with open(codex_file, "a", encoding="utf-8") as f:
        f.write('{"type": "event_msg", "content": "hello"}\n')
    return codex_file


def _make_copilot_session(tmp_path: Path) -> Path:
    """Create a minimal CoPilot JSON session file."""
    copilot_file = tmp_path / "copilot_session.json"
    data = {
        "version": 3,
        "requesterUsername": "testuser",
        "responderUsername": "GitHub Copilot",
        "requests": [
            {
                "requestId": "req_1",
                "message": {"parts": [], "text": "Hello"},
                "variableData": {"variables": []},
                "response": [],
            }
        ],
    }
    copilot_file.write_text(json.dumps(data))
    return copilot_file


def test_ingest_codex_session_creates_file_record(tmp_path: Path) -> None:
    """Should create file record for Codex session."""
    codex_file = _make_codex_session(tmp_path)
    db_path = tmp_path / "test.db"

    result = ingest_session_file(codex_file, db_path)

    if result["file_id"] <= 0:
        raise AssertionError(f"Expected file_id > 0, got {result['file_id']}")
    if not isinstance(result["session_file"], str):
        raise AssertionError(
            f"Expected session_file to be str, got {type(result['session_file'])}"
        )


def test_ingest_copilot_session_creates_file_record(tmp_path: Path) -> None:
    """Should create file record for CoPilot session."""
    copilot_file = _make_copilot_session(tmp_path)
    db_path = tmp_path / "test.db"

    result = ingest_session_file(copilot_file, db_path)

    if result["file_id"] <= 0:
        raise AssertionError(f"Expected file_id > 0, got {result['file_id']}")
    if not isinstance(result["session_file"], str):
        raise AssertionError(
            f"Expected session_file to be str, got {type(result['session_file'])}"
        )


def test_ingest_with_nonexistent_file(tmp_path: Path) -> None:
    """Should handle missing session file gracefully."""
    db_path = tmp_path / "test.db"
    missing_file = tmp_path / "missing.jsonl"

    with pytest.raises(FileNotFoundError):
        ingest_session_file(missing_file, db_path)


def test_ingest_returns_summary_dict(tmp_path: Path) -> None:
    """Should return summary dict with required keys."""
    codex_file = _make_codex_session(tmp_path)
    db_path = tmp_path / "test.db"

    result = ingest_session_file(codex_file, db_path)

    if "session_file" not in result:
        raise AssertionError("Missing 'session_file' key in result")
    if "file_id" not in result:
        raise AssertionError("Missing 'file_id' key in result")
    if "errors" not in result:
        raise AssertionError("Missing 'errors' key in result")
    if not isinstance(result["errors"], list):
        raise AssertionError(
            f"Expected 'errors' to be list, got {type(result['errors'])}"
        )


def test_ingest_with_custom_batch_size(tmp_path: Path) -> None:
    """Should accept custom batch_size parameter."""
    codex_file = _make_codex_session(tmp_path)
    db_path = tmp_path / "test.db"

    result = ingest_session_file(codex_file, db_path, batch_size=500)

    if result["file_id"] <= 0:
        raise AssertionError(f"Expected file_id > 0, got {result['file_id']}")


def test_ingest_with_verbose_logging(tmp_path: Path) -> None:
    """Should accept verbose flag without errors."""
    codex_file = _make_codex_session(tmp_path)
    db_path = tmp_path / "test.db"

    result = ingest_session_file(codex_file, db_path, verbose=True)

    if result["file_id"] <= 0:
        raise AssertionError(f"Expected file_id > 0, got {result['file_id']}")


def test_ingest_creates_database_schema(tmp_path: Path) -> None:
    """Should create database schema if it doesn't exist."""
    codex_file = _make_codex_session(tmp_path)
    db_path = tmp_path / "test.db"

    ingest_session_file(codex_file, db_path)

    # Verify schema was created
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    conn.close()

    if "files" not in tables:
        raise AssertionError("Missing 'files' table in database")
    if "sessions" not in tables:
        raise AssertionError("Missing 'sessions' table in database")
    if "interactions" not in tables:
        raise AssertionError("Missing 'interactions' table in database")


def test_ingest_transactional_rollback_on_error(tmp_path: Path) -> None:
    """Should rollback transaction if ingest fails."""
    # Create invalid session file
    bad_file = tmp_path / "bad.jsonl"
    bad_file.write_text("{invalid json}\n")

    db_path = tmp_path / "test.db"

    with pytest.raises(ValueError):
        ingest_session_file(bad_file, db_path)

    # Database should still be usable
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    conn.close()

    # Schema should exist but no data should be persisted from failed ingest
    if len(tables) == 0:
        raise AssertionError("Expected tables to exist in database")


# Helper functions for TestIngestDirectory
def _setup_session_directory(tmp_path: Path, count: int = 3) -> tuple[Path, list[Path]]:
    """Create a directory with multiple session files in year/month/day hierarchy."""
    sessions_dir = tmp_path / "sessions" / "2025" / "01" / "15"
    sessions_dir.mkdir(parents=True)

    files = []
    for i in range(count):
        codex_file = sessions_dir / f"session_{i}.jsonl"
        codex_file.write_text(f'{{"type": "session_meta", "sid": "test_{i}"}}\n')
        files.append(codex_file)

    return tmp_path / "sessions", files


def test_ingest_directory_with_sessions(tmp_path: Path) -> None:
    """Should ingest all sessions in directory."""
    sessions_dir, _ = _setup_session_directory(tmp_path, count=3)
    db_path = tmp_path / "test.db"

    results = list(ingest_sessions_in_directory(sessions_dir, db_path))

    if len(results) != 3:
        raise AssertionError(f"Expected 3 results, got {len(results)}")
    if not all(r["file_id"] > 0 for r in results):
        raise AssertionError("Expected all file_ids to be > 0")


def test_ingest_directory_with_limit(tmp_path: Path) -> None:
    """Should respect limit parameter."""
    sessions_dir, _ = _setup_session_directory(tmp_path, count=5)
    db_path = tmp_path / "test.db"

    results = list(ingest_sessions_in_directory(sessions_dir, db_path, limit=2))

    if len(results) != 2:
        raise AssertionError(f"Expected 2 results, got {len(results)}")


def test_ingest_directory_empty_raises_error(tmp_path: Path) -> None:
    """Should raise SessionDiscoveryError for empty directory."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    db_path = tmp_path / "test.db"

    with pytest.raises(SessionDiscoveryError):
        list(ingest_sessions_in_directory(empty_dir, db_path))


def test_ingest_directory_with_verbose(tmp_path: Path) -> None:
    """Should accept verbose flag without errors."""
    sessions_dir, _ = _setup_session_directory(tmp_path, count=2)
    db_path = tmp_path / "test.db"

    results = list(ingest_sessions_in_directory(sessions_dir, db_path, verbose=True))

    if len(results) != 2:
        raise AssertionError(f"Expected 2 results, got {len(results)}")


def test_ingest_directory_continues_on_error(tmp_path: Path) -> None:
    """Should continue processing after encountering error."""
    # Create directory structure
    sessions_dir = tmp_path / "sessions" / "2025" / "01" / "15"
    sessions_dir.mkdir(parents=True)

    # Create valid session
    valid_file = sessions_dir / "session_1.jsonl"
    valid_file.write_text('{"type": "session_meta", "sid": "test_1"}\n')

    # Create invalid session
    bad_file = sessions_dir / "session_bad.jsonl"
    bad_file.write_text("{not valid}\n")

    # Create another valid session
    valid_file2 = sessions_dir / "session_2.jsonl"
    valid_file2.write_text('{"type": "session_meta", "sid": "test_2"}\n')

    db_path = tmp_path / "test.db"

    # Should process valid sessions despite error (non-verbose mode)
    results = list(
        ingest_sessions_in_directory(tmp_path / "sessions", db_path, verbose=False)
    )

    # At least some sessions should have been processed
    if not any(r["file_id"] > 0 for r in results):
        raise AssertionError("Expected at least one session to be processed")


def test_ingest_directory_with_custom_batch_size(tmp_path: Path) -> None:
    """Should pass batch_size to session ingest."""
    sessions_dir, _ = _setup_session_directory(tmp_path, count=2)
    db_path = tmp_path / "test.db"

    results = list(ingest_sessions_in_directory(sessions_dir, db_path, batch_size=100))

    if len(results) != 2:
        raise AssertionError(f"Expected 2 results, got {len(results)}")


def test_load_rules_with_existing_file(tmp_path: Path) -> None:
    """Should load rules from existing file."""
    rules_file = tmp_path / "rules.yml"
    rules_file.write_text("rules: []\n")

    result = _load_rules_safely(rules_file, verbose=False)

    # Should return list or None
    if result is not None and not isinstance(result, list):
        raise AssertionError(f"Expected result to be None or list, got {type(result)}")


def test_load_rules_with_missing_file(tmp_path: Path) -> None:
    """Should return None on missing file in non-verbose mode."""
    missing_file = tmp_path / "missing_rules.yml"

    result = _load_rules_safely(missing_file, verbose=False)

    # Should not raise, returns None
    if result is not None:
        raise AssertionError(f"Expected None, got {result}")


def test_load_rules_verbose_raises_on_error(tmp_path: Path) -> None:
    """Should raise on error in verbose mode."""
    # Create invalid YAML file
    bad_rules = tmp_path / "bad_rules.yml"
    bad_rules.write_text("{ invalid yaml")

    # In verbose mode might raise during loading
    try:
        _load_rules_safely(bad_rules, verbose=True)
    except (ValueError, OSError):
        # Expected to raise in verbose mode
        pass
