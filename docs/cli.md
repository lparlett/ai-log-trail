# CLI Commands Reference

This guide documents all available CLI commands, their options, and common workflows.

---

## Overview

The AI Log Trail provides five main CLI modules:

| Command | Purpose |
|---------|---------|
| `ingest_session` | Load Codex session logs into SQLite |
| `group_session` | Display grouped prompts & events from database |
| `export_session` | Export session data with redactions applied |
| `redaction_rules` | Manage redaction rule library |
| `migrate_sqlite_to_postgres` | Migrate database from SQLite to PostgreSQL |

---

## ingest_session

**Purpose:** Ingest one or more Codex session JSONL files into SQLite, applying validation, sanitization, and rule-based redactions.

### ingest_session: Usage

```bash
python -m cli.ingest_session [OPTIONS]
```

### ingest_session: Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--database`, `-d` | Path | `[ingest].db_path` from config | Path to SQLite database file |
| `--session`, `-s` | Path | (auto-discover) | Explicit session JSONL file to ingest |
| `--limit` | Int | (no limit) | Max number of session files to ingest (only with auto-discover) |
| `--verbose`, `-v` | Flag | false | Enable detailed logging to stdout |
| `--debug` | Flag | false | Debug mode: verbose logging + limit to 2 files |

### ingest_session: Examples

#### Ingest the earliest session with default config

```bash
python -m cli.ingest_session
```

**Output:**

```txt
Loaded config from user/config.toml
Ingesting session: /path/to/.codex/sessions/2025/10/30/session-1.jsonl
Ingested 15 prompts, 145 token events, 8 function calls.
3 redactions applied (email_regex: 2, token_pattern: 1).
Database: local.db
```

#### Ingest with verbose logging

```bash
python -m cli.ingest_session --verbose
```

**Output:** Includes per-event validation details, rule matching, and transaction summaries.

#### Ingest a specific session file

```bash
python -m cli.ingest_session --session /path/to/custom_session.jsonl --database custom.db
```

#### Debug mode: ingest first 2 sessions with verbose output

```bash
python -m cli.ingest_session --debug
```

#### Ingest up to 5 sessions from auto-discovered directory

```bash
python -m cli.ingest_session --limit 5 --verbose
```

### ingest_session: Common Workflows

#### Workflow 1: Initial Setup & Test Ingest

```bash
# Set up config
cp user/config.example.toml user/config.toml
# Edit config.toml: set sessions.root, ingest.db_path, outputs.reports_dir

# Test with one session in debug mode
python -m cli.ingest_session --debug

# Review output for errors
# If successful, ingest all
python -m cli.ingest_session
```

#### Workflow 2: Ingest New Sessions Periodically

```bash
# Cron job (daily):
cd /path/to/ai-log-trail
python -m venv .venv
. .venv/Scripts/activate
python -m cli.ingest_session --limit 10 --verbose >> logs/ingest.log 2>&1
```

#### Workflow 3: Handle Ingest Errors

If ingestion fails:

1. Check the error message (e.g., "Missing 'type' field in event on line 42")
2. Verify JSONL file format: `python -m json.tool session.jsonl | head -20`
3. If file is malformed, either:
   - Fix manually (text editor)
   - Skip file and ingest others: `--session <next_file>`
4. Re-ingest: errors are logged but don't block other sessions

### ingest_session: Error Messages

| Error | Cause | Fix |
|-------|-------|-----|
| `ConfigError: sessions.root not found` | Path in config doesn't exist | Update config.toml: `[sessions].root = "..."` |
| `ConfigError: db_path is absolute` | SQLite path is absolute on Windows | Use relative path or `~` expansion in config |
| `SessionDiscoveryError: no sessions found` | No JSONL files in sessions.root | Verify path and subdirectory structure |
| `EventValidationError: Missing required field 'type'` | JSONL line is malformed | Check JSONL format; skip file or fix manually |
| `sqlite3.IntegrityError: UNIQUE constraint failed` | File already ingested | Ingest only new files; check `files.path` in DB |
| `ErrorSeverity.CRITICAL: Corrupted JSONL header` | File header is invalid | Restore from backup or skip file |

---

## group_session

**Purpose:** Display a single session's prompts and grouped events in human-readable format.

### group_session: Usage

```bash
python -m cli.group_session [OPTIONS]
```

### group_session: Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `-o`, `--output` | Path | `[outputs].reports_dir/session_{id}.txt` | Write report to file (stdout if omitted) |
| `--list` | Flag | false | List all sessions in database; don't render |
| `--session` | Int | (earliest) | Session ID to group (use with --list to find) |
| `--limit-lines` | Int | 200 | Truncate long event payloads to N lines |

### group_session: Examples

#### Display earliest session to console

```bash
python -m cli.group_session
```

**Output:**

```txt
═══════════════════════════════════════════════════════════════
  Session 1 (2025-10-30T13:20:55Z)
═══════════════════════════════════════════════════════════════

[Prompt 1] 2025-10-30T13:20:55Z
User: "Write a Python function to sort a list"

  ├─ [token_count] prompt=42 completion=127 total=169
  ├─ [turn_context] cwd=/home/user/project sandbox_mode=enabled
  ├─ [function_call] code_edit
  │   arguments: {"file": "sort.py", "action": "create", ...}
  │   output: {"success": true, "line_count": 25}
  └─ [reasoning] "The user wants a simple sort function..."

[Prompt 2] 2025-10-30T13:21:30Z
User: "Add docstring to the function"
  ...
```

#### Write output to file

```bash
python -m cli.group_session --output reports/my_session.txt
```

#### List all sessions

```bash
python -m cli.group_session --list
```

**Output:**

```txt
Available sessions:
  ID | File | Path | Prompts | Tokens | Ingested
  1  | 1    | /home/user/.codex/sessions/.../session-1.jsonl | 5 | 420 | 2025-10-30T15:00:00
  2  | 2    | /home/user/.codex/sessions/.../session-2.jsonl | 8 | 680 | 2025-10-30T16:30:00
  3  | 3    | /home/user/.codex/sessions/.../session-3.jsonl | 3 | 210 | 2025-10-30T17:45:00
```

#### Display specific session

```bash
python -m cli.group_session --session 2 --output reports/session_2.txt
```

#### Shorten long events (limit to 100 lines each)

```bash
python -m cli.group_session --limit-lines 100
```

### group_session: Common Workflows

#### Workflow 1: Quick Review

```bash
# See earliest session in console
python -m cli.group_session

# Or list all and pick one
python -m cli.group_session --list
python -m cli.group_session --session <ID>
```

#### Workflow 2: Generate Reports for Sharing

```bash
# Create markdown report for a specific session
python -m cli.group_session --session 5 --output reports/session_5_review.txt

# Share the .txt file (safe: no raw session data exposed, only prompts & redacted info)
```

#### Workflow 3: Archive Sessions

```bash
# Generate reports for all sessions
for id in {1..50}; do
  python -m cli.group_session --session $id --output reports/session_${id}.txt 2>/dev/null
done
```

---

## export_session

**Purpose:** Export a session's data as redacted JSONL or CSV, applying all redaction rules and manual redactions.

### export_session: Usage

```bash
python -m cli.export_session [OPTIONS]
```

### export_session: Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--session` | Int | (earliest) | Session ID to export |
| `--file` | Int | (auto) | File ID to export (if exporting multiple files) |
| `--format` | Str | `jsonl` | Output format: `jsonl`, `csv`, or `json` |
| `--output`, `-o` | Path | stdout | Write to file instead of stdout |
| `--apply-rules` | Flag | true | Apply rule-based redactions |
| `--apply-manual` | Flag | true | Apply manual redactions from DB |
| `--dry-run` | Flag | false | Preview redactions without writing output |

### export_session: Examples

#### Export earliest session as JSONL (default)

```bash
python -m cli.export_session --output session_export.jsonl
```

**Output:** One event per line, redacted.

```jsonl
{"type": "session", "session_id": "...", "timestamp": "...", "payload": {...}}
{"type": "event_msg", "timestamp": "...", "payload": {"type": "token_count", ...}}
...
```

#### Export as CSV for Excel review

```bash
python -m cli.export_session --session 2 --format csv --output session_2.csv
```

**Output:**

```csv
prompt_id,event_type,timestamp,payload,redactions_applied
1,event_msg,2025-10-30T13:20:55Z,"token_count: 42 / 4000","email_regex (2)"
1,response_item,2025-10-30T13:21:00Z,"[REDACTED: API_KEY]","token_pattern (1)"
2,event_msg,2025-10-30T13:21:30Z,"turn_context: cwd=/home/user...","none"
```

#### Dry-run: preview redactions before export

```bash
python -m cli.export_session --session 3 --dry-run --verbose
```

**Output:**

```txt
Preview: Would apply 8 redactions
  - email_regex: 3 matches
  - token_pattern: 2 matches
  - path_redaction: 3 matches
Output would be 142 lines (original 150).
Use --output to write.
```

#### Export without rule-based redactions (manual only)

```bash
python -m cli.export_session --session 1 --apply-rules false --output manual_redactions_only.jsonl
```

---

## redaction_rules

**Purpose:** Manage the redaction rule library. Load, validate, list, and sync rules from YAML config to the database.

### redaction_rules: Usage

```bash
python -m cli.redaction_rules [SUBCOMMAND] [OPTIONS]
```

### redaction_rules: Subcommands

#### list

**Purpose:** Display all rules currently in the database or YAML file.

```bash
python -m cli.redaction_rules list [--source yaml|db]
```

**list: Options:**

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--source` | Str | `db` | Show rules from `db` (SQLite) or `yaml` (user/redactions.yml) |
| `--enabled` | Flag | (all) | Show only enabled rules |
| `--disabled` | Flag | (all) | Show only disabled rules |

**Example:**

```bash
python -m cli.redaction_rules list --source yaml
```

**Output:**

```txt
Rules in user/redactions.yml:
  1. email_regex (regex, scope=global)
     pattern: r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
     replacement: [REDACTED: EMAIL]
     enabled: true

  2. token_pattern (regex, scope=field)
     pattern: r'(sk_test_|sk_live_)\w+' 
     replacement: [REDACTED: API_KEY]
     enabled: true
     ignore_case: false

  ...
```

#### validate

**Purpose:** Check YAML file for syntax errors and rule conflicts.

```bash
python -m cli.redaction_rules validate [--rules PATH]
```

**validate: Options:**

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--rules` | Path | `user/redactions.yml` | Path to YAML rule file |

**Example:**

```bash
python -m cli.redaction_rules validate
```

**Output:**

```txt
✓ user/redactions.yml is valid (15 rules)
  - 14 enabled
  - 1 disabled (old_pattern)
No conflicts detected.
```

Or, if error:

```txt
✗ user/redactions.yml has errors:
  Line 42: Invalid regex pattern in 'broken_pattern': unterminated group
  Line 58: Unknown scope 'custom' (expected: field, prompt, global)
```

#### sync

**Purpose:** Load rules from YAML and sync to database. Replaces existing rules or adds new ones.

```bash
python -m cli.redaction_rules sync [--rules PATH] [--dry-run]
```

**sync: Options:**

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--rules` | Path | `user/redactions.yml` | Path to YAML rule file |
| `--dry-run` | Flag | false | Preview changes without modifying DB |

**Example:**

```bash
python -m cli.redaction_rules sync --dry-run
```

**Output:**

```txt
Dry-run: Would sync 15 rules from user/redactions.yml to local.db
Changes:
  + email_regex (new)
  + token_pattern (new)
  + path_redaction (updated: pattern changed)
  - old_rule (deleted: not in YAML)
  ~ api_key_pattern (no change)

Commit changes? (yes/no): 
```

### redaction_rules: Common Workflows

#### Workflow 1: Add a New Rule

1. Edit `user/redactions.yml`:

    ```yaml
    my_new_rule:
        type: regex
        pattern: r'MY_SECRET_\w+'
        scope: global
        replacement: '[REDACTED]'
        enabled: true
        reason: "Redact custom secrets"
    ```

2. Validate:

    ```bash
    python -m cli.redaction_rules validate
    ```

3. Sync to DB:

    ```bash
    python -m cli.redaction_rules sync
    ```

4. Verify:

    ```bash
    python -m cli.redaction_rules list --source db | grep my_new_rule
    ```

#### Workflow 2: Disable a Rule Temporarily

1. Edit `user/redactions.yml`, set `enabled: false`
2. Sync: `python -m cli.redaction_rules sync`
3. Re-ingest sessions: `python -m cli.ingest_session`
   (New ingests will not apply the disabled rule)

#### Workflow 3: Review Rule Coverage

```bash
# List all rules and their counts
python -m cli.redaction_rules list --source db
# Output shows how many times each rule was applied
```

---

## migrate_sqlite_to_postgres

**Purpose:** Migrate the SQLite database to PostgreSQL. Useful for scaling to multiple concurrent clients.

### migrate_sqlite_to_postgres: Usage

```bash
python -m cli.migrate_sqlite_to_postgres [OPTIONS]
```

### migrate_sqlite_to_postgres: Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--source` | Path | `[ingest].db_path` from config | SQLite database file |
| `--target` | Str | `[postgres].connection_string` from config | PostgreSQL connection string |
| `--dry-run` | Flag | false | Preview migration without committing |
| `--verbose` | Flag | false | Detailed output per table |
| `--batch-size` | Int | 1000 | Rows per batch during copy |

### Connection String Format

```bash
postgresql://username:password@localhost:5432/ai_log_trail_db
```

Or with environment variables:

```bash
export PGPASSWORD="my_password"
python -m cli.migrate_sqlite_to_postgres --target postgresql://user@localhost:5432/ai_log_trail
```

### migrate_sqlite_to_postgres: Examples

#### Dry-run: preview migration

```bash
python -m cli.migrate_sqlite_to_postgres --dry-run --verbose
```

**Output:**

```txt
Dry-run mode: No changes will be committed
Source: local.db (SQLite)
Target: postgresql://user@localhost:5432/ai_log_trail

Checking target schema...
  ✓ Connected to PostgreSQL
  ✓ Tables exist (12 tables, 0 rows)

Comparing row counts:
  files: 5 rows in SQLite
  sessions: 5 rows in SQLite
  prompts: 47 rows in SQLite
  token_messages: 623 rows in SQLite
  ...
  Total: 2,847 rows to migrate

Would migrate without errors.
Execute without --dry-run to proceed.
```

#### Execute migration

```bash
python -m cli.migrate_sqlite_to_postgres --verbose
```

**Output:**

```txt
Migrating SQLite → PostgreSQL...
Source: local.db
Target: postgresql://user@localhost:5432/ai_log_trail

Creating schema on target...
  ✓ Schema created

Copying tables:
  ✓ files (5 rows, 0.12s)
  ✓ sessions (5 rows, 0.08s)
  ✓ session_context (5 rows, 0.06s)
  ✓ prompts (47 rows, 0.18s)
  ✓ token_messages (623 rows, 1.2s)
  ✓ turn_context_messages (47 rows, 0.09s)
  ✓ agent_reasoning_messages (94 rows, 0.15s)
  ✓ function_plan_messages (12 rows, 0.05s)
  ✓ function_calls (18 rows, 0.11s)
  ✓ redaction_rules (15 rows, 0.04s)
  ✓ redactions (87 rows, 0.09s)
  ✓ events (0 rows, 0.02s)

Verifying row counts...
  ✓ All tables match

Migration complete: 2,847 rows in 3.2s
Switch application to PostgreSQL connection string in config.
```

#### Rollback (if needed)

```bash
# Migration failed or you want to revert:
# Option 1: Restore SQLite from backup
cp local.db.backup local.db

# Option 2: Drop PostgreSQL and retry
psql -U user -d postgres -c "DROP DATABASE ai_log_trail;"
python -m cli.migrate_sqlite_to_postgres --dry-run --verbose
python -m cli.migrate_sqlite_to_postgres --verbose
```

### migrate_sqlite_to_postgres: Common Workflows

#### Workflow 1: Scale from SQLite to PostgreSQL

1. **Set up PostgreSQL:**

    ```bash
    createdb -U postgres ai_log_trail
    # Or via cloud provider (AWS RDS, Azure, etc.)
    ```

2. **Update config:**

    ```toml
    [postgres]
    connection_string = "postgresql://user:pass@pg.example.com:5432/ai_log_trail"
    ```

3. **Dry-run:**

    ```bash
    python -m cli.migrate_sqlite_to_postgres --dry-run --verbose
    ```

4. **Migrate:**

    ```bash
    python -m cli.migrate_sqlite_to_postgres --verbose
    ```

5. **Verify:**

    ```bash
    # Test query on PostgreSQL
    psql -U user -d ai_log_trail -c "SELECT COUNT(*) FROM prompts;"
    ```

6. **Switch application:**

Update `user/config.toml` to use PostgreSQL connection string; next ingest will use Postgres.

#### Workflow 2: Scheduled Backup & Replication

```bash
# Cron: daily backup of SQLite, replicate to Postgres
0 2 * * * /path/to/backup.sh
0 3 * * * python -m cli.migrate_sqlite_to_postgres --verbose >> logs/sync.log 2>&1
```

---

## Common Patterns

```bash
# 1. Configure
cp user/config.example.toml user/config.toml
# (Edit config.toml with your paths)

# 2. Ingest
python -m cli.ingest_session --debug

# 3. Review
python -m cli.group_session

# 4. Export for sharing
python -m cli.export_session --format csv --output summary.csv

# 5. Manage rules
python -m cli.redaction_rules list --source yaml
```

### Pattern 2: Batch Processing

```bash
#!/bin/bash
# Ingest all sessions, generate reports

python -m cli.ingest_session
python -m cli.redaction_rules sync

for i in {1..100}; do
  python -m cli.group_session --session $i --output reports/session_${i}.txt 2>/dev/null || break
done
```

### Pattern 3: CI/CD Integration

```yaml
# GitHub Actions example
- name: Ingest sessions
  run: python -m cli.ingest_session --limit 5 --verbose

- name: Generate reports
  run: |
    for i in {1..5}; do
      python -m cli.group_session --session $i --output session_${i}.txt || true
    done

- name: Upload artifacts
  uses: actions/upload-artifact@v3
  with:
    name: session-reports
    path: reports/
```

---

## Troubleshooting

### Issue: "ConfigError: sessions.root not found"

**Cause:** Path in `user/config.toml` doesn't exist.

**Fix:**

```bash
# Check the configured path
grep "root =" user/config.toml

# Create or correct the directory
mkdir -p /path/to/sessions
# Update config.toml with correct path
```

### Issue: "SessionDiscoveryError: no sessions found"

**Cause:** Directory exists but has no JSONL files.

**Fix:**

```bash
# Verify directory structure
ls -la /path/to/.codex/sessions/2025/10/30/

# Should see *.jsonl files
# If not, verify Codex logs are being written there
```

### Issue: "EventValidationError: Missing required field 'type'"

**Cause:** JSONL file is malformed.

**Fix:**

```bash
# Inspect the problematic file
head -5 /path/to/session.jsonl | python -m json.tool

# If output is not valid JSON, file is corrupted
# Option 1: Repair with jq (if partial corruption)
jq '.' /path/to/session.jsonl | jq -s '.' > fixed.jsonl

# Option 2: Use a different session file
python -m cli.ingest_session --session /path/to/different_session.jsonl
```

### Issue: Ingest is slow

**Cause:** Large session files or batch size too small.

**Fix:**

```toml
# In user/config.toml, increase batch size
[ingest]
batch_size = 5000  # Default is 1000
```

Or run ingest with `--limit` to process fewer files:

```bash
python -m cli.ingest_session --limit 1 --verbose
```

### Issue: Export has missing redactions

**Cause:** Rules not synced or changed after ingest.

**Fix:**

```bash
# Verify rules in DB
python -m cli.redaction_rules list --source db

# Sync latest rules
python -m cli.redaction_rules sync

# Re-apply redactions on next export
python -m cli.export_session --apply-rules true --dry-run
```

---

## Next Steps

- See [`docs/architecture.md`](architecture.md) for system design
- See [`docs/schema.md`](schema.md) for database structure
- See [`AGENTS.md`](../AGENTS.md) for coding standards
- See [`README.md`](../README.md) for quick start
