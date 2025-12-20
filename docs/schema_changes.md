# Schema Changes and Configuration Surface

## 2025-11-29 - Schema normalization: eliminated denormalized columns

- **Motivation**: Removed redundant denormalization in `sessions`, `turn_context_messages`, and `redactions` tables to achieve 2NF (Second Normal Form).
  
- **sessions table simplification**:
  - Removed: `cwd`, `approval_policy`, `sandbox_mode`, `network_access` (duplicated context)
  - Created new `session_context` table (1:1 with sessions) to store session-level environment/execution context
  - Updated inserts in `src/parsers/handlers/db_utils.py` to split data insertion
  - Migration function `_migrate_normalize_schema()` in `database.py` handles live database upgrades

- **turn_context_messages simplification**:
  - Removed: `cwd`, `approval_policy`, `sandbox_mode`, `network_access` (duplicated from sessions/session_context)
  - Kept: `writable_roots` (turn-specific, not session-wide)
  - Updated index from `idx_redactions_prompt_scope` to `idx_redactions_prompt` (scope removed)

- **redactions table normalization**:
  - Removed: `scope`, `replacement_text` (now live in `redaction_rules` only, referenced by FK)
  - Kept: `rule_fingerprint` as immutable audit snapshot (what rule definition was applied)
  - Updated unique index from `(file_id, prompt_id, field_path, rule_id, rule_fingerprint, replacement_text)` to `(file_id, prompt_id, field_path, rule_id, rule_fingerprint)`
  - Revised `RedactionCreate` dataclass and CRUD helpers to no longer accept/store these fields

- **Code updates**:
  - `src/services/redactions.py`: Removed `scope`, `replacement_text` from dataclasses; removed scope validation functions; updated all insert/select queries
  - `src/services/ingest.py`: Stopped inserting `scope` and `replacement_text` into redactions
  - `cli/export_session.py`: Stopped passing `scope` and `replacement_text` to `RedactionCreate`
  - `src/parsers/handlers/db_utils.py`: Split session insert to populate new `session_context` table; simplified turn_context insert
  - `src/services/postgres_schema.py`: Mirrored all changes to Postgres schema definition; added `session_context` to copy order
  - Tests: Updated all 209 tests to remove scope/replacement_text assertions; deprecated tests checking removed validations

- **Backward compatibility**:
  - Migration function runs automatically on schema initialization if tables already exist
  - Existing databases are upgraded lazily (first time `ensure_schema()` is called)
  - All data preserved; no lossy transformation
  - Code queries now JOIN `redaction_rules` to get replacement text (transparent to callers via insert layer)

- **Performance notes**:
  - Eliminates redundant storage (4 columns duplicated across 2-3 tables)
  - One additional JOIN required for replacement_text lookup, offset by reduced I/O on larger tables
  - Index improvements on prompt-scoped queries (narrower index on redactions)

## 2025-11-29 - Redaction application provenance and dedupe

- Added `file_id`, `rule_fingerprint`, `session_file_path`, and `applied_at` columns to `redactions` to capture rule-driven applications (append-only).
- Added unique index `uniq_redactions_application` on `(file_id, prompt_id, field_path, rule_id, rule_fingerprint, replacement_text)` to support insert-or-ignore when both ingest and export apply rules.
- Added `rule_fingerprint` computation (SHA256 of normalized rule definition) and stored it on each redaction application.
- Added `rule_fingerprint` column to `redaction_rules` to track rule revisions and enable soft-disable of stale applications.
- Updated schemas (SQLite/Postgres) to include new columns and unique index.

## 2025-11-27 - Added redactions table (v0.6.0 / issue #5)

- Added `redactions` table tracking scope (`prompt`, `field`, `global`), optional prompt linkage, field paths, replacement text, actor, reason, and timestamps.
- Created index `idx_redactions_prompt_scope` to speed filtered lookups.
- Introduced `src/services/redactions.py` CRUD helpers for creating, listing, updating, and deleting redactions.

## 2025-11-27 - Added rule syncing and provenance

- Added `redaction_rules` table to persist YAML/JSON rules with scope, pattern, replacement, enabled flag, provenance fields, and timestamps.
- Added `rule_id` foreign key and `active` flag to `redactions` for tracing provenance and soft-disabling redactions tied to disabled rules.
- Updated SQLite and Postgres schemas plus connection helper (`get_connection_for_config`) to apply the new structures automatically.

## 2025-11-24 - Configured database/output paths

- Added `[ingest].db_path` and `[outputs].reports_dir` to `user/config.toml` (example updated).
- Config loader now validates that the database parent directory exists and is writable, and that `outputs.reports_dir` exists and is writable.
- `cli.ingest_session` defaults to `[ingest].db_path` when `--database` is not supplied.
- `cli.group_session` writes grouped output to `[outputs].reports_dir/session.txt` by default (overridable via `-o`).

- Added `redactions` table tracking scope (`prompt`, `field`, `global`), optional prompt linkage, field paths, replacement text, actor, reason, and timestamps.
- Created index `idx_redactions_prompt_scope` to speed filtered lookups.
- Introduced `src/services/redactions.py` CRUD helpers for creating, listing, updating, and deleting redactions.
