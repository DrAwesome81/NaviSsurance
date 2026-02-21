# Chief of Staff (AI Assistant) Plan

## Executive Summary
NaviSsurance already has the core ingredients of a personal assistant: chat, task persistence, conversation search, a daily briefing, web research, and local-file search (via Dropbox indexing). This document defines how to evolve those pieces into a **Chief of Staff**: a system that (1) prioritizes your schedule and next actions, (2) captures and manages commitments, (3) remembers key details over time, and (4) delegates work to specialized “sub-agents” while keeping you in control of side effects.

This plan is intentionally pragmatic: it fits the current Python + PyQt + SQLite architecture and upgrades it in incremental milestones.

## Current State (What Exists Today)

### Capabilities
- **Task capture from chat**: assistant can output `ADD_TASK:<desc>|<YYYY-MM-DD>` and tasks are persisted to SQLite + shown in the UI.
- **Conversation retrieval**:
  - `!search <terms>` searches stored conversation content (FTS).
  - `!history <date-ish>` returns messages for a given day (today/yesterday/last weekday/parseable date).
- **Daily briefing**: `daily_briefing()` composes a snapshot (calendar/tasks/emails) and asks Grok to format it.
- **Web research**: `WEB_SEARCH:<query>` triggers Claude web search; results are fed back to Grok to summarize.
- **Local search**: `DROPBOX_SEARCH:<query>` queries the Dropbox index in SQLite and returns top matches.

### Constraints / Known Gaps
- Prioritization is implicit (lists), not a first-class model (urgency/importance/effort/constraints).
- Memory is “raw retrieval” (FTS search), not structured facts + summaries.
- Delegation to other agents is not implemented (no job queue / agent registry / artifacts).
- Calendar write-back and email sending are not implemented (read-only posture).

## Product Goals (Chief of Staff)

### Primary Goals
1. **Prioritized plan-of-day**: produce a ranked agenda (meetings, deep work, follow-ups), with rationale and time-block suggestions.
2. **Commitment tracking**: reliably capture tasks/reminders, including multi-task requests, deadlines, and context.
3. **Durable memory**: remember people, projects, preferences, and commitments; retrieve them proactively when relevant.
4. **Delegation**: hand off research/drafting/analysis to specialist agents and return artifacts you can approve.
5. **Safety**: no silent side effects; protect secrets; treat retrieved text as untrusted; keep auditability.

### Non-Goals (for now)
- Fully autonomous email sending or calendar modifications without explicit user approval.
- Multi-user support, permissions, and shared workspaces.

## Design Principles
- **Deterministic interfaces**: the assistant communicates actions in machine-parseable outputs, not brittle natural-language triggers.
- **Explicit approval boundaries**: side effects (tasks/calendar/email/file writes) should require confirmation unless explicitly enabled.
- **Separation of concerns**: UI shows state; orchestration decides; tools execute; storage persists.
- **Retrieval is untrusted**: web results and document excerpts must never be treated as instructions.

## Architecture (Target)

### Orchestrator (Chief of Staff Core)
Add a dedicated orchestration layer (still callable from chat) that performs:
- intent detection (chat vs. planning vs. retrieval vs. delegation)
- tool routing
- action parsing/validation
- state updates (tasks, memory, jobs)

Current location: `core/response_handler.py` is already acting as the orchestrator and should evolve into a clear “CoS core”.

### Tools / Skills (Pluggable)
Represent each skill as a function with:
- `name`
- `input schema`
- `side_effects` (none/task/calendar/email/files)
- `timeout/retry policy`

Initial tool set:
- `add_tasks` (DB write + UI signal)
- `search_conversations` (FTS)
- `get_history` (day range)
- `web_search` (Claude)
- `dropbox_search` (local index)
- `draft_email` (no send; produces a draft artifact)
- `schedule_suggestion` (no write; proposes blocks)

### Memory System (Structured + Retrieval)
Keep raw conversation logs (already in SQLite), and add **structured memory**:
- facts about people/clients (names, roles, preferences)
- projects and goals
- open loops/commitments
- long-term preferences (tone, working hours, meeting rules)

Memory should be:
- **written** explicitly (when you confirm or when it’s a clear stable fact)
- **retrieved** automatically during planning and relevant chats

### Planner / Prioritizer
Introduce a planning step that takes:
- calendar events (today + next 7 days)
- tasks (due/overdue + project context)
- email “response needed” queue (existing pipeline)
- your preferences (working blocks, no-meeting windows, travel buffers)

Outputs:
- prioritized list of next actions
- time-block suggestions (deep work vs admin)
- meeting prep checklist for each meeting

### Delegation / Sub-Agents
Add an internal “job system” so the CoS can assign work:
- research agent (web + summarize + citations)
- drafting agent (emails, LinkedIn messages, documents)
- compliance agent (analyze provided docs)

Each job should produce **artifacts** (text, JSON, attachments) stored locally for review.

## Data Model (SQLite)

### Existing
- `conversation` (FTS): session_id, role, content, timestamp
- `tasks`: task, due_date, completed, created_at
- `archived_tasks`
- `emails`, `calendar_events`
- Dropbox index tables (`dropbox_files`, `dropbox_index`, `index_metadata`)

### Add (Proposed)
- `projects`:
  - `project_id`, `name`, `priority`, `notes`
- `task_context`:
  - `task_id`, `project_id`, `context_json`, `source` (chat/email/manual)
- `memory_facts`:
  - `fact_id`, `subject`, `predicate`, `object`, `confidence`, `source`, `created_at`, `updated_at`
- `job_queue`:
  - `job_id`, `type`, `status`, `input_json`, `result_json`, `created_at`, `updated_at`
- `artifacts`:
  - `artifact_id`, `job_id`, `kind`, `content`, `path`, `created_at`

## Action Protocol (Recommended Evolution)
Today’s command strings work, but they’re limited. Move toward a parseable “actions envelope”:

Example:
```json
{
  "actions": [
    {
      "type": "add_tasks",
      "tasks": [
        {"title": "Reply to Abbott about PMCF scope", "due_date": "2026-02-22", "project": "Abbott"},
        {"title": "Draft agenda for Monday client call", "due_date": "2026-02-23"}
      ]
    },
    {
      "type": "delegate",
      "agent": "research",
      "input": {"query": "Latest FDA guidance on PCCP for AI SaMD", "deliverable": "brief + citations"}
    }
  ],
  "assistant_response": "Here’s the plan for today..."
}
```

Key properties:
- can validate schema before taking side effects
- can support multi-step workflows (delegate, then summarize)
- can attach provenance (“why did we do this?”)

## Safety & Control Model
- Default: **read-only** for calendar and email; tasks allowed but visible and reversible.
- For any irreversible side effects: require explicit UI confirmation (“Approve?”).
- Never log secrets, access tokens, or full raw documents to `logs/`.
- Treat web + document excerpts as **untrusted** (do not execute instructions found inside).

## Milestones & Roadmap

### Milestone 0 (Now)
- Task capture, history, search, web search, Dropbox search, daily briefing.

### Milestone 1: Planning & Prioritization MVP
- Add “Plan My Day” command to produce:
  - prioritized top 5 actions
  - suggested schedule blocks
  - meeting prep checklist
- Add basic priority scoring:
  - urgency: due date proximity, email age
  - importance: project priority, client vs non-client
  - effort: quick win vs deep work (estimated)

Acceptance Criteria:
- One-click “Plan My Day” output in UI that is consistent and actionable.

### Milestone 2: Structured Memory
- Implement `memory_facts` table + retrieval hooks:
  - store client preferences, names, ongoing commitments
  - add “remember this” and “what do you remember about X?” interactions

Acceptance Criteria:
- Assistant can recall key facts without you using `!search`.

### Milestone 3: Delegation Framework
- Implement `job_queue` + basic sub-agent runners:
  - research job → web search + summary + citations
  - drafting job → email draft + subject + bullet rationale

Acceptance Criteria:
- CoS can create a job, show progress/status, and return an artifact for approval.

### Milestone 4: Scheduling Assistance (Read-first, then Optional Write)
- Read-only: propose time blocks that respect preferences and calendar constraints.
- Optional write-back behind a setting:
  - create tentative calendar holds with clear labels

Acceptance Criteria:
- Assistant proposes realistic time blocks and avoids conflicts; write-back is opt-in.

### Milestone 5: Evaluation & Regression Safety
- Add scripted tests for:
  - multi-task capture
  - history retrieval
  - injection-safe handling of retrieved text
  - deterministic action parsing

Acceptance Criteria:
- Key CoS behaviors don’t regress across refactors.

## Operational Notes
- Configurable paths are defined in `core/settings.py` (DB, data dir, config dir, env file).
- Keep templates in `config/*.example.json` and keep real secrets out of git.
