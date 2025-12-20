# System Architecture

## Overview

The AI Log Trail tool provides a complete pipeline for ingesting, normalizing, analyzing, and exporting AI agent session logs with privacy-preserving redaction controls.

```text
Session Files (JSONL)
        ↓
   [Parser] ← discovers sessions, loads events, groups by user message
        ↓
   [Ingest] ← validates, sanitizes, persists to SQLite
        ↓
   [SQLite] ← normalized tables + raw JSON audit trail
        ↓
   [Redaction] ← applies rules & manual redactions
        ↓
   [Export] ← generates reports, outputs redacted session data
```

---

## Core Components

### 1. Parser (`src/parsers/`)

**Responsibility:** Discover session files, load JSONL events, normalize structure, group by user message.

**Key modules:**

- `session_parser.py` — Discovers nested session directories, loads JSONL, validates event structure
- `handlers/db_utils.py` — Extract helpers (extract_session_details, extract_token_fields, etc.) and insert functions
- `handlers/event_handlers.py` — Process grouped events (handle_event_msg, handle_response_item_event, etc.)

**Flow:**

```python
iter_session_files(root)
  → for each JSONL file:
      load_session_events()  [validate, normalize]
      group_by_user_messages()  [collect events under each prompt]
      → [(prompt, [events]), ...]
```

**Output:** List of (user_prompt, event_list) tuples ready for database insertion.

---

### 2. Ingest (`src/services/ingest.py`)

**Responsibility:** Transform parsed sessions into SQLite rows, apply rule-based redactions, track errors and summaries.

**Key classes:**

- `SessionSummary` — Result metadata: file_id, prompt count, message types, errors, rule applications
- `ErrorSeverity` — Enum for WARNING (continue), ERROR (skip item), CRITICAL (stop file)
- `ProcessingError` — Structured error with severity, code, message, context

**Flow:**

```python
ingest_session_file(config, file_path)
  → load_session_events(file_path)  [parser step]
  → group_by_user_messages()  [parser step]
  → validate_event()  [ensure required fields, normalize payload]
  → sanitize_json()  [redact secrets per heuristics]
  → extract_session_details(raw_event)  [pull session metadata]
  → insert_session(SessionInsert(conn, ...))  [FK: file → session]
    → for each prompt:
        insert_prompt(PromptInsert(...))  [FK: file → prompt]
        → for each grouped event:
            handle_event_msg()  [event routing]
            → insert_token(), insert_turn_context(), etc.
            → apply_rules(redaction_rules, event)  [match patterns, track summaries]
  → return SessionSummary(file_id, prompt_count, errors, rule_summaries)
```

**Database transaction:** Single transaction per file (all-or-nothing on error).

---

### 3. Services (`src/services/`)

#### database.py — Connection & Schema

- `get_connection()` — Open SQLite connection with configured path
- `ensure_schema()` — Create/migrate tables on first use
- Schema: 12 tables (files, sessions, session_context, prompts, redaction_rules, redactions, messages, function_calls, etc.)

#### config.py — Configuration

- `DatabaseConfig` — SQLite path, conn string (Postgres)
- `SessionsConfig` — Sessions root directory, batch size, output paths
- `load_config()` — Parse user/config.toml, validate paths

#### validation.py — Event Validation

- `validate_event()` — Check required fields (type, timestamp, payload), normalize structure
- Per-event-type helpers: `_validate_required_fields()`, `_normalize_payload()`, etc.

#### sanitization.py — Secret Redaction (Pre-ingest)

- `sanitize_json()` — Recursively scan for secrets (API keys, tokens, email patterns)
- `_looks_like_secret()` — Heuristic detection (base64, env var patterns, etc.)
- **Note:** This is *automatic* per-event; rule-based redactions happen later in ingest

#### redaction_rules.py — Rule Management

- `RedactionRule` — Dataclass: type (regex/marker/literal), pattern, scope (field/prompt/global), replacement, options (ignore_case, dotall)
- `load_rules()` — Parse user/redactions.yml into RedactionRule instances
- `apply_rules()` — Iterate rules in order, match patterns, generate RuleSummary (count, fingerprint)
- `RuleSummary` — TypedDict: rule_id, count, replacement_text
- **Fingerprint:** SHA256 of normalized rule definition for deduplication across ingest/export

#### redactions.py — Redaction CRUD

- `RedactionRecord` — Dataclass: file_id, prompt_id, field_path, rule_id, reason, actor, applied_at
- `create_redaction()` — Insert manual redaction
- `list_redactions()` — Query by file/prompt/rule
- `update_redaction()` — Modify reason/actor metadata
- `delete_redaction()` — Remove redaction

#### postgres_schema.py — PostgreSQL Mirror

- Mirrors SQLite schema for migration target
- Tables, indexes, foreign keys, unique constraints

---

### 4. Models (`src/core/models/`)

**Responsibility:** Define data containers for agent configs, events, actions, messages.

#### base_types.py

- `AgentFeatures` — Feature flags (streaming, function_calls, tool_usage, context_window, file_edits)
- `AgentConfig` (ABC) — Base class for agent-specific configs (validate, to_dict, from_dict)

#### config_data.py

- `AgentConfigData` — Container for agent-specific config instances
- `AgentRegistry` — Map of agent types to their config classes

#### base_event.py

- `BaseEvent` (ABC) — Event interface (type, timestamp, payload, raw)

#### event_data.py

- Concrete event types (e.g., TokenCountEvent, TurnContextEvent) inheriting from BaseEvent

#### agents/codex/ — Agent-Specific Models

- `config.py` — CodexConfig: root_path, features, validation
- `action.py` — Action: type, name, arguments, timestamp
- `message.py` — CodexMessage: role, content, timestamp, metadata
- `parser.py` — CodexParser: Parses raw JSONL into Action/Message instances
- `errors.py` — ParserError, InvalidEventError for error tracking

---

### 5. CLI Entry Points (`cli/`)

#### ingest_session.py

- `main()` → `build_parser()` → parse args → `load_config()` → `ingest_sessions_in_directory()` or `ingest_session_file()`
- Flags: `--database`, `--session`, `--limit`, `--verbose`, `--debug`
- Output: Ingestion summary (prompts, tokens, errors) to stdout

#### group_session.py

- `main()` → load earliest session → `describe_event()` per event → render to console or file
- Flags: `-o` (output path), `--list` (list sessions)
- Output: Human-readable grouped report (Markdown or text)

#### export_session.py

- `main()` → query redactions from DB → apply to raw session JSON → output filtered JSONL or CSV
- Flags: `--session`, `--file`, `--format` (jsonl/csv)
- Output: Redacted session export

#### redaction_rules.py

- `main()` → load/validate/sync rules from user/redactions.yml
- Subcommands: list, validate, sync-to-db
- Flags: `--rules` (path), `--apply` (dry-run mode)

#### migrate_sqlite_to_postgres.py

- `main()` → connect to Postgres → create schema → copy SQLite tables → verify counts
- Flags: `--dry-run`, `--target` (Postgres connection string)

---

## Data Flow: Key Operations

### Operation 1: Ingest Session

```text
Command: python -m cli.ingest_session --session /path/to/session.jsonl

1. Parse args → resolve config → open SQLite connection
2. Parser:
   - Load JSONL lines
   - Validate each event (required fields, type, payload)
   - Normalize structure (payload dict, metadata dict)
   - Group events by user_message_id
   → [GroupedPrompt(user_msg, [events]), ...]
3. Ingest:
   - Begin transaction
   - insert_session() → sessions.id
   - For each prompt:
     - insert_prompt() → prompts.id
     - For each event:
       - Sanitize (redact auto-detected secrets)
       - Route: is it token_count? turn_context? response_item?
         - insert_token() → token_messages
         - insert_turn_context() → turn_context_messages
         - insert_function_call() → function_calls
         - insert_agent_reasoning() → agent_reasoning_messages
         - insert_function_plan() → function_plan_messages
       - apply_rules(redaction_rules, event) → match patterns → create_redaction() for matches
   - Commit transaction
   - Return SessionSummary(file_id, prompts, tokens, errors, {rule_id: count})
4. Output: Print summary, persist to DB
```

**Error Handling:**

- Validation error → ErrorSeverity.ERROR → skip event, continue
- SQL error → ErrorSeverity.CRITICAL → rollback, stop file, report
- Parse error → catch, log, increment error count

---

### Operation 2: Group & Display Session

```text
Command: python -m cli.group_session

1. Config: Load user/config.toml
2. Database: get_connection() → query earliest session
3. Query: SELECT prompts, messages, function_calls... for session
4. Render:
   - For each prompt:
     - Print user message
     - Print grouped events under prompt:
       - Token usage: "4200 / 4000 limit"
       - Reasoning: "[agent thinking...]"
       - Function calls: "[tool_use: name=... args=...]"
   - Apply shorten() for long payloads
5. Output: Write to console or [outputs].reports_dir
```

---

### Operation 3: Export with Redactions

```text
Command: python -m cli.export_session --session <session_id> --format jsonl

1. Config: Load rules from user/redactions.yml
2. Database:
   - Query redactions for this session
   - Query session raw JSON
3. Apply Redactions:
   - For each redaction record:
     - field_path = "payload.arguments"
     - Load raw JSON for prompt
     - Navigate to field_path, replace text
     - Store redacted version
4. Output:
   - JSONL format: one event per line (redacted)
   - CSV format: rows with prompt, event, action taken
```

---

## Key Algorithms & Patterns

### Redaction Rule Matching

```python
for each rule in rules:
  if rule.enabled and event_matches_scope(rule.scope, field_path):
    compiled_pattern = rule.compiled  [cached re.Pattern]
    matches = compiled_pattern.findall(field_value)
    if matches:
      for match in matches:
        replacement = rule.effective_replacement  [or global default]
        field_value = field_value.replace(match, replacement)
      RuleSummary.count += 1
      RedactionRecord(rule_id, fingerprint=rule.fingerprint, ...)
```

**Order Matters:** Rules applied in YAML file order; later rules can re-match earlier replacements.

**Deduplication:** Fingerprint (SHA256 of rule + replacement) prevents double-applying same rule in export.

---

### Session Discovery

```text
iter_session_files(root_path):
  for year in root_path/YYYY:
    for month in year/MM:
      for day in month/DD:
        for file in day/*.jsonl:
          yield file  [in chronological order]
```

Preserves Codex's nested directory structure; enables batch processing by date range.

---

## Database Schema (Simplified)

```text
files
  ├─ id (PK)
  ├─ path (UNIQUE)
  └─ ingested_at

sessions (FK: files.id)
  ├─ id (PK)
  ├─ file_id (UNIQUE FK)
  ├─ session_id
  └─ raw_json

session_context (1:1 with sessions)
  ├─ id (PK)
  ├─ session_id (UNIQUE FK)
  ├─ cwd, approval_policy, sandbox_mode, network_access

prompts (FK: files.id)
  ├─ id (PK)
  ├─ file_id (FK)
  ├─ prompt_index
  ├─ message, active_file, open_tabs
  └─ raw_json

token_messages, turn_context_messages, agent_reasoning_messages, ...
  ├─ id (PK)
  ├─ prompt_id (FK)
  ├─ timestamp, payload fields
  └─ raw_json

function_calls (FK: prompt_id)
  ├─ id (PK)
  ├─ call_timestamp, output_timestamp
  ├─ name, call_id, arguments, output
  └─ raw_call_json, raw_output_json

redaction_rules
  ├─ id (PK = rule name)
  ├─ type (regex|marker|literal)
  ├─ pattern, scope (field|prompt|global)
  ├─ replacement_text, rule_fingerprint
  ├─ enabled, reason, actor
  └─ created_at, updated_at

redactions (append-only audit log)
  ├─ id (PK)
  ├─ file_id (FK, nullable)
  ├─ prompt_id (FK, nullable)
  ├─ rule_id (FK redaction_rules, nullable)
  ├─ field_path, rule_fingerprint
  ├─ reason, actor, applied_at
  └─ UNIQUE(file_id, prompt_id, field_path, rule_id, rule_fingerprint)
```

**Invariant:** Every `prompts.file_id` has a corresponding `files.id` (cascading delete on file removal).

---

## Configuration & Extensibility

### User Configuration (`user/config.toml`)

```toml
[sessions]
root = "C:/Users/me/.codex/sessions"  # Where to find JSONL files

[ingest]
db_path = "local.db"                  # SQLite destination
batch_size = 1000                     # Events per transaction

[outputs]
reports_dir = "reports/"              # Where group_session writes

[postgres]
connection_string = "postgresql://..."  # Optional: for migration
```

### Extending to New Agents

To add support for a new agent (e.g., Cursor, Qwen):

1. Create `src/agents/cursor/` with:
   - `config.py` — CursorConfig inheriting from AgentConfig
   - `parser.py` — CursorParser inheriting from BaseParser
   - `message.py`, `action.py` — Cursor-specific event models

2. Register in `src/core/models/config_data.py`:

    ```python
    AGENT_REGISTRY = {
      "codex": CodexConfig,
      "cursor": CursorConfig,
    # ...
    }
    ```

3. Update parser discovery in `src/parsers/session_parser.py` to instantiate CursorParser for Cursor logs.

4. Tests: Add `tests/agents/cursor/` mirroring Codex structure.

---

## Testing Strategy

- **Unit tests** (`tests/services/`, `tests/core/`) — Test validators, redaction logic, config loading in isolation
- **Integration tests** (`tests/parsers/`, `tests/cli/`) — Test full pipelines (parse → ingest → query) with temp SQLite
- **Fixtures** (`tests/fixtures/`) — Sample session logs, expected outputs for regression testing
- **Coverage:** Aim for 80%+ line coverage, 100% on critical paths (validation, redaction, ingest)

---

## Error Handling

All errors are captured and reported:

```python
ProcessingError(
    severity=ErrorSeverity.WARNING,      # Continue
    code="invalid_event",
    message="Missing 'type' field",
    file_path="session.jsonl",
    line_number=42,
)
```

Severity levels:

- **WARNING** — Skip event, continue processing file
- **ERROR** — Skip item/batch, continue file (e.g., SQL constraint violation)
- **CRITICAL** — Stop processing file, rollback transaction (e.g., corrupted JSONL header)

Errors are collected in `SessionSummary.errors` and printed to user.

---

## Performance Considerations

1. **Batching** — Ingest processes events in configurable batches (default 1000); reduces memory footprint
2. **Indexing** — Indexes on (file_id, prompt_id, rule_id) for redaction queries
3. **Caching** — Compiled regex patterns cached in RedactionRule instances
4. **Raw JSON Storage** — Preserved in *_json columns for audit trail without re-parsing

---

## Security & Privacy

- **No secrets in code** — All paths, API keys in user/config.toml (gitignored)
- **Parameterized SQL** — All queries use ? placeholders; no string concatenation
- **Automatic sanitization** — Secrets auto-redacted during ingest (heuristic-based)
- **Manual redaction** — User can create/modify redactions; immutable audit log
- **Rule fingerprints** — Track which rule was applied; enable rollback/audit

---

## Next Steps

Refer to:

- [`docs/cli.md`](cli.md) — CLI command reference & examples
- [`docs/schema.md`](schema.md) — Detailed schema diagram
- [`AGENTS.md`](../AGENTS.md) — Coding standards, testing conventions
- [`ROADMAP.md`](../ROADMAP.md) — Feature roadmap & milestones
