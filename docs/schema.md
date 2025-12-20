# Database Schema Reference

## Schema Overview

The AI Log Trail SQLite schema is normalized to 2NF (Second Normal Form) with audit trails and redundancy for transparency.

---

## Table Relationships

```text
┌─────────────────────────────────────────────────────────────────┐
│                        files (root anchor)                       │
│  id (PK) | path (UNIQUE) | ingested_at                          │
└─────────────────────────────────────────────────────────────────┘
         ↓                           ↓
         ↓                           ↓
    ┌─────────────────────┐   ┌──────────────────────────────┐
    │    sessions         │   │    prompts                   │
    │  1:1 with file      │   │  many:1 with file            │
    │                     │   │                              │
    │ id | file_id (FK)   │   │ id | file_id (FK)            │
    │    | session_id     │   │    | prompt_index            │
    │    | raw_json       │   │    | message (user input)    │
    └─────────────────────┘   │    | active_file             │
           ↓                   │    | open_tabs               │
           ↓                   │    | raw_json                │
    ┌──────────────────┐      └──────────────────────────────┘
    │ session_context  │              ↓
    │ 1:1 with session │              ↓ (many:1)
    │                  │      ┌──────────────────────┐
    │ id               │      │ *_messages, *_calls  │
    │ session_id (FK)  │      │ (token, turn_context,│
    │ cwd              │      │  agent_reasoning,    │
    │ approval_policy  │      │  function_plan,      │
    │ sandbox_mode     │      │  function_calls)     │
    │ network_access   │      │                      │
    └──────────────────┘      │ id | prompt_id (FK) │
                              │    | timestamp       │
                              │    | payload fields  │
                              │    | raw_json        │
                              └──────────────────────┘
```

**Redaction subsystem (independent):**

```text
┌──────────────────────────────────┐
│    redaction_rules (config)      │
│  id (name/PK) | type             │
│  | pattern | scope               │
│  | replacement_text              │
│  | rule_fingerprint              │
│  | enabled | reason | actor      │
│  | created_at | updated_at       │
└──────────────────────────────────┘
            ↑
            ↑ FK: rule_id
            ↑
┌──────────────────────────────────────────────────┐
│        redactions (audit log, append-only)       │
│  id (PK) | file_id (FK, nullable)                │
│          | prompt_id (FK, nullable)              │
│          | rule_id (FK, nullable)                │
│          | field_path                            │
│          | rule_fingerprint                      │
│          | reason | actor | applied_at           │
│  UNIQUE(file_id, prompt_id, field_path,          │
│         rule_id, rule_fingerprint)               │
└──────────────────────────────────────────────────┘
```

---

## Table Definitions

### files

**Purpose:** Root table tracking ingested session files.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `id` | INTEGER | PK, AUTOINCREMENT | Stable row identifier |
| `path` | TEXT | NOT NULL, UNIQUE | Full path to JSONL file; enables deduplication |
| `ingested_at` | TEXT | NOT NULL, DEFAULT CURRENT_TIMESTAMP | ISO-8601 timestamp |

**Indexes:**

- PK on `id`
- UNIQUE on `path` (deduplication)

**Cascading:** All child tables (sessions, prompts) cascade delete on file removal.

---

### sessions

**Purpose:** Session-level metadata captured from first event in file.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `id` | INTEGER | PK, AUTOINCREMENT | Stable row identifier |
| `file_id` | INTEGER | NOT NULL, UNIQUE FK → files | One session per file |
| `session_id` | TEXT | nullable | AI agent session UUID (if present in raw data) |
| `session_timestamp` | TEXT | nullable | ISO-8601 when session started |
| `raw_json` | TEXT | nullable | Full raw session metadata for audit |

**Relationship:** 1:1 with files (UNIQUE FK).

**Related table:** `session_context` (1:1, contains environment/execution context).

---

### session_context

**Purpose:** Execution environment and approval context for a session.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `id` | INTEGER | PK, AUTOINCREMENT | Stable row identifier |
| `session_id` | INTEGER | NOT NULL, UNIQUE FK → sessions | Links to session |
| `cwd` | TEXT | nullable | Current working directory at start |
| `approval_policy` | TEXT | nullable | Sandbox approval rules (e.g., "user_approval") |
| `sandbox_mode` | TEXT | nullable | Sandbox state (e.g., "enabled", "disabled") |
| `network_access` | TEXT | nullable | Network policy (e.g., "restricted", "full") |
| `created_at` | TEXT | NOT NULL, DEFAULT CURRENT_TIMESTAMP | Insert timestamp |

**Relationship:** 1:1 with sessions (UNIQUE FK); split from `sessions` table to achieve 2NF.

---

### prompts

**Purpose:** User prompts (message turns) within a session.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `id` | INTEGER | PK, AUTOINCREMENT | Stable row identifier |
| `file_id` | INTEGER | NOT NULL FK → files | Links to source file (for denorm. convenience) |
| `prompt_index` | INTEGER | NOT NULL | 0-based index of prompt in session |
| `timestamp` | TEXT | nullable | ISO-8601 when user sent prompt |
| `message` | TEXT | nullable | Full user prompt text |
| `active_file` | TEXT | nullable | File open in editor when prompt sent |
| `open_tabs` | TEXT | nullable | List of open files (JSON or comma-separated) |
| `my_request` | TEXT | nullable | Extracted/normalized request (if computed) |
| `raw_json` | TEXT | nullable | Full raw prompt event for audit |

**Indexes:**

- PK on `id`
- FK on `file_id`

**Child tables:** All message/call tables (token_messages, turn_context_messages, etc.) foreign key to `prompts.id`.

---

### Message Tables (token_messages, turn_context_messages, agent_reasoning_messages, function_plan_messages)

**Purpose:** Event-level messages grouped under prompts.

Example: token_messages

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `id` | INTEGER | PK, AUTOINCREMENT | Stable row identifier |
| `prompt_id` | INTEGER | NOT NULL FK → prompts | Parent prompt |
| `timestamp` | TEXT | nullable | ISO-8601 when token event occurred |
| `prompt_tokens` | INTEGER | nullable | Tokens in user input |
| `completion_tokens` | INTEGER | nullable | Tokens in agent output |
| `total_tokens` | INTEGER | nullable | Sum of above |
| `raw_json` | TEXT | nullable | Full raw event for audit |

**Similar tables:**

- **turn_context_messages** — cwd, approval_policy, sandbox_mode, network_access, writable_roots (turn-specific context changes)
- **agent_reasoning_messages** — source, text (agent thinking/planning)
- **function_plan_messages** — name, arguments (update_plan function calls)

**Indexes:** FK on `prompt_id` for efficient grouping.

---

### function_calls

**Purpose:** Standalone function/tool calls with input and output.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `id` | INTEGER | PK, AUTOINCREMENT | Stable row identifier |
| `prompt_id` | INTEGER | NOT NULL FK → prompts | Parent prompt |
| `call_timestamp` | TEXT | nullable | ISO-8601 when call was made |
| `output_timestamp` | TEXT | nullable | ISO-8601 when output was received |
| `name` | TEXT | nullable | Function/tool name (e.g., "code_edit") |
| `call_id` | TEXT | nullable | Unique call identifier |
| `arguments` | TEXT | nullable | Function arguments (JSON) |
| `output` | TEXT | nullable | Return value (JSON or text) |
| `raw_call_json` | TEXT | nullable | Full raw call event |
| `raw_output_json` | TEXT | nullable | Full raw output event |

**Indexes:** FK on `prompt_id`.

---

### redaction_rules

**Purpose:** Library of redaction patterns (regex, marker, literal) applied during ingest/export.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `id` | TEXT | PK | Rule name (e.g., "email_regex") |
| `type` | TEXT | NOT NULL, CHECK in ('regex', 'marker', 'literal') | Pattern type |
| `pattern` | TEXT | NOT NULL | Regex or literal string to match |
| `scope` | TEXT | NOT NULL, DEFAULT 'prompt', CHECK in ('prompt', 'field', 'global') | Where rule applies |
| `replacement_text` | TEXT | NOT NULL | What to replace matches with |
| `rule_fingerprint` | TEXT | NOT NULL | SHA256 of normalized rule (for dedup) |
| `enabled` | INTEGER | NOT NULL, DEFAULT 1 | 0 = disabled, 1 = enabled |
| `reason` | TEXT | nullable | Why this rule exists (documentation) |
| `actor` | TEXT | nullable | Who created/modified (e.g., "user:alice") |
| `created_at` | TEXT | NOT NULL, DEFAULT CURRENT_TIMESTAMP | Insert timestamp |
| `updated_at` | TEXT | nullable | Last modification timestamp |

**Usage:** Sourced from user/redactions.yml; synced to DB via CLI.

---

### redactions

**Purpose:** Audit log of applied redactions; append-only with deduplication support.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `id` | INTEGER | PK, AUTOINCREMENT | Stable row identifier |
| `file_id` | INTEGER | nullable FK → files | Which session file was redacted (or null for global) |
| `prompt_id` | INTEGER | nullable FK → prompts | Which prompt (or null if file/global scope) |
| `rule_id` | TEXT | nullable FK → redaction_rules | Which rule was applied (or null if manual) |
| `rule_fingerprint` | TEXT | NOT NULL | Immutable fingerprint of applied rule (audit) |
| `field_path` | TEXT | nullable | JSONPath to redacted field (e.g., "payload.arguments") |
| `reason` | TEXT | nullable | Why redaction was applied (user annotation) |
| `actor` | TEXT | nullable | Who applied (e.g., "system:ingest", "user:bob") |
| `applied_at` | TEXT | NOT NULL | ISO-8601 when redaction was applied |
| **UNIQUE** | | (file_id, prompt_id, field_path, rule_id, rule_fingerprint) | Deduplication: prevent re-applying same rule |

**Relationship:** FK to redaction_rules (nullable for manual redactions).

**Append-only:** Redactions are never deleted; only new ones added. Enables audit trail.

---

## Key Design Decisions

### 1. Normalized vs. Denormalized

**Normalized (2NF):**

- `session_context` split from `sessions` to avoid repeating context columns across prompts
- `redaction_rules` split from `redactions` to store rule definitions once

**Denormalized (for convenience):**

- `file_id` stored in `prompts` (redundant with sessions→files) for direct prompt→file queries
- `raw_json` preserved in every table for audit trail without re-parsing

**Rationale:** Balance query performance (direct file_id in prompts) with storage efficiency and auditability.

### 2. Raw JSON Audit Trail

Every table has a `raw_json` column (or `raw_call_json`, `raw_output_json` for function_calls) preserving the original parsed event. This enables:

- Debugging parsing issues
- Reprocessing without re-parsing JSONL
- Transparency (users can verify what was stored)

### 3. Cascading Deletes

```sql
FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
```

Removing a file cascades to:

- sessions, session_context
- prompts
- All message and call child rows
- redactions (file-scoped)

**Rationale:** Maintains referential integrity when files are removed.

### 4. Unique Redaction Index

```sql
UNIQUE (file_id, prompt_id, field_path, rule_id, rule_fingerprint)
```

Prevents the same rule from being applied twice to the same field. Used with `INSERT OR IGNORE` during ingest+export to safely idempotent apply rules.

### 5. Rule Fingerprint

SHA256 hash of normalized rule definition (pattern, scope, replacement, options). Enables:

- Detecting if rule definition changed (soft-disable old applications)
- Auditing which version of a rule was applied
- Deduplication across ingest and export phases

---

## Indexes

**Primary Keys (implicit):**

- `files.id`
- `sessions.id`
- `prompts.id`
- `*_messages.id`
- `function_calls.id`
- `redaction_rules.id`
- `redactions.id`

**Foreign Keys:**

- `sessions.file_id` (UNIQUE: 1:1 with files)
- `session_context.session_id` (UNIQUE: 1:1 with sessions)
- `prompts.file_id` (many:1)
- All message tables: `prompt_id` (many:1)
- `function_calls.prompt_id` (many:1)
- `redactions.rule_id` (many:1, nullable)
- `redactions.file_id`, `redactions.prompt_id` (for scope filtering)

**Unique Constraints:**

- `files.path` (deduplication)
- `redactions` composite (file_id, prompt_id, field_path, rule_id, rule_fingerprint)

---

## Access Patterns

### Common Queries

**Get all prompts for a session:**

```sql
SELECT p.* FROM prompts p
WHERE p.file_id = ? ORDER BY p.prompt_index;
```

**Get all events for a prompt:**

```sql
SELECT
  tm.* as token_event,
  tcm.* as turn_context_event,
  arm.* as reasoning_event,
  fc.* as function_call
FROM prompts p
LEFT JOIN token_messages tm ON tm.prompt_id = p.id
LEFT JOIN turn_context_messages tcm ON tcm.prompt_id = p.id
LEFT JOIN agent_reasoning_messages arm ON arm.prompt_id = p.id
LEFT JOIN function_calls fc ON fc.prompt_id = p.id
WHERE p.id = ?
ORDER BY tm.timestamp, tcm.timestamp, arm.timestamp, fc.call_timestamp;
```

**Get redactions applied to a prompt:**

```sql
SELECT r.*, rr.replacement_text
FROM redactions r
LEFT JOIN redaction_rules rr ON r.rule_id = rr.id
WHERE r.prompt_id = ?
ORDER BY r.applied_at;
```

**Check if a rule has been applied to a field:**

```sql
SELECT 1 FROM redactions
WHERE file_id = ? AND prompt_id = ? AND field_path = ?
  AND rule_id = ? AND rule_fingerprint = ?
LIMIT 1;
```

(Used before inserting to support `INSERT OR IGNORE`.)

---

## Migration & Backward Compatibility

### Schema Versioning

The schema is versioned implicitly by the presence of tables. On first use, `ensure_schema()` creates all tables.

If an existing database lacks new tables (added in a later version), `ensure_schema()` creates them without affecting existing data.

### Example: Adding `session_context`

Old schema had `cwd`, `approval_policy`, etc. in `sessions` table.

Migration:

1. Detect old schema (check if `session_context` table exists)
2. If missing: Create `session_context` table
3. Migrate data: `INSERT INTO session_context SELECT id, session_id, cwd, ... FROM sessions`
4. Drop old columns from `sessions`
5. Continue normally

Handled by `_migrate_normalize_schema()` in `database.py` (called by `ensure_schema()`).

---

## PostgreSQL Equivalence

The schema is designed to be database-agnostic. `src/services/postgres_schema.py` defines the PostgreSQL equivalent with:

- `SERIAL` instead of `INTEGER AUTOINCREMENT`
- `TIMESTAMP` instead of `TEXT` (though we use ISO-8601 strings for consistency)
- Identical table structure, FKs, and indexes

Migration path: SQLite → PostgreSQL via `cli/migrate_sqlite_to_postgres.py`.

---

## Performance Notes

1. **Query Performance:**
   - Indexing FKs enables efficient filtering by file/prompt/rule
   - `raw_json` columns are large but separate (don't fetched unless explicitly selected)
   - Consider adding `WHERE enabled = 1` index on `redaction_rules` if many rules exist

2. **Storage:**
   - Each *_messages table row may have `raw_json` (100s of bytes to KBs)
   - For large sessions, consider archiving old redactions or splitting by date range

3. **Ingest Batching:**
   - Transactions group events; configurable batch size balances memory vs. commit frequency
   - Default: 1000 events per transaction

---

## Next Steps

- See [`docs/architecture.md`](architecture.md) for system design and data flow
- See [`AGENTS.md`](../AGENTS.md) for schema change procedures
- See [`docs/schema_changes.md`](schema_changes.md) for migration history
