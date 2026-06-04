# AGENTS.md — NaviSsurance

**Purpose**: This file captures the project's hard rules, conventions, non-negotiables, and development discipline for any agent (Grok, Cursor, human contributor using AI tools, etc.) working on the codebase. It exists so future work stays consistent with how the app was intentionally built.

Last updated: 2026-06 (post CoS/Intel thread + business plan merge)

## Project Vision & Mental Model
NaviSsurance is a **desktop-first, local-first Consultant Operating System** for MedTech regulatory work (AI/ML SaMD, IVD/LDT focus). 

The core vision (from `docs/consultant-os-roadmap.md`): It functions like **"a small, highly competent team"** working exclusively for the solo founder. Key pillars:
- Deep layered memory of clients, past work, and decisions.
- Proactive intelligence (Pulse / Intel tab).
- Planning, delegation, and coordination (Chief of Staff).
- High-quality document production (Workspace) that intelligently reuses real historical work.
- Native billing, tasks, compliance, leads, etc.

**Primary user surface**: The built-in desktop chat + tabs (especially Chief of Staff for delegation and Intel for monitoring). Remote chat integrations are not part of the active roadmap.

See also:
- `docs/overview.md`
- `docs/consultant-os-roadmap.md` (the **fixed** 5-phase plan — do not deviate)
- `docs/design.md`
- `docs/user_manual.md`

## Source of Truth Order
Follow `docs/contributor_guide.md` exactly:
1. Current **code** (running implementation wins).
2. Current architecture/status docs (`docs/overview.md`, `docs/design.md`, `docs/api.md`).
3. `docs/roadmap_status.md` + `TODO.md`.
4. Testing/operational docs.
5. Historical plans only as reference (never as active spec unless explicitly called out in roadmap_status or TODO).

**Update Rule** (from contributor_guide.md): When making meaningful changes:
- Update **code first**.
- Then update the relevant docs (overview, design, api, testing.md, roadmap_status.md, TODO.md).
- Never treat unchecked paragraphs in old plans as active work.

## Core Non-Negotiables (Do Not Violate)

### 1. Intel / Pulse Retrieval Layer — 100% Local-Only (Absolute)
- The **entire** Intel retrieval, indexing, search, relevance scoring, synthesis, compression, and context formatting system **must be 100% local**.
- No remote models, no APIs (Grok, ChatGPT, etc.), no "downstream remote" hedging, no fallback language that leaves any role for remote in this subsystem.
- The `intel retrieval layer itself will never make a remote call`.
- Authoritative data stays in `agent_memory` (kind="intel_finding"). `core/intel_retrieval.py` is a **derived, self-contained local index only**.
- Must remain functional after initial model download with no further network access for the intel path.
- Use the dedicated local stack: SentenceTransformer (with `local_files_only=True`, `HF_HUB_OFFLINE=1` guards), isolated Chroma `intel_index/`, local LLM profiles (`intel_batch_digest`, etc.).
- **Testing requirement**: All representative public-path tests **must** pass under `INTEL_DISABLE_VECTOR=1`. Use non-vacuous asserts on real gold-standard paths (`save_finding` → public `retrieve_relevant_intel*` → ranking/synthesis). See `tests/test_intel_retrieval.py` and the IMPL 93ed7923 history.
- Defensive guards: Raised/high-importance items are **never** silently dropped.
- Strict output budgets: small, predictable, high-signal context (modeled on `core/file_handler.py:format_compact_historical_context` — tiny metadata-only lines, never raw content).
- See: `core/intel_retrieval.py` (header + plan.md in logs for full constraints), `docs/intel.md`, `core/intel.py`.

**Any change that touches intel relevance/synthesis must re-verify the local-only invariant and run the representative tests.**

### 2. Chief of Staff UI — "At Most Two Vertical Panes Per Tab" (Ruthlessly Enforced)
- Explicit user rule: **At most two vertical panes for any given tab**. No exceptions for accretion.
- CoS sidebar: ruthlessly limited to what is actually used for delegation (Chats + Assignments).
  - Chats tab: one primary list pane.
  - Assignments tab: **exactly two vertical panes via QSplitter**:
    - Top (Delegation Board): workload chips (if any), compact filters, assignment table, one clean horizontal action row.
    - Bottom (Staff Results): large readable details pane + clean action bar (Export Results | Add to Memory | Link to Project/Client | Open Assignee Chat).
- Remove/hide legacy clutter on sight: Suggested, Work Plans, permanent Raised Intel + Shield noise, Relevant Past Documents, micro-button groups, old sub-tabs, View Memories button at top, etc. These can only be reintroduced on explicit request.
- Right-click context menu on assignment table (keeps everything to the two-pane discipline).
- The "Assignments" section main visible pane must focus on tasks that **require input** (needs-input / blocked / follow-up), not a full historical list.
- History/proposed plans behind dropdowns, never always-present.
- See the prominent `NOTE` and implementation in `gui/chief_of_staff_tab.py:2500` (and surrounding `_build_sidebar` / assignment layout code). Many comments reference "per the two-pane rule".
- Changes that affect CoS layout must preserve (or strengthen) this mental model of "real delegable staff via plain-language chat + clean board/results".

### 3. Development & Change Discipline (Smallest-Safe, Representative, Verifiable)
- **Smallest-safe diffs / micro-increments only**. Prefer the tiniest edit to an existing file. No over-engineering, no speculative abstractions, no polish outside the exact task.
- **Generally prefer editing an existing file** to creating a new one (prevents bloat, builds on existing work).
- Do not create new source files unless absolutely necessary.
- After **any** change: run the relevant tests (especially representative public paths). Verify it actually works — run the test/script and check the output. "Minimum complexity means no gold-plating, not skipping the finish line."
- Use **representative / gold-standard paths** for new logic (especially ranking, retrieval, delegation, memory):
  - Exercise the real public API flows (e.g., `save_finding` → `retrieve_relevant_intel*` for Intel; full assignment creation + handoff + results for delegation).
  - Provide **non-vacuous** evidence (asserts that would actually fail on broken behavior; position evidence, measurable deltas, etc.).
  - "Representative public delegation path", "gold path", "non-vacuous proof".
- **Chained smallest-safe micro-increments** with full reuse of existing patterns and defensive style.
- Read/grep first. Explore before editing (`list_dir`, `read_file`, `grep`).
- For complex/multi-step work: use `todo_write` tool to track (mark completed immediately when done; one in_progress at a time).
- For genuine ambiguity or high-impact restructuring: use `enter_plan_mode` / `exit_plan_mode` (explore, propose plan, get approval before coding).
- Before claiming "done" on any task: actually verify (run the thing, inspect output). If no test exists for a claim, say so explicitly.
- "Defensive" implementation: never break existing writes/flows; graceful fallbacks; handle missing optional deps (e.g., onnxruntime for Intel vectors → keyword fallback).

### 4. Roadmap & Scope Discipline
- The 5-phase plan in `docs/consultant-os-roadmap.md` is **fixed and approved**. Follow the order.
- Highest-leverage remaining work is Phase 4 (Workspace Production Engine + historical reference injection + consistency).
- Use `docs/roadmap_status.md` (current classification) and `TODO.md` (active backlog) as the living trackers.
- Services-first business plan (June 2026 in `business-plan/`) prioritizes using the app internally for bizdev capacity + Phase 4 for measurable time savings. Changes should support (or at least not contradict) that.
- No scope creep. "Keep going" loops must stay within the approved plan + explicit user direction.

### 5. Memory, Retrieval, and Layering
- Respect the layered memory architecture (`user_memory`, `cos_memory`, `agent_memory`, `assignment_memory`).
- Promotion paths exist and should be used deliberately.
- Retrieval must be summary-first / compact where possible; respect strict context budgets in CoS (see app preferences and `_apply_cos_context_budget`).
- Historical document references (Phase 1/4) are high-value — surface and inject them cleanly (see `core/file_handler.py`, workspace, clients, CoS).

### 6. Testing & Verification
- Follow `docs/testing.md`:
  - Automated regression first (`python -m pytest -q` or focused suites).
  - Qt/UI tests often require `RUN_QT_TESTS=1` (and are intentionally limited on this Windows setup).
  - Representative / E2E paths for delegation, memory, runtime, Intel, etc.
- For Intel changes: always run under `INTEL_DISABLE_VECTOR=1` + full representative suite.
- Many behaviors (runtime, browser, some CoS flows) have deterministic automated coverage — use it.
- Manual smoke is for GUI judgment, live services, restart semantics, and subjective quality only after automated passes.
- "Verify it actually works" — do not rely on "it should be fine."

### 7. Documentation & Communication
- Code change → docs update (per contributor_guide Update Rule).
- When using `/implement` or subagent skills: follow the project's rigor (smallest-safe, tests, representative paths, clean exit only on 0 open issues from reviewers where applicable).
- Logs, timing, and diagnostics (e.g., `PULSE_DIAGNOSTIC`) are valuable for debugging but keep user-facing surfaces clean.
- Business context: The June 2026 plan (`business-plan/`) is the current growth blueprint. 90-day actions are meant to be executed *inside* the app (CoS + Intel + Workspace).

## Practical Workflow for Agents
1. Start every significant task by reading the relevant source-of-truth docs + `AGENTS.md` + key code.
2. Use exploration tools liberally.
3. For anything non-trivial: create a todo list.
4. Make the smallest possible safe change.
5. Run targeted tests + representative verification.
6. Update docs if the change is meaningful.
7. Verify end-to-end where possible (run the app flow, inspect artifacts, check logs).
8. If layout/UI: double-check the two-pane rule and prune ruthlessly.
9. If touching Intel: re-assert 100% local + run the vector-disabled tests.
10. Document what you did (in commit message, summary, or code comments) with file:line references.

## Things That Have Historically Caused Pain (Avoid)
- Feature accretion in CoS sidebar (leads to "fucking disaster" cluttered UIs and massive cleanup debt).
- Introducing any remote dependency or language into the Intel retrieval path.
- Large refactors without representative tests or breaking existing flows.
- Treating old plans as current spec without checking roadmap_status/TODO/code.
- Skipping verification ("it looks good in the diff").
- Using expanding hardcoded keyword/phrase lists in Python for high-level user *intent classification* or complex routing decisions (e.g. "is this a broad multi-agent coordination goal requiring a Work Plan?"). The LLM (with full context) should decide via natural output or explicit markers (e.g. PROPOSE_STAFF_PLAN:). Structured exact command syntax (ADD_TASK:, ASSIGN: and friends) is the deliberate exception for deterministic execution. See chief_of_staff.md audit note.

## References
- `docs/contributor_guide.md` (source of truth + update rule — read this first)
- `docs/consultant-os-roadmap.md` (fixed plan)
- `docs/roadmap_status.md` + `TODO.md` (live status)
- `docs/testing.md`
- `docs/intel.md` + `core/intel_retrieval.py` (local-only details)
- `gui/chief_of_staff_tab.py` (two-pane rule + current CoS implementation)
- `business-plan/` (current growth context — services-first, Phase 4 priority)
- Historical context from the long CoS/Intel development thread (preserved in `previous_thread_logs/` when present) for the "why" behind many rules (CoS simplification, Intel purity, smallest-safe discipline, representative testing). Treat as history that shaped the current invariants; the rules themselves are now encoded here and in the code/docs.

This file should be updated when new hard rules emerge from user direction or painful lessons.

---

*Maintained so agents can do ambitious work without repeatedly re-learning the project's hard-won constraints.*