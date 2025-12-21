# Codex Sessions Tool Roadmap

This roadmap outlines the path to a viable **v1.0.0** release and sketches the extensions that follow.

---

## Phase 0: Foundations (in progress)

- Ingest Codex JSONL sessions into normalized SQLite tables (`files`, `sessions`, `prompts`, `token_messages`, `turn_context_messages`, `agent_reasoning_messages`, `function_plan_messages`, `function_calls`).
- Capture raw JSON alongside structured rows to enable future reprocessing and audits.
- CLI utilities for grouping events (`cli.group_session`) and ingesting sessions (`cli.ingest_session` with limit/debug/verbose modes).

---

## Phase 1: Viable v1.0.0 (core transparency export)

### Milestones

- v0.4.0: Schema & ingestion hardening
- v0.6.0: Redaction baseline + CLI
- v0.8.0: Reporting CLI + filters
- v0.9.0: Review UI + redaction persistence
- v1.0.0: Packaging, docs, governance

### Issue bundle: v0.4.0 (Schema & ingestion hardening)

- [X] Add SQLite migration tooling and document the migration flow.
- [X] Expose DB path and output dirs in `user/config.toml`; validate paths on startup (ingest CLI now defaults to config db path; grouping CLI writes to configured reports dir).
- [X] Expand ingestion tests for `group_by_user_messages`, `_parse_prompt_message`, `_insert_function_call`.
- [X] CI: enforce Codecov config and ensure lint/type/test gates pass on PRs.

**Why migrate beyond SQLite?**

SQLite stays the default for single-user, local ingest, but we need a path to a server database (PostgreSQL) for team use and larger datasets. Reasons: better concurrency for simultaneous ingests/reviews, role-based access controls for sensitive logs, WAL-based durability, easier backup/restore, and managed storage that will not hit file-lock limits on Windows. Migration tooling will let users lift existing SQLite data into Postgres without losing audit trails.

### Issue bundle: v0.6.0 (Redaction baseline + CLI)

- [X] Add `redactions` table (prompt/field overrides: replacement text, actor, timestamp, reason) with CRUD helpers. (v0.6.0 / #5)
- [X] Add configurable redaction rules (regex / `[redact ...]`) via YAML/JSON.
- [X] CLI: list/add/remove redactions; ensure exports apply redactions by default.
- [X] Tests for redaction application and rule precedence.

### Issue bundle: v0.8.0 (Reporting CLI + filters)

- [ ] Add CoPilot ingestion and parsing
- [ ] Add `ai-log-trail report` modes: prompts-only; prompts + reasoning/actions; token summaries.
- [ ] Support Markdown and CSV outputs.
- [ ] Filters: date range, repo/workspace, session id.
- [ ] Include transparency metadata (e.g., entries redacted by X).
- [ ] Golden tests per mode/filter with redactions applied.

### Issue bundle: v0.9.0 (Review UI + persistence)

- [ ] Streamlit (or lightweight) UI: session browser, prompt detail view, agent actions.
- [ ] Redaction controls in UI; persist to SQLite `redactions`.
- [ ] Export button that mirrors reporting CLI behavior.
- [ ] UI smoke tests and persistence tests.

### Issue bundle: v1.0.0 (Packaging, docs, governance)

- [ ] Package for easy install (pipx/zipapp); document install/upgrade.
- [ ] Quick-start docs: config, ingest, review, redact, export.
- [ ] Governance notes: data ownership, privacy, audit trails.
- [ ] Release notes and final schema/doc sync.

**Exit criteria for v1.0.0:**  

Users can ingest all sessions, review prompts/actions, apply redactions through CLI or UI, and export sanitized reports suitable for repo transparency.

---

## Phase 2: Quality & Collaboration Enhancements

- Add tagging: allow prompts and sessions to be labeled (e.g., repo names, project themes). Provide filters in UI/CLI.
- Introduce notes/disposition columns (e.g., “followed”, “ignored”, “needs review”).
- Track redaction history (versioning, undo, audit logs).
- Offer diff-based preview: raw vs redacted side-by-side before publishing.
- Integrate token cost analytics (aggregate token_count events, estimate cost).
- Provide REST/GraphQL API (FastAPI) so other tools (VS Code extensions, dashboards) can consume the data.

---

## Phase 3: Integrations & Publishing

- Build a VS Code extension that surfaces prompts/actions inline and lets users redact from the editor.
- Add GitHub Action / CLI support to generate transparency reports during CI (using redaction rules committed to repo).
- Support multi-user workflows: per-user redaction namespaces, shared databases, or sync with central datastore.
- Implement optional cloud sync (S3/SQLite over HTTP) for teams needing centralized storage.
- Explore transformer-based summarization to provide “agent action summaries” per prompt.

---

## Phase 4: Advanced Features (vision)

- Plug into issue trackers: auto-link prompts/actions to Jira/GitHub issues.
- Offer PDF/HTML interactive transparency dashboards (Plotly Dash, Superset integration).
- Anomaly detection: flag prompts where agent actions touched sensitive repositories or made large changes.
- Provide compliance exports (e.g., SOC2/ISO templates) compiling AI usage records.

---

## Ongoing Tasks

- Maintain comprehensive unit/integration tests; add sample fixtures with synthetic logs.
- Monitor schema changes and keep `AGENTS.md` / docs updated.
- Collect user feedback from early adopters to refine UI/UX, redaction flows, and reporting formats.

---

**Next checkpoint:** Finish Phase 1 backlog items, ship v1.0.0, gather feedback from internal projects, then prioritize Phase 2 initiatives based on usage patterns.
