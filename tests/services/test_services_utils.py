# pylint: disable=duplicate-code
"""Tests for validation and sanitization helpers."""
from __future__ import annotations

import unittest

import pytest

from src.services.validation import validate_event, EventValidationError
from src.services.sanitization import sanitize_json, REDACTED

TC = unittest.TestCase()


def test_validate_event_normalizes_payload() -> None:
    """validate_event should coerce payload to dict and preserve fields."""
    event = {"type": "event_msg", "timestamp": "2025-10-31T10:00:00Z"}
    normalized = validate_event(event)
    TC.assertEqual(normalized["payload"], {})
    TC.assertEqual(normalized["type"], "event_msg")


@pytest.mark.parametrize(
    "bad_event",
    [
        "not-a-dict",
        {"type": "", "timestamp": "x"},
        {"type": "event_msg", "timestamp": 1},
        {"type": "event_msg", "payload": "not-dict"},
    ],
)
def test_validate_event_rejects_bad_inputs(bad_event: object) -> None:
    """validate_event should raise EventValidationError on invalid shapes."""
    with pytest.raises(EventValidationError):
        validate_event(bad_event)


def test_sanitize_json_redacts_sensitive_values() -> None:
    """sanitize_json should redact keys and secret-looking strings."""
    payload = {
        "access_token": "secret-token",
        "nested": {"password": "p@ss"},
        "tuple": ("apikey",),
        "string_secret": "sk-abcdef1234567890",
        "safe": "hello",
    }
    sanitized = sanitize_json(payload)
    TC.assertEqual(sanitized["access_token"], REDACTED)
    TC.assertEqual(sanitized["nested"]["password"], REDACTED)
    TC.assertEqual(sanitized["string_secret"], REDACTED)
    TC.assertEqual(sanitized["safe"], "hello")


def test_sanitize_json_handles_false_negatives_and_casing() -> None:
    """Sanitization should catch heuristics and case-insensitive sensitive keys."""

    payload = {
        "Authorization": "Bearer abc123",
        "api_key_backup": "short-token-123",
        "unicode_secret": "sk-ßeta-secret",
        "custom": "uuidlike-1234-5678-9012-3456",
    }
    sanitized = sanitize_json(payload)
    TC.assertEqual(sanitized["Authorization"], REDACTED)
    TC.assertEqual(sanitized["api_key_backup"], "short-token-123")
    TC.assertEqual(sanitized["unicode_secret"], REDACTED)
    TC.assertEqual(sanitized["custom"], "uuidlike-1234-5678-9012-3456")


def test_sanitize_json_with_missing_markers() -> None:
    """Secrets that don't match heuristics should remain unchanged."""

    payload = {"note": "short-token", "uuid": "12345678-1234-1234-1234-123456789012"}
    sanitized = sanitize_json(payload)
    TC.assertEqual(sanitized, payload)


def test_validate_event_defaults_payload_and_metadata() -> None:
    """validate_event should default payload/metadata when missing."""

    event = {"type": "event_msg", "timestamp": "t1", "metadata": None}
    normalized = validate_event(event)
    TC.assertEqual(normalized["payload"], {})
    TC.assertIsNone(normalized.get("metadata"))


def test_validate_event_roundtrip_structure() -> None:
    """validate_event should preserve fields and allow revalidation."""

    event = {
        "type": "event_msg",
        "timestamp": "t2",
        "payload": {"type": "agent_message", "text": "hi"},
        "metadata": {"source": "cli"},
    }
    normalized = validate_event(event)
    normalized_again = validate_event(normalized)
    TC.assertEqual(normalized_again["metadata"], {"source": "cli"})
    TC.assertEqual(normalized_again["payload"]["type"], "agent_message")


# ===== Additional tests for sanitization.py branch coverage =====


def test_sanitize_json_with_dict_types() -> None:
    """Sanitize should handle nested dicts with sensitive keys."""
    payload = {
        "outer": {
            "token_secret": "sk-12345",
            "safe_nested": "value",
            "deeper": {
                "authorization": "Bearer token123",
                "normal": "data",
            },
        }
    }
    sanitized = sanitize_json(payload)
    TC.assertEqual(sanitized["outer"]["token_secret"], REDACTED)
    TC.assertEqual(sanitized["outer"]["safe_nested"], "value")
    TC.assertEqual(sanitized["outer"]["deeper"]["authorization"], REDACTED)
    TC.assertEqual(sanitized["outer"]["deeper"]["normal"], "data")


def test_sanitize_json_with_list_types() -> None:
    """Sanitize should recursively process lists."""
    payload = {
        "tokens": [
            "sk-secret-token",
            "normal-value",
            {"api_key": "should-be-redacted"},
        ]
    }
    sanitized = sanitize_json(payload)
    TC.assertEqual(sanitized["tokens"][0], REDACTED)
    TC.assertEqual(sanitized["tokens"][1], "normal-value")
    TC.assertEqual(sanitized["tokens"][2]["api_key"], REDACTED)


def test_sanitize_json_with_tuple_types() -> None:
    """Sanitize should handle tuples (converting to tuple in output)."""
    payload = {"tuple_data": ("sk-secret", "normal", ("nested", "secret-pk_liketoken"))}
    sanitized = sanitize_json(payload)
    TC.assertIsInstance(sanitized["tuple_data"], tuple)
    TC.assertEqual(sanitized["tuple_data"][0], REDACTED)
    TC.assertEqual(sanitized["tuple_data"][1], "normal")
    TC.assertIsInstance(sanitized["tuple_data"][2], tuple)


def test_sanitize_json_long_alphanumeric_secret() -> None:
    """Strings >= 64 chars with only alnum/-/_/= should be redacted."""
    payload = {
        "long_token": "a" * 64,
        "long_with_dash": "a-b-c-d-e-f-g-h-" * 6,  # 96 chars with dashes
        "not_long_enough": "a" * 63,
        "not_alnum": "a" * 64 + "@",  # Has special char
    }
    sanitized = sanitize_json(payload)
    TC.assertEqual(sanitized["long_token"], REDACTED)
    TC.assertEqual(sanitized["long_with_dash"], REDACTED)
    TC.assertNotEqual(sanitized["not_long_enough"], REDACTED)
    TC.assertNotEqual(sanitized["not_alnum"], REDACTED)


def test_sanitize_json_bearer_token() -> None:
    """Bearer tokens should be redacted."""
    payload = {
        "auth1": "Bearer token123456",
        "auth2": "BEARER differenttoken",
        "safe": "Bearing gifts",
    }
    sanitized = sanitize_json(payload)
    TC.assertEqual(sanitized["auth1"], REDACTED)
    TC.assertEqual(sanitized["auth2"], REDACTED)
    TC.assertNotEqual(sanitized["safe"], REDACTED)


def test_sanitize_json_private_key_markers() -> None:
    """PEM-style private key markers should trigger redaction."""
    payload = {
        "key1": "-----BEGIN PRIVATE KEY-----\ndata\n-----END PRIVATE KEY-----",
        "key2": "-----begin rsa private key-----\ndata",
        "safe": "to begin a story",
    }
    sanitized = sanitize_json(payload)
    TC.assertEqual(sanitized["key1"], REDACTED)
    TC.assertEqual(sanitized["key2"], REDACTED)
    TC.assertNotEqual(sanitized["safe"], REDACTED)


def test_sanitize_json_sensitive_prefixes() -> None:
    """API tokens with sensitive prefixes should be redacted."""
    payload = {
        "stripe": "sk-test-1234567890",
        "openai": "sk-abc1234def5678",
        "aws": "AKIA1234567890ABCDEF",
        "rk_token": "rk-live-secret",
        "pk_token": "pk_live_secret123456789",
        "safe": "sk_manual-value",  # Underscore, not dash
    }
    sanitized = sanitize_json(payload)
    TC.assertEqual(sanitized["stripe"], REDACTED)
    TC.assertEqual(sanitized["openai"], REDACTED)
    TC.assertEqual(sanitized["aws"], REDACTED)
    TC.assertEqual(sanitized["rk_token"], REDACTED)
    TC.assertEqual(sanitized["pk_token"], REDACTED)
    TC.assertNotEqual(sanitized["safe"], REDACTED)


def test_sanitize_json_redact_nested_structures() -> None:
    """The _redact function should handle nested dicts, lists, tuples."""
    # This tests the _redact branch handling different types
    # _redact preserves structure but redacts all scalar values within it
    payload = {
        "api_key": {
            "nested_dict": {"password": "secret"},
            "nested_list": ["item", {"authorization": "Bearer token"}],
            "nested_tuple": ("safe", ("nested",)),
            "none_value": None,
        }
    }
    sanitized = sanitize_json(payload)
    # api_key is in SENSITIVE_KEYS, so _redact is called
    # _redact preserves structure but redacts string values
    TC.assertIsInstance(sanitized["api_key"], dict)
    TC.assertEqual(sanitized["api_key"]["nested_dict"]["password"], REDACTED)
    TC.assertEqual(sanitized["api_key"]["nested_list"][0], REDACTED)
    TC.assertEqual(sanitized["api_key"]["nested_list"][1]["authorization"], REDACTED)
    TC.assertEqual(sanitized["api_key"]["nested_tuple"][0], REDACTED)
    TC.assertIsNone(sanitized["api_key"]["none_value"])


def test_sanitize_json_case_insensitive_sensitive_keys() -> None:
    """Sensitive key matching should be case-insensitive."""
    payload = {
        "PASSWORD": "p@ss",
        "PassWord": "secret",
        "password": "pass123",
        "Client_Secret": "csrf-token",
        "PRIVATE_KEY": "rsa-key",
    }
    sanitized = sanitize_json(payload)
    TC.assertEqual(sanitized["PASSWORD"], REDACTED)
    TC.assertEqual(sanitized["PassWord"], REDACTED)
    TC.assertEqual(sanitized["password"], REDACTED)
    TC.assertEqual(sanitized["Client_Secret"], REDACTED)
    TC.assertEqual(sanitized["PRIVATE_KEY"], REDACTED)


def test_sanitize_json_with_whitespace_secret_detection() -> None:
    """Secret detection should work with leading/trailing whitespace."""
    payload = {
        "token1": "  sk-secrettoken  ",
        "token2": "\nBearer token\t",
        "token3": "  -----BEGIN PRIVATE KEY-----\n",
    }
    sanitized = sanitize_json(payload)
    TC.assertEqual(sanitized["token1"], REDACTED)
    TC.assertEqual(sanitized["token2"], REDACTED)
    TC.assertEqual(sanitized["token3"], REDACTED)


def test_sanitize_json_empty_structures() -> None:
    """Empty dicts, lists, tuples should be preserved."""
    payload = {
        "empty_dict": {},
        "empty_list": [],
        "empty_tuple": (),
        "mixed": {"nested_empty": {}, "nested_list_empty": []},
    }
    sanitized = sanitize_json(payload)
    TC.assertEqual(sanitized["empty_dict"], {})
    TC.assertEqual(sanitized["empty_list"], [])
    TC.assertEqual(sanitized["empty_tuple"], ())
    TC.assertEqual(sanitized["mixed"]["nested_empty"], {})


def test_sanitize_json_non_string_scalar_values() -> None:
    """Non-string scalar values should pass through unchanged."""
    payload = {
        "int_value": 42,
        "float_value": 3.14,
        "bool_value": True,
        "none_value": None,
        "int_in_list": [1, 2, 3],
        "mixed_list": [1, "sk-secret", None, True],
    }
    sanitized = sanitize_json(payload)
    TC.assertEqual(sanitized["int_value"], 42)
    TC.assertEqual(sanitized["float_value"], 3.14)
    TC.assertEqual(sanitized["bool_value"], True)
    TC.assertIsNone(sanitized["none_value"])
    TC.assertEqual(sanitized["int_in_list"], [1, 2, 3])
    TC.assertEqual(sanitized["mixed_list"][1], REDACTED)
