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
- Planning/prioritization scoring: basic heuristic started (_compute_priority_score in chief_of_staff_service: explicit P + due/overdue + needs_input/blockers + status + age; sorts open assignments + rich tasks contexts for CoS/AM prompts). Still no full formal engine or plan-of-day output schema.
- Workspace consistency surface in CoS (Phase 4): basic note/context started (_consistency_context helper + daily briefing section; reuses persisted reports from checker + Sentinel QA hook). See TODO for more GDrive/single-doc.
- Memory retrieval is still primarily lexical/structured, with semantic/entity-aware enhancements still maturing.
- Delegation now has runtime scaffolding, but broader queue-backed execution still needs production hardening.
- Calendar write operations are available via explicit command, but broader scheduling optimization remains limited.
- Agent/assignment reflection summaries: support added (scopes + auto post-chat + prompt injection + CoS _memory_context + daily briefing). Sentinel/Lex bootstraps too.

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

### Example use case: Predicate search + Substantial Equivalence (SE) table for a medical device
You can give the CoS a goal in plain chat like:  
"Look for any predicates for my new [device description: e.g. AI-based ECG monitor with these indications and tech characteristics], and put them into a substantial equivalence table for me."

- CoS recognizes this as a high-level regulatory goal. It can propose a multi-agent "Work Plan" (WP-xxx) or you can direct specific agents ("research predicates with Atlas, then have Quill compile the SE comparison table, Sentinel do QA review").
- Simple client research questions (e.g. "I got this from Rich at iQSurgical: by when do we need to request FDA input to have a decision on non-Silent Mode study need by end Q3? 30/60 days? Will they decide in-meeting?") flow to the normal CoS LLM path. The model, with full context (dossier, reflections, active plans, etc.), either answers directly (using tools), does a lightweight single ASSIGN (to Pulse/Atlas), or (for true multi-agent coordination needs) emits PROPOSE_STAFF_PLAN: <goal>. The latter triggers the rich proposal with Mason consult etc.
- There are no keyword lists or phrase triggers left for deciding planning level. Intent detection is purely model-driven.
- Complex multi-agent deliverables keep the rich WP path (via model judgment).
- It breaks it down using available specialists:
  - Atlas (Deep Researcher): Spins up a Deep Research project, uses FDA/OpenFDA tools + web search to find relevant predicate 510(k)s, gathers summaries on indications for use, technological characteristics, etc. Attaches findings as artifacts/references.
  - Quill (Writer): Receives the research artifacts + your device details + any historical similar docs from memory. Drafts a professional SE table (and supporting sections) as a Workspace document using regulatory style.
  - Sentinel (QA/Compliance): Gets a snapshot for review (raised intel, consistency checks on the doc set if related-set generated, flags on contradictions or gaps vs predicates). Can be assigned to produce a review memo.
- Mason can coordinate milestones if it's part of a larger project.
- Pulse/Shield can be pulled in for any emerging regulatory signals or risks around the predicates.
- Proposals appear in CoS chat and the Assignments board (as "proposed").
- You approve (e.g. "approve WP-42" or individual proposals). Work is delegated; agents get rich briefs with context (prior reflections, attached research, client dossier).
- Execution: Agents work in their dedicated threads, produce artifacts (research package, draft .docx table, QA notes). They report progress via summaries and status updates.
- "Let me know when done" / visibility:
  - CoS board (Assignments pane) highlights agent tasks, especially "⚠️ NEEDS INPUT" or awaiting_review. Sort/filter by assignee/status. Detail pane shows full timeline, latest agent update, extracted questions, attached files/artifacts.
  - Open any assignee chat directly from board or CoS to review the output live.
  - Daily briefings and AM Sweep surface open high-prio agent work and active plan status.
  - Ask CoS in chat: "status on the SE table for device X", "checkpoint WP-42", or "any updates from Atlas on predicates?" — it pulls from work plan/assignment context and reports.
  - Work plans provide structured checkpoint reports with recent activity.
- Inspect & revisions:
  - Review the draft table in Workspace (linked via artifacts).
  - In agent chat: give specific feedback ("add a column for clinical data comparison", "use this additional predicate K-number", "tighten the equivalence discussion on power source").
  - CoS or direct agent can update the brief, re-run sections, or create follow-on assignments.
  - Upload additional files/artifacts if needed.
  - Update status (e.g. to in_progress or done) once satisfied.
  - Full audit trail in assignment events.
- When complete: Set status to "done"; the table/doc is in your Workspace/client folder (exportable to GDrive), artifacts attached, summary in CoS.

This workflow is supported today for regulatory tasks like this. It uses the general research + drafting + QA tools plus your device description + memory of past work. It won't be perfectly one-shot for a complex table (expect 1-3 iterations with the drafter/QA for precision on SE criteria), but the handoff, artifact passing, review loop, and oversight are built in.

See also: "What happens when CoS assigns work" above, and the Work Plans section in chat for coordinated multi-agent efforts.

## Keyword heuristics vs. LLM intent detection (audit note)

The CoS action system has two layers:

- **Structured explicit commands** (intentional and by design): ACTION_COMMAND_PREFIXES (~20 prefixes) + corresponding regex patterns (ASSIGN:, ADD_TASK:, all UPDATE_*/BULK_*, ADD_*, TASK_SET_*, APPROVE_PROPOSAL, etc.). These enable deterministic parsing/execution when the user or model uses the exact machine-readable syntax. Model is instructed to output them under "## Actions (machine)". This is the "API" for side effects; not fragile intent classification.

- **Natural-language / heuristic intent detectors** (use with care): 
  - Direct task capture (_user_requested_direct_dashboard_task_add, synthesize_add_task_line_from_user_text, _DASHBOARD_TASK_*_RE regexes with phrases like "add a task to", "remind me to", "create a task", "put this on my task list", "new task").
  - Delegation redirections (_handle_delegation_redirection: ~12 regex patterns for "delegate this to X", "give it to X", "have X handle", "route to X", etc.).
  - Plain approvals and work-plan commands (_handle_plain_proposal_approval with approval_triggers list; _handle_work_plan_* using re for "approve|delegate|revise|wp|plan|checkpoint").
  - Memory hint detection (_MEMORY_HINT_SUBSTRINGS ~19 phrases like "teach navi", "i prefer", "remember ", "client prefers" to decide whether to run extra extraction).
  - Routing in main_chat_router/response_handler ( "daily briefing", task creation keywords ['add','create',...], "WEB_SEARCH:", medtech+news).

The former staff-planning heuristic (large planning_signals + research bypasses) was the clearest example of the anti-pattern for *complex high-level intent* ("does this need full multi-agent Work Plan + Mason + approval gate?") and has been removed in favor of pure LLM-driven PROPOSE_STAFF_PLAN: marker.

Recommendation (now encoded in practice): For high-level behavioral branching and intent classification that affects whether rich coordination/proposals happen, use LLM + explicit output markers (PROPOSE_STAFF_PLAN, etc.) after providing full context, rather than expanding Python keyword lists. Structured syntax commands and small UX fast-paths (task entry, redirections after proposals) are exceptions. Audit any new ones against this.

See AGENTS.md for related discipline.

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
  - Usable guidance + basic heuristic scoring exists (see gaps: _compute_priority_score wired to contexts). Formal urgency/importance + plan-of-day schema still incomplete.
- [~] **Milestone 5 (Evaluation/regression safety)**
  - Strong CoS parser and DB regression coverage exists.
  - Broader scenario/e2e coverage can still be expanded.

### Next practical milestones

1. **Prioritization engine hardening**
   - Heuristic started (P+due+signals in CoS contexts). Next: formal urgency/importance + predictable plan-of-day schema.
2. **Delegation runner v2**
   - Add explicit background job execution model beyond command parsing.
3. **Evaluation harness**
   - Add curated scenario fixtures for CoS recommendation quality + tool safety regressions.

## Operational Notes
- Configurable paths (database, data directory, config directory, env file location) are defined in `core/settings.py`.
- CoS / AM Sweep context budgets, per-block caps, multi-turn history limits, and Grok output caps are edited from **Settings → App preferences** (`core/app_preferences.py`).
- Keep templates in `config/*.example.json` and keep real secrets out of git.
