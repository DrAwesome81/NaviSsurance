# Project Review - 2026-06-15

**Purpose**: Reset and structured review of NaviSsurance. Document use cases and user stories from the user's perspective, then map them to current implementation to identify status, gaps, and priorities.

**Context**: This is a fresh discussion document. We will capture real-world use cases and stories, write them here, then cross-reference against the live app (code, UI, features in core/, gui/, docs/consultant-os-roadmap.md, etc.).

**Date**: 2026-06-15  
**Participants**: User + Grok (following AGENTS.md rules: main Dropbox paths only, read/grep first, smallest-safe, Update Rule for docs, etc.)

---

## Use Cases

(High-level scenarios describing what the user does with the system. Populated iteratively from discussion.)

### Intelligence & Research (Pulse / Intel)
- Use the Intel tab primarily for chatting with Pulse, requesting research (paste URL/article/question or tell CoS "have Pulse look into this [brief]"), and reviewing previous chat threads. Get structured research summary with findings, sources, dates, implications.
- Research tasks save full outputs (structured summaries, key points, sources, artifacts) viewable in a dedicated sub-tab for reviewing the complete results of each task.
- Browse and manage all stored intel in a separate sub-tab: search the full index, edit any info/tags/client links/notes, link to clients/projects. All intel is indexed (primary mechanism) for on-demand discoverability by subagents or CoS when the user asks about a topic/brief/client.
- Set up watch topics for regulatory areas/clients. Receive proactive alerts/findings when new signals appear (FDA guidance, enforcement, etc.). New intel is indexed automatically for later retrieval.

### Planning & Delegation (CoS)
- Tell CoS what you're working on ("two submissions for Client X, plus audit prep"). CoS suggests task breakdowns and priorities, time blocks around calendar, assignments to specialists (Pulse research, Quill drafting, Sentinel QA, Mason coordination), etc., using all available intel, due dates, priorities, and other factors. It needs to consider multiple factors for the plan.
- Use plain language delegation: "give this research to Pulse" or "assign the table draft to Quill". System creates proposed assignment with rich brief (including any prior intel/memory), auto-activates thread/handoff for named agents, and tracks status.
- Approve/revise plans can be done in chat, but plans should also be viewable and editable in a sub-tab. CoS should also be able to see emails and review those as well as part of its planning. CoS should also be able to edit my calendar. See progress in CoS assignments pane (needs-input flags, latest agent updates), Intel sub-tabs (research outputs and stored intel), assignment threads, emails, and calendar.
- Ask follow-ups like "what did Pulse find on the predicates?" and get grounded answers from actual saved findings/artifacts, not synthesis.

### Document Production (Workspace)
- Start a new deliverable (e.g., Validation Plan, SE table, submission section). Mark relevant historical documents or client files as context.
- Generate draft using real past work for style/structure/consistency (auto historical ref injection). Iterate with dual-LLM or agent assistance.
- For complex work, generate related document sets (multiple companions sharing cluster). Run consistency checks across them. Export full pack (docs + manifest + summary + cross-refs + any consistency/billing artifacts) to local client folder and/or GDrive.
- Review generated output in context of client dossier or CoS.

### Client & Project Management
- Maintain client dossier as single hub: recent activity, projects, assignments, tasks, indexed/stored intel (research findings), relevant past documents, compliance notes.
- Link findings, time, documents, and intel directly to clients/projects.
- Track project deliverables, status, deadlines, billing mode (hourly vs fixed). See utilization and open work at a glance.

### Tasks, Calendar & Billing
- Capture tasks naturally in chat or UI. Assign to categories, projects, agents, due dates, estimates, recurrence, blockers.
- See and act on tasks in Dashboard, Tasks tab (with ID visibility for references), CoS board. Mason or CoS can propose/update via structured commands.
- Schedule or view calendar blocks. Have CoS suggest time blocks for "Yours" work based on calendar + priorities.
- Log time (manual or suggested from work). Generate client invoices from entries/deliverables using branded templates. Export to client folders.

### Memory, Continuity & Learning
- Teach facts/preferences/aliases explicitly ("Teach Navi: Client prefers...").
- Have passive extraction from conversations, meetings, assignments into memory layers (global, agent private, assignment-local).
- Retrieve and use layered memory automatically in the right contexts (CoS, agents, dossiers, generation). Promote high-value items deliberately.
- Review/edit memories with control. See continuity via reflections.

---

## User Stories

(As a [role], I want [goal] so that [benefit]. Populated iteratively.)

### Intelligence & Research
- As the founder, I want to request research on a specific URL or topic via the Intel tab or CoS chat ("have Pulse look into this") so that I get structured findings with sources/dates/implications. The Intel tab is for Pulse chat, research requests, and previous threads; full research task outputs are reviewable in a dedicated sub-tab, and all intel is stored/indexed in another sub-tab where I can browse, search, and edit info, tags, client/project links, etc. (indexed for on-demand retrieval by CoS/subagents).
- As the founder, I want proactive monitoring on regulatory topics/clients so that important new signals are indexed and stored as intel (viewable in the stored intel sub-tab and discoverable via retrieval) without me constantly searching.

### Chief of Staff & Delegation
- As the founder, I want to describe what I'm working on in plain language to CoS so that I get a clear breakdown, task capture, calendar time-blocking suggestions, and delegation opportunities mapped to specialists.
- As the founder, I want plain-language delegation ("give this to Pulse", "assign the draft to Quill") to reliably create assignments with rich briefs, dedicated threads, handoff, execution, status tracking, and results surfaced in Intel/CoS without manual follow-up.

### Workspace & Document Generation
- As the founder, I want to start generating a regulatory document (or set) with context from my real past work and client files so that the output matches my style, reuses structure, maintains consistency, and includes traceability (manifest, sources, cross-refs).
- As the founder, I want generated deliverables (single or related sets) exported with full supporting pack directly to the client's folder (local + optional GDrive) so that I have a complete, ready-to-use deliverable without manual assembly.

### Tasks & Daily Execution
- As the founder, I want to capture and manage tasks (with IDs visible for references, blockers, estimates, assignments, recurrence) across chat, dashboard, and dedicated tab so that work is organized, visible, and actionable without duplication or lost details.
- As the founder, I want CoS or agents to propose or update tasks/calendar blocks via natural language or structured output so that my plan stays current with minimal manual entry.

### Memory & Context
- As the founder, I want explicit and passive memory capture (teach commands, conversation extraction, meeting notes) layered by scope (global, agent-private, assignment-local, client/project linked) so that relevant context is automatically available where needed without repetition.
- As the founder, I want to review, promote, or edit memories so that I retain control while benefiting from continuity and retrieval in CoS, agents, generation, and dossiers.

### Client & Project Management + Billing
- As the founder, I want a living client dossier that aggregates activity, intel, documents, tasks, assignments, billing status, and relevant past work so that I have a single source of truth per client without manual assembly.
- As the founder, I want time tracking and invoice generation tied to projects/clients/deliverables (using real templates) so that billing is accurate, low-friction, and exportable to client folders.

---

## Next Steps

- Populate use cases and stories from discussion.
- Map each to current app (e.g., "Implemented in X", "Partial in Y", "Gap: Z").
- Identify priorities for Phase 4 / next work.
- Update relevant living docs (roadmap_status.md, TODO.md) only after code/docs changes per rules.

---

*This document is for this review session. Content will be added iteratively based on discussion.*