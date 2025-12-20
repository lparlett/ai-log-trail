"""Validators that ensure event payloads meet ingest expectations.

Purpose: Validate Codex session events before ingest processing.
Author: Codex with Lauren Parlett
Date: 2025-10-30
AI-assisted: Generated with Codex (GPT-5).
"""

from __future__ import annotations

from typing import Any


class EventValidationError(ValueError):
    """Raised when a session event is malformed."""


def validate_event(event: Any) -> dict[str, Any]:
    """Return a normalized event dict if validation succeeds.

    Validation guards downstream handlers from unexpected shapes. Only JSON
    objects with a string ``type`` and (optional) dict ``payload`` are allowed.
    """

    normalized = _ensure_event_dict(event)
    normalized["payload"] = _normalize_payload(normalized.get("payload"))
    _validate_required_fields(normalized)
    _validate_timestamp(normalized.get("timestamp"))
    _normalize_metadata(normalized)
    return normalized


def _ensure_event_dict(event: Any) -> dict[str, Any]:
    """Validate top-level type and return a shallow copy."""

    if not isinstance(event, dict):
        raise EventValidationError("Event must be a JSON object.")
    return dict(event)


def _normalize_payload(payload: Any) -> dict[str, Any]:
    """Normalize payload field to a dict."""

    if payload is None:
        return {}
    if isinstance(payload, dict):
        return dict(payload)
    raise EventValidationError("Event 'payload' must be a JSON object.")


def _validate_required_fields(event: dict[str, Any]) -> None:
    """Ensure required 'type' field is present and valid."""

    event_type = event.get("type")
    if not isinstance(event_type, str) or not event_type.strip():
        raise EventValidationError("Event 'type' must be a non-empty string.")


def _validate_timestamp(timestamp: Any) -> None:
    """Ensure timestamp is string or None."""

    if timestamp is not None and not isinstance(timestamp, str):
        raise EventValidationError("Event 'timestamp' must be a string or null.")


def _normalize_metadata(event: dict[str, Any]) -> None:
    """Normalize metadata to a dict when present."""

    metadata = event.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        event["metadata"] = {}
