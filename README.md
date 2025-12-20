# AI Log Trail
<!-- markdownlint-disable MD042 -->
[![Status](https://img.shields.io/badge/status-experimental-blueviolet)](#)
[![Version](https://img.shields.io/badge/version-0.4.1-orange)](#)
[![Python](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](#)
![Codecov](https://img.shields.io/codecov/c/github/lparlett/ai-log-trail?logo=codecov&logoColor=%23F01F7A)
[![DOI](https://zenodo.org/badge/1086626705.svg)](https://doi.org/10.5281/zenodo.17728973)
<!-- markdownlint-enable MD042 -->
> **Universal AI assistance logging with transparency.**  
> A flexible framework for capturing, analyzing, and sharing AI agent interactions while maintaining privacy and auditability. Supporting multiple AI agents and workflows, this tool helps organizations track and understand their AI usage patterns.

---

## Table of Contents

- [Why this exists](#why-this-exists)
- [Architecture Overview](#architecture-overview)
- [Current capabilities](#current-capabilities)
- [Getting started](#getting-started)
- [CLI Commands](#cli-commands)
- [Documentation](#documentation)
- [Troubleshooting](#troubleshooting)
- [Roadmap snapshot](#roadmap-snapshot-2025-10-30)
- [Contributing](#contributing--ethos)

---

## Why this exists

Codex (and other AI coding tools) produce rich session logs, but they're hard to read and even harder to share responsibly. The AI Log Trail tool ingests `*.json` or `*.jsonl` session data, normalizes it into SQLite, and generates human-friendly reports that highlight:

- User prompts and the agent responses/actions.
- Token usage and cost indicators.
- Function calls, reasoning trails, and decision history.
- Redactions applied to sensitive content so transparency doesn't compromise privacy.

The goal is a workflow where AI-assisted coding can be audited, explained, and optionally published in repositories or release notes.

---

## Architecture Overview

The AI Log Trail follows a simple 5-stage pipeline:

```text
Session Files (JSONL)
        ↓
   [Parser] ← discover, load, validate, group by user message
        ↓
   [Ingest] ← normalize, sanitize, persist to SQLite
        ↓
   [Redaction] ← apply rules & manual redactions
        ↓
   [Export] ← generate reports, output redacted data
```

**Key components:**

- **Parser** (`src/parsers/`) — Discovers nested session directories, loads JSONL events, groups by user prompt
- **Ingest** (`src/services/ingest.py`) — Validates, sanitizes, applies rule-based redactions, persists to SQLite in a transaction
- **Database** (`src/services/database.py`) — 12 normalized tables with cascading FK, audit trail via `raw_json` columns
- **Redactions** (`src/services/redactions.py`, `src/services/redaction_rules.py`) — Rule library, application tracking, deduplication via fingerprints
- **CLI** (`cli/`) — Entry points: ingest, group (display), export, rules management, migration

**Learn more:** [`docs/architecture.md`](docs/architecture.md) — Full system design, data flows, error handling.

---

## Current capabilities

- **Structured ingest** - Parse Codex session directories into tables (`files`, `sessions`, `prompts`, `token_messages`, `turn_context_messages`, `agent_reasoning_messages`, `function_plan_messages`, `function_calls`) with raw JSON preserved.
- **Redaction storage** - `redactions` table tracks prompt/field/global scopes with replacement text, actor, reason, and timestamps for provenance.
- **Rule-based redaction** - YAML/JSON rule file (`user/redactions.yml` seeded with
  defaults for emails, tokens, paths, troubleshooting snippets, and `[redact ...]`
  markers) applied in file order with per-rule counts in summaries; manual DB
  redactions still take precedence.
- **CLI utilities**
  - `python -m cli.group_session` groups events under each prompt for quick console or file review and writes to `[outputs].reports_dir` by default.
  - `python -m cli.ingest_session` ingests one or many sessions into SQLite with `--limit`, `--debug`, and `--verbose` modes using the configured database path.
- **Governance docs** - `AGENTS.md` sets behavioral guardrails; `ROADMAP.md` tracks milestones through v1.0.0 and beyond.
- **Config scaffolding** - `user/config.example.toml` seeds per-user setup; actual secrets stay local via `.gitignore`.
- **Migration docs** - `docs/migration.md` explains SQLite to Postgres migration, dry-run, and rollback steps.
- **Tests** - Organized under `tests/` by area:
  - `tests/services/` (config, redactions, rules, DB helpers)
  - `tests/parsers/` (session parsing, DB handlers)
  - `tests/cli/` (ingest, CLI scripts, migration)
  - `tests/core/` (models, base types, agent config)

---

## Getting started

> Requires Python 3.12+

1. **Clone & configure**

   ```bash
   git clone <repo-url>
   cd AI-Log-Trail
   cp user/config.example.toml user/config.toml
   # edit user/config.toml to set:
   #   [sessions].root -> Codex/Copilot logs directory
   #   [ingest].db_path -> SQLite destination
   #   [outputs].reports_dir -> where grouped reports should be written
   ```

   Optional tuning: set `[ingest].batch_size` in `user/config.toml` if you want a larger or smaller event batch during ingest (default is 1000).

2. **Ingest a sample**

   ```bash
   python -m cli.ingest_session --debug
   ```

   This ingests the first two sessions, logs verbose output, and writes to `[ingest].db_path`.

3. **Explore prompts**

   ```bash
   python -m cli.group_session
   ```

   Generates a grouped text report for the earliest session, stored under `[outputs].reports_dir` (override with `-o`).

---

## CLI Commands

The tool provides 5 main CLI commands. See [`docs/cli.md`](docs/cli.md) for full reference and examples.

| Command | Purpose | Example |
|---------|---------|---------|
| `ingest_session` | Load session logs into SQLite | `python -m cli.ingest_session --debug` |
| `group_session` | Display prompts & events | `python -m cli.group_session --list` |
| `export_session` | Export redacted session data | `python -m cli.export_session --format csv` |
| `redaction_rules` | Manage redaction library | `python -m cli.redaction_rules list --source yaml` |
| `migrate_sqlite_to_postgres` | Scale to PostgreSQL | `python -m cli.migrate_sqlite_to_postgres --dry-run` |

---

## Documentation

| Document | Purpose |
|----------|---------|
| [`docs/architecture.md`](docs/architecture.md) | System design: components, data flow, pipelines, algorithms |
| [`docs/schema.md`](docs/schema.md) | Database schema: table definitions, relationships, indexes |
| [`docs/cli.md`](docs/cli.md) | CLI reference: all commands, options, examples, workflows |
| [`docs/schema_changes.md`](docs/schema_changes.md) | Migration history: schema evolution, backward compatibility |
| [`docs/redaction_rules.md`](docs/redaction_rules.md) | Redaction authoring: rule syntax, ordering, examples |
| [`docs/migration.md`](docs/migration.md) | SQLite → Postgres migration: steps, dry-run, rollback |
| [`AGENTS.md`](AGENTS.md) | Development: coding standards, testing, security, versioning |
| [`ROADMAP.md`](ROADMAP.md) | Feature roadmap: phases, milestones, priorities |

---

## Troubleshooting

### Common Issues

#### ConfigError: sessions.root not found

- Ensure `[sessions].root` in `user/config.toml` points to an existing directory
- See [`docs/cli.md#troubleshooting`](docs/cli.md#troubleshooting) for detailed steps

#### SessionDiscoveryError: no sessions found

- Verify Codex logs are in the configured directory under `YYYY/MM/DD/` structure
- Run `ls -la /path/to/sessions/2025/` to check

#### EventValidationError: Missing required field 'type'

- Session JSONL file is malformed; inspect with `python -m json.tool`
- Try a different session file or repair JSONL before ingesting

#### Slow ingest

- Increase `[ingest].batch_size` in `user/config.toml` (default 1000)
- Run with `--limit 1` to process fewer files at once

For more details, see [`docs/cli.md#troubleshooting`](docs/cli.md#troubleshooting).

---

## Roadmap snapshot (2025-10-30)

Refer to [ROADMAP.md](ROADMAP.md) for the full plan. Highlights for v1.0.0:

- Schema migrations and automated tests.
- Redaction system (manual + rule-based) with CLI and UI controls.
- Streamlit review app for prompt/action browsing and export.
- Markdown/CSV transparency reports filtered by repo, date, or session.
- Pipx-friendly packaging and documentation.

Beyond v1.0.0 we're targeting tagging, audit trails, API integrations, VS Code extensions, and compliance-ready exports.

---

## Operational assumptions

- **Architecture** - Components are wired manually; no dependency injection framework is in place yet. Larger deployments should plan for DI or service registries before extending the tool.
- **Session paths** - Ingest expects Codex logs under `~/.codex/sessions/<year>/<month>/<day>/file.jsonl` (or the Windows equivalent). Symlinks and junctions must preserve this structure and point to readable directories; atypical mount points are not traversed automatically.
- **Memory profile** - JSON payloads are read as-is with no max size enforcement. Very large sessions can exhaust memory; split oversized logs before ingesting or ingest them incrementally.
- **Concurrency** - SQLite writes run in a single process and rely on SQLite's default locking. Running multiple ingests against the same database concurrently is unsupported and may deadlock.
- **Encoding** - All file I/O assumes UTF-8. Convert logs encoded differently before processing.
- **Timestamps** - Session timestamps are stored verbatim. Downstream analytics should normalize timezones explicitly (e.g., convert to UTC) to avoid skew.

These constraints will be revisited as part of resilience and scaling work.

---

## Contributing & ethos

This is an "AI-assisted" project-experiments will happen-but the mandate is transparency:

- Every commit notes AI assistance.
- Raw logs remain user-owned; ingest only reads from configured paths.
- Redactions are first-class citizens with provenance.

Ideas, bug reports, and questions are welcome. Please review `CONTRIBUTING.md` for expectations before contributing.

---

## License

This project is licensed under the terms of the [MIT License](LICENSE).
