"""Utilities that redact sensitive values from JSON-compatible structures.

Purpose: Sanitize AI agent session JSON payloads before persistence.
Author: Codex with Lauren Parlett
Date: 2025-10-30
AI-assisted: Generated with Codex (GPT-5) and Claude Haiku 4.5.
"""

from __future__ import annotations

from typing import Any


REDACTED = "[redacted]"

SENSITIVE_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "client_secret",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "token_secret",
}

SENSITIVE_PREFIXES = ("sk-", "rk-", "pk_", "akia")
SENSITIVE_MARKERS = ("-----begin",)


def sanitize_json(data: Any) -> Any:
    """Return a sanitized copy of ``data`` with secrets redacted.

    Sensitive keys are replaced with ``[redacted]``. String heuristics catch
    common API tokens or private key blocks so we never persist raw secrets.
    """

    return _sanitize(data)


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            sanitized[key] = _sanitize_dict_value(key, item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize(item) for item in value)
    return _sanitize_scalar(value)


def _sanitize_dict_value(key: Any, value: Any) -> Any:
    key_text = str(key).casefold()
    if key_text in SENSITIVE_KEYS:
        return _redact(value)
    return _sanitize(value)


def _sanitize_scalar(value: Any) -> Any:
    if isinstance(value, str) and _looks_like_secret(value):
        return REDACTED
    return value


def _looks_like_secret(text: str) -> bool:
    normalized = text.strip()
    lowered = normalized.casefold()
    if lowered.startswith("bearer "):
        return True
    for marker in SENSITIVE_MARKERS:
        if marker in lowered:
            return True
    for prefix in SENSITIVE_PREFIXES:
        if lowered.startswith(prefix):
            return True
    if len(normalized) >= 64 and all(
        char.isalnum() or char in "-_=" for char in normalized
    ):
        return True
    return False


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    if value is None:
        return None
    return REDACTED
