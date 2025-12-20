# Redaction Rules

"""Redaction rules authoring guide (AI-assisted by Codex GPT-5).

Purpose: How to define YAML/JSON rules, ordering/precedence, and defaults.
Author: Codex with Lauren Parlett
Date: 2025-11-27
Related code: src/services/redaction_rules.py
Related config: user/redactions.yml
"""

## Rule file location

- Rules live in a single file: `user/redactions.yml` (JSON also supported).
- The loader reads this file directly; if it is missing, ingest fails fast.

## Rule schema

Each entry in the YAML/JSON list supports:

- `id` (required, string): unique identifier for the rule.
- `type` (required): `regex`, `marker`, or `literal`.
  - `regex`: standard regex matching with optional `ignore_case`/`dotall`.
  - `marker`: regex that should include a named group `content`; when it matches,
    the entire marker (e.g., `[redact secret=abc]`) is replaced with the
    replacement text.
  - `literal`: exact string match; pattern text is escaped internally so regex
    metacharacters are treated literally.
- `pattern` (required): regex pattern for `regex` rules; marker regex for `marker`.
  - For `literal`, `pattern` is the exact text to match; it is escaped internally
  so special regex characters are treated literally.
- `scope` (optional, default `prompt`):
  - `prompt`: applies only to the user's prompt text before any structured
    redactions. It does **not** touch agent responses. Example: strip emails
    anywhere in the prompt body.
  - `field`: applies to specific structured fields (e.g., message bodies)
    when integrated into field-level processing. Example: target
    `raw_json.events[0].payload` without touching other fields. Field targets
    are determined by the structured schema (see `docs/schema_changes.md` and
    table definitions in `src/services/database.py`), so author rules based on
    known column/JSON paths.
  - `global`: applies across all content (raw and structured) when supported,
    covering both user prompts and agent responses.
- `replacement` (optional): replacement text; defaults to `<REDACTED>`.
- `enabled` (optional): defaults to `true` which turns on the rule for redaction.
- `reason` / `actor` (optional): metadata for provenance.
- `ignore_case` (optional): defaults to `true` where letter case is ignored during string search.
- `dotall` (optional): defaults to `false`. When `true`, the regex `.` will also
  match newline characters, which is helpful for multi-line markers or patterns.

## Marker behavior

For `marker` rules, the pattern must include a named group `content`. The engine
replaces that group including the surrounding brackets.
Example pattern: `\[redact\s+(?P<content>.+?)\]` turns
`[redact secret=abc]` into `<REDACTED>`.

## Ordering and precedence

- Rules are applied in file order. Earlier rules run first and can affect later
  matches.
- Manual redactions stored in the database still take precedence and should be
  applied **after** rule-based redactions when wiring the pipeline.

## Defaults

- `user/redactions.yml` is seeded with defaults for emails, bearer/API tokens,
  file paths, bracketed troubleshooting snippets, and `[redact ...]` markers.
- To disable a default, set `enabled: false` on that rule id.

## Examples

YAML regex rule:

```yaml
- id: emails
  type: regex
  pattern: "[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}"
  replacement: "<REDACTED:EMAIL>"
  reason: "privacy"
```

YAML marker rule:

```yaml
- id: inline_marker
  type: marker
  pattern: "\\[redact\\s+(?P<content>.+?)\\]"
  dotall: true
  replacement: "<REDACTED>"
```

JSON example:

```json
[
  {
    "id": "tokens",
    "type": "regex",
    "pattern": "bearer\\s+[A-Za-z0-9._-]{8,}",
    "replacement": "<REDACTED:TOKEN>"
  }
]
```

## Validation and errors

- Missing required fields (`id`, `type`, `pattern`) or unknown `type`/`scope`
  raise `ValueError` and stop ingest.
- Duplicate ids are rejected.
- Invalid/malformed regex patterns raise at load time to avoid silent skips.

## Summary reporting

- Application produces per-rule counts keyed by rule `id`; summaries can surface
  these counts for transparency during ingest/export.
