# Chief of Staff (AI Assistant) Plan

<!-- Pulse private memory + Shield triage for CoS coordination -->

## Executive Summary
NaviSsurance now includes a working **Chief of Staff + AI Executive Team** operating model:

- named specialist agents (Atlas, Quill, Sentinel, Lex, Scout, Mason, Ledger, Archive, Pulse, Shield),
- a delegation/assignment workflow with status history and artifacts,
- direct per-agent chat consoles,
- a CoS delegation board with bulk controls and health signals,
- and command-driven side effects (tasks/calendar/assignment actions) from CoS chat.

This document tracks implementation status and remaining roadmap work.

Last updated: 2026-05-12

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
  - automatic assignee-thread handoff with an initial intake reply
- **Delegation board**
  - filter/search, assignment detail timeline, artifact viewing, export to markdown
  - bulk board actions with optional audit notes
  - health view: overdue / blocked 3d+ / awaiting_review 3d+
  - latest agent follow-up summary plus `NEEDS_INPUT` visibility on assignments
  - sortable table-style board columns for faster triage
- **Date safety**
  - strict calendar validation for due dates in parser and CoS board UI
- **Testing**
  - broad CoS parser/service unit coverage with mocked LLM calls
  - additional utility/helper tests for due-date and bulk-mode parsing
- **Memory / retrieval**
  - explicit `Teach Navi:` memory capture with approved global memory
  - explicit `Teach <Agent>:` memory capture with approved per-agent durable memory
  - passive review-first memory extraction for stable facts, preferences, and aliases
  - durable `agent_memory` for named specialists
  - task-local `assignment_memory` for assignment/thread-specific working context
  - richer alias / glossary entries with synonyms and optional scope metadata
  - summary-first long-term retrieval over older chat turns with raw-turn grounding fallback
  - daily / weekly memory reflection summaries backed by approved memory and chunk summaries
  - entity-scoped memory links for client/project-aware recall
  - promotion flows from:
    - `agent_memory -> global Navi memory`
    - `assignment_memory -> agent_memory`
- **Runtime / integrations**
  - optional background runtime scheduler for queued and recurring jobs
  - optional local HTTP API for non-GUI integrations
  - shared tool registry for CoS, agents, and browser-backed tools

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
- Memory retrieval is still primarily lexical/structured, with semantic/entity-aware enhancements still maturing.
- Delegation now has runtime scaffolding, but broader queue-backed execution still needs production hardening.
- Calendar write operations are available via explicit command, but broader scheduling optimization remains limited.
- Agent/assignment reflection summaries are still a follow-up opportunity beyond the current global reflection layer.

## Current Delegation UX

### What happens when CoS assigns work
- A delegation assignment is created.
- A linked assignee-owned thread is created automatically.
- The assigned agent gets an initial kickoff prompt and posts an intake-style first reply into that thread.
- The CoS assignment board can then show whether the assignee is waiting on you for answers or files.

### What to look for on the board
- Assignment rows can show `NEEDS_INPUT` when the latest agent reply contains questions, missing-input requests, or document requests.
- The delegation board can be sorted by column header to group by status, assignee, priority, due date, or follow-up state.
- The delegation board also restores your last filter state and column layout on reopen.
- The assignment detail pane shows:
  - the latest agent update,
  - whether input is currently needed,
  - extracted request lines,
  - and any uploaded files already attached to the assignment.

### How to respond when an agent needs something
1. Select the assignment in the CoS board.
2. Read the `Agent follow-up` section.
3. Click `Open Assignee Chat`.
4. Reply in the agent thread and/or use `Upload Artifact` to attach requested files.
5. Return to the CoS board to confirm the assignment no longer needs input.

## Current Memory Model

### Memory layers
The current CoS-adjacent memory model is now layered:

- `user_memory`
  - global Navi memory for durable user-wide facts, preferences, aliases, and curated promoted learnings
- `cos_memory`
  - CoS-specific planning memory and structured retrieval notes
- `agent_memory`
  - durable private memory for one named specialist such as `Atlas` or `Quill`
- `assignment_memory`
  - task-local, short-horizon memory attached to assignments and threads

### Access model
- direct agents read:
  - their own `agent_memory`
  - relevant `assignment_memory`
  - filtered global memory when injected
- Chief of Staff reads:
  - `cos_memory`
  - global Navi memory
  - relevant agent memory
  - relevant assignment memory
- Navi reads:
  - global memory directly
  - selective supervisor slices from agent and assignment memory when relevant

### Explicit teaching
- `Teach Navi: ...`
  - writes approved memory into global Navi memory
- `Teach Atlas: ...`
- `Teach Quill: ...`
- `Teach <AgentName>: ...`
  - writes approved memory into that agent's durable memory

### Promotion paths
CoS can now promote:
- selected agent memory into global Navi memory
- selected assignment memory into durable agent memory

This keeps temporary task facts from polluting global memory while still allowing useful learnings to graduate upward.

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
- `ADD_TASK: <task description> | <MM-DD-YYYY or none> | <Business or Personal> [| <P0-P5>] [| <assigned to or none>] [| <project id or none>] [| <recurrence: None|Daily|Weekly|Monthly>] [| <estimate: minutes or duration (e.g. 1 hr 15 min) or none>]`
- `TASK_SET_TAGS: <task_id> | <json array of tags>` (example: `TASK_SET_TAGS: 123 | ["triage:dispatch","source:am_sweep"]`)
- `TASK_SET_ESTIMATE: <task_id> | <minutes>` (0-600, example: `TASK_SET_ESTIMATE: 123 | 45`) — updates an existing task; new tasks can also carry estimate in `ADD_TASK`’s last field (minutes or a phrase like `1 hr 15 min`, stored as minutes)
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

## Architecture (Target / design reference)
Much of the orchestration, tool registry, memory layers, and delegation flows described below are **now implemented** (see `core/chief_of_staff_service.py`, `core/tool_registry.py`, and related modules). Keep this section as a **design reference** for remaining gaps (for example formal JSON action envelopes and a dedicated prioritization engine), not as a checklist of missing foundation work.

### Orchestrator (Chief of Staff Core)
Add a dedicated orchestration layer (still callable from chat) that performs:
- intent detection (chat vs. planning vs. retrieval vs. delegation)
- tool routing
- action parsing/validation
- state updates (tasks, memory, jobs)

Current execution spine now spans:
- `core/main_chat_router.py`
- `core/chief_of_staff_service.py`
- `core/response_handler.py`

`core/response_handler.py` still contains legacy orchestration paths, but the current CoS behavior is primarily centered in `core/chief_of_staff_service.py`.

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
- `web_search` (current remote provider path)
- `dropbox_search` (local index)
- `doc_search` (unified search across Dropbox/local/Google Drive; dedup-aware) — see `docs/unified_search.md`
- `draft_email` (no send; produces a draft artifact)
- `schedule_suggestion` (no write; proposes blocks)

Current implementation note:
- Shared tool registration now lives in `core/tool_registry.py`.
- CoS tool-trigger loops in `core/chief_of_staff_service.py` should be treated as consumers of that shared tool surface rather than a fully separate long-term system.

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

Current implementation note:
- `user_memory` is the global durable store for Navi-wide recall.
- `agent_memory` is the per-agent durable store.
- `assignment_memory` is the task-local store for assignments and threads.
- `chat_retrieval` handles summary-first long-term retrieval.
- reflections are stored separately.
- entity links now allow memory rows to be associated with clients and projects.

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

Current implementation note:
- Runtime-backed job scaffolding now exists in `core/runtime/`.
- Assignment bootstrap work can be queued via the runtime layer.
- This is still not the same as a fully generalized autonomous multi-agent operating system.

## Data Model (SQLite)

### Existing
- `conversation` (FTS): session_id, role, content, timestamp
- `tasks`: task, due_date, completed, created_at
- `archived_tasks`
- `emails`, `calendar_events`
- Dropbox index tables (`dropbox_files`, `dropbox_index`, `index_metadata`)

### Add (Proposed — historical design sketch)
The bullets below were an early schema sketch. Much of this has since shipped under different table names (for example assignments, `runtime_jobs`, durable memory stores, and artifact tables). Treat this list as **design history**, not a migration checklist.
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

Status as of 2026-05-12:

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
- Configurable paths (database, data directory, config directory, env file location) are defined in `core/settings.py`.
- CoS / AM Sweep context budgets, per-block caps, multi-turn history limits, and Grok output caps are edited from **Settings → App preferences** (`core/app_preferences.py`).
- Keep templates in `config/*.example.json` and keep real secrets out of git.
