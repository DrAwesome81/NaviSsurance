# Chief of Staff (AI Assistant) Plan

## Executive Summary
NaviSsurance now includes a working **Chief of Staff + AI Executive Team** operating model:

- named specialist agents (Atlas, Quill, Sentinel, Lex, Scout, Mason, Ledger, Archive, Pulse, Shield),
- a delegation/assignment workflow with status history and artifacts,
- direct per-agent chat consoles,
- a CoS delegation board with bulk controls and health signals,
- and command-driven side effects (tasks/calendar/assignment actions) from CoS chat.

This document tracks implementation status and remaining roadmap work.

## Current State (Implemented)

### Core capabilities in production
- **CoS conversational actions**
  - `ADD_TASK`, `ADD_CAL_BLOCK`
  - task update actions: `TASK_SET_TAGS`, `TASK_SET_ESTIMATE`
  - full assignment actions (`ASSIGN`, status/priority/due/title/brief/summary/artifact updates)
  - bulk assignment actions (status/priority/due/reassign)
  - assignment-to-dashboard task actions (single + bulk, duplicate-safe by assignment ID)
- **Executive team directory + routing**
  - canonical agent identity, aliases, capabilities, home-tab routing
- **Assignment system**
  - assignment table + event timeline + linked artifacts
  - source-thread linkage and reassignment thread relinking
- **Delegation board**
  - filter/search, assignment detail timeline, artifact viewing, export to markdown
  - bulk board actions with optional audit notes
  - health view: overdue / blocked 3d+ / awaiting_review 3d+
- **Date safety**
  - strict calendar validation for due dates in parser and CoS board UI
- **Testing**
  - broad CoS parser/service unit coverage with mocked LLM calls
  - additional utility/helper tests for due-date and bulk-mode parsing

### AM Sweep (implemented)
AM Sweep is a **user-initiated morning triage loop** that gathers context (open tasks, assignments, today/upcoming calendar, unreplied emails, memory) and produces:

- an executive summary and four buckets: **Dispatch**, **Prep**, **Yours**, **Skip**
- optional prose-only **time-block proposal** (no calendar writes unless explicit machine actions are emitted)
- a final machine-action section that can:
  - create assignments (`ASSIGN`) to route work to specialist agents in parallel
  - tag / estimate existing tasks (`TASK_SET_TAGS`, `TASK_SET_ESTIMATE`)

#### How to run it (UI)
- Open the `Chief of Staff` tab
- Use `Options` → `AM Sweep`
- A dedicated chat thread is created if needed (titled like `AM Sweep YYYY-MM-DD`)

### Known gaps / next opportunities
- Planning/prioritization scoring is still heuristic (no formal urgency/importance scoring engine yet).
- Memory retrieval is lexical/structured, not embeddings-backed by default.
- Delegation currently uses command parsing; no generalized background job runner yet.
- Calendar write operations are available via explicit command, but broader scheduling optimization remains limited.

## Current CoS Action Command Reference

Use exact line formats in CoS-generated actions:

- Priority scale:
  - dashboard tasks: P0 (lowest urgency) … P5 (highest urgency)
  - delegation assignments: P1 (lowest urgency) … P5 (highest urgency)

- `ASSIGN: <AgentName> | <Title> | <Brief> | <P1-P5> | <YYYY-MM-DD or none>`
- `UPDATE_ASSIGNMENT_STATUS: <A-0007 or 7> | <queued|in_progress|awaiting_review|blocked|done|cancelled> | <optional note>`
- `BULK_UPDATE_ASSIGNMENT_STATUS: <status> | <AgentName or all> | <open or all (optional)> | <optional note>`
- `UPDATE_ASSIGNMENT_PRIORITY: <A-0007 or 7> | <P1-P5> | <optional note>`
- `BULK_UPDATE_ASSIGNMENT_PRIORITY: <P1-P5> | <AgentName or all> | <open or all (optional)> | <optional note>`
- `UPDATE_ASSIGNMENT_DUE: <A-0007 or 7> | <YYYY-MM-DD or none> | <optional note>`
- `BULK_UPDATE_ASSIGNMENT_DUE: <YYYY-MM-DD or none> | <AgentName or all> | <open or all (optional)> | <optional note>`
- `RETITLE_ASSIGNMENT: <A-0007 or 7> | <new title> | <optional note>`
- `UPDATE_ASSIGNMENT_BRIEF: <A-0007 or 7> | <new brief markdown> | <optional note>`
- `UPDATE_ASSIGNMENT_SUMMARY: <A-0007 or 7> | <summary markdown>`
- `REASSIGN: <A-0007 or 7> | <AgentName> | <optional note>`
- `BULK_REASSIGN_ASSIGNMENTS: <AgentName or all> | <AgentName target> | <open or all (optional)> | <optional note>`
- `ADD_ASSIGNMENT_ARTIFACT: <A-0007 or 7> | <artifact_type> | <title> | <content markdown>`
- `ADD_TASK_FROM_ASSIGNMENT: <A-0007 or 7> | <MM-DD-YYYY or none> | <Business or Personal>`
- `BULK_ADD_TASKS_FROM_ASSIGNMENTS: <AgentName or all> | <Business or Personal> | <open or all (optional)>`
- `ADD_TASK: <task description> | <MM-DD-YYYY or none> | <Business or Personal>`
- `TASK_SET_TAGS: <task_id> | <json array of tags>` (example: `TASK_SET_TAGS: 123 | ["triage:dispatch","source:am_sweep"]`)
- `TASK_SET_ESTIMATE: <task_id> | <minutes>` (0-600, example: `TASK_SET_ESTIMATE: 123 | 45`)
- `ADD_CAL_BLOCK: <title> | <start datetime> | <end datetime> | <calendar id or primary>`

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
- `doc_search` (unified search across Dropbox/local/Google Drive; dedup-aware) — see `docs/unified_search.md`
- `draft_email` (no send; produces a draft artifact)
- `schedule_suggestion` (no write; proposes blocks)

### Memory System (Structured + Retrieval)
Keep raw conversation logs (already in SQLite), and add a **memory layer** that can retrieve *only what’s needed* for a given prompt.

This approach is exactly what you described: store all chats, then attach **tags** and **summaries** so the assistant can find the right snippets quickly. The key is to store summaries/tags as **separate indexed fields**, not by mutating or “prepending” content onto the raw chat rows. (Prepending is workable, but it tends to contaminate retrieval results, duplicate information, and make it harder to audit what was actually said.)

#### Memory Components (Recommended)
- **Raw conversation log (immutable)**: full text of each turn, timestamped.
- **Chunking**: group turns into “chunks” (e.g., 10–30 turns, or ~2–5 minutes of conversation).
- **Rolling summaries**:
  - per-chunk summary (what happened, decisions, commitments)
  - per-day summary (high-level timeline)
  - per-project summary (current status and open loops)
- **Tags / entities**:
  - project/client (Abbott, Dova, etc.)
  - people (names, roles)
  - topics (FDA, ISO 13485, PCCP, etc.)
  - intent types (decision, task, preference, meeting, follow-up)
- **Structured memory facts** (for stable long-term recall):
  - preferences (working hours, tone, scheduling rules)
  - relationships (who is who, what company)
  - ongoing commitments (“I promised to send X by date Y”)

#### Retrieval Strategy (How it uses memory)
Use a staged approach so retrieval stays small and relevant:
1. **Hard filters** (fast): project tag, date window (e.g., last 30 days), person tags.
2. **Lexical search (FTS)**: search `conversation` and/or chunk summaries for keywords.
3. **Semantic re-rank (optional)**: if you add embeddings later, re-rank top candidates by similarity.
4. **Assemble minimal context**:
   - top N chunk summaries
   - the 3–10 most relevant raw turns (verbatim) for grounding
   - relevant memory facts (preferences/commitments)
5. **Guardrails**: retrieved text is treated as *untrusted reference*, not instructions; only user-approved actions cause side effects.

#### When to write memory (Summarize/Tag triggers)
- **On session end / idle timer**: summarize the last chunk and tag entities.
- **On explicit user command**: “remember this”, “tag this to Abbott”.
- **On high-signal events**:
  - task created
  - decision made (“we will do X”)
  - preference stated (“don’t schedule meetings before 10”)
  - delegation created (“ask agent to research Y”)

#### Is “tag + summarize + search” a good idea?
Yes. It’s a strong, low-complexity path that:
- keeps **full fidelity** (raw logs remain intact),
- makes retrieval cheap and relevant (summaries/tags are small),
- allows iterative upgrades (you can add embeddings later without changing the user experience),
- improves safety/auditability (you can show “why this was retrieved”).

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
- `conversation_chunks`:
  - `chunk_id`, `session_id`, `start_ts`, `end_ts`, `turn_ids_json`, `project_id` (nullable)
- `conversation_summaries`:
  - `summary_id`, `scope` (chunk/day/project), `scope_id`, `summary_text`, `key_decisions_json`, `open_loops_json`, `created_at`
- `conversation_tags`:
  - `tag_id`, `scope` (turn/chunk/session), `scope_id`, `tag_type` (project/person/topic/intent), `tag_value`, `confidence`, `created_at`
- `memory_facts`:
  - `fact_id`, `subject`, `predicate`, `object`, `confidence`, `source`, `created_at`, `updated_at`
- `memory_preferences` (optional, can be folded into `memory_facts`):
  - `pref_id`, `key`, `value`, `source`, `updated_at`
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

Status as of 2026-02-23:

- [x] **Milestone 0 (Foundation)**
  - Task capture, history, search, daily briefing, basic CoS chat.
- [x] **Milestone 2 (Structured memory v1)**
  - Structured memory extraction + retrieval context in CoS prompt.
- [x] **Milestone 3 (Delegation framework v1)**
  - Named agents, assignment lifecycle, artifacts, direct agent chats, CoS board controls.
- [~] **Milestone 4 (Scheduling assistance)**
  - Calendar awareness and explicit calendar block creation implemented.
  - Advanced schedule optimization remains future work.
- [~] **Milestone 1 (Prioritization MVP)**
  - Usable guidance exists, but a formal scoring/planning engine is still incomplete.
- [~] **Milestone 5 (Evaluation/regression safety)**
  - Strong CoS parser and DB regression coverage exists.
  - Broader scenario/e2e coverage can still be expanded.

### Next practical milestones

1. **Prioritization engine hardening**
   - Formal urgency/importance scoring and predictable plan-of-day output schema.
2. **Delegation runner v2**
   - Add explicit background job execution model beyond command parsing.
3. **Evaluation harness**
   - Add curated scenario fixtures for CoS recommendation quality + tool safety regressions.

## Operational Notes
- Configurable paths are defined in `core/settings.py` (DB, data dir, config dir, env file).
- Keep templates in `config/*.example.json` and keep real secrets out of git.
