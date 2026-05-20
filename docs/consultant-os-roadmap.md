# NaviSsurance – Consultant Operating System
## Comprehensive Implementation Plan (Approved)

**Status:** Approved – Fixed Plan  
**Date Approved:** May 2026  
**Owner:** Grok (executing)

---

## 1. Vision & Guiding Principles

**Vision**  
NaviSsurance becomes a single, intelligent workspace that functions like a small, highly competent team working exclusively for you. It maintains deep memory of your clients and past work, proactively monitors the regulatory and competitive environment, helps you plan and prioritize, captures time and revenue cleanly, and dramatically accelerates the creation of high-quality client deliverables by intelligently reusing your real historical work.

**Guiding Principles**
- One coherent system, not a collection of loosely connected tabs.
- Memory and retrieval are first-class citizens (this is the foundation).
- The system should reduce context switching and administrative overhead.
- Proactive intelligence is valuable, but never annoying.
- Billing and time tracking must feel native and low-friction.
- All file intelligence must work cleanly across Google Drive (primary) and Dropbox (archive) without creating duplicate or confusing artifacts.
- The architecture must support gradual, safe expansion without requiring constant rework.

---

## 2. Overall Architecture

### Core Layers

| Layer                    | Responsibility                                      | Primary Interface          | Key Agents / Components          |
|--------------------------|-----------------------------------------------------|----------------------------|----------------------------------|
| **Source of Truth**      | Clients, Projects, Deliverables, Assignments        | Client Dossier + Projects  | Database + rich UI               |
| **Intelligence**         | Watching, raising signals, regulatory/market context| Pulse tab + CoS sidebar    | Pulse agent                      |
| **Coordination**         | Planning, prioritization, synthesis, daily briefing | Chief of Staff tab         | Chief of Staff agent             |
| **Production**           | Document generation using real memory + templates   | Workspace                  | Workspace engine + retrieval     |
| **Operations**           | Time, billing, revenue tracking, invoicing          | Billing tab                | Billing service                  |
| **Memory & Retrieval**   | Unified understanding of files + past work          | Global search + agents     | RAG/Indexing + Metadata service  |
| **Automation**           | Background monitoring, reminders, health checks     | Runtime + Jobs             | Scheduler + agent jobs           |

**Cross-cutting concerns:** Model routing, global search, activity feed, consistent UX, data model hygiene.

### Recommended Agent Specialization
- **Chief of Staff** — Generalist coordinator and planner (heavy model)
- **Pulse** — Regulatory/market intelligence specialist (private agent_memory)
- Future candidates: Regulatory Writer, Billing Assistant, Compliance Monitor (added only when clearly justified)

---

## 3. Detailed Feature Breakdown by Area

### 3.1 Client & Project Hub (Source of Truth)

**Core Functions**
- Rich client profiles with billing mode (Hourly vs Deliverable), default rate, billing contact, notes, and regulatory context.
- Project management with deliverables, status, deadlines, priority, and links to clients.
- Assignment system (tasks owned by you or tracked for clients).
- Ability to link findings, time entries, documents, and intel directly to clients or projects.
- Per-client views showing recent activity, open deliverables, raised intel, billing status, and relevant files.

**Recommended Enhancements**
- “Client Health” summary card (upcoming deliverables, billing status, recent intel, open risks).
- Quick capture of notes, decisions, or action items from within the dossier.
- Ability to mark projects as “Regulatory Critical” or “High Revenue” for prioritization.

### 3.2 Chief of Staff

**Core Functions**
- Natural language planning and task management.
- AM Sweeps and daily/weekly planning.
- Visibility into raised Intel from Pulse.
- Ability to create projects, assignments, and link work to clients.
- Context-aware responses using recent activity, raised findings, and billing state.

**Recommended Enhancements**
- Structured daily briefing that includes: Raised Pulse items, upcoming billing events, open high-priority deliverables, and suggested focus areas.
- “What should I work on today?” command with reasoned suggestions.
- Ability to delegate lightweight tasks to Pulse (e.g., “research recent FDA guidance on X”).

### 3.3 Pulse / Intelligence Layer

**Core Functions**
- Watchlist management (Topics + Keywords).
- Background monitoring (every 2 hours via runtime) using real web search.
- Creation of findings with importance scoring and raising capability.
- Manual research requests.
- Linking findings to clients/projects.
- Notes on findings that persist.
- Badge on the Intel tab when items are raised.

**Recommended Enhancements**
- Smarter raising logic using both keyword signals and model judgment.
- Ability for Pulse to maintain its own private memory of regulatory themes and client-specific implications.
- Periodic “Regulatory Pulse Report” that can be reviewed in CoS.
- Support for competitive and standards monitoring in addition to regulatory.

### 3.4 Billing & Time Operations

**Core Functions**
- Client-level billing mode: Hourly or Deliverable-based.
- Time entry (manual + timer) with optional links to projects and deliverables.
- Deliverable/SoW item management for deliverable-based clients (name, amount, status: pending/ready/invoiced).
- Invoice draft generation using your actual branded DOCX templates.
- Proper invoice numbering and history.
- Support for both time-based and fixed-amount line items in the same system.

**Recommended Enhancements**
- Semi-automatic time suggestions based on CoS work and assignment activity.
- Retainer health view (for deliverable clients) showing progress against monthly or project totals.
- One-click invoice generation from Project or Client Dossier.
- Multiple branded templates with per-client defaults.
- Revenue and utilization reporting.

### 3.5 Workspace & Document Generation

**Core Functions**
- Template-based document generation using your real DOCX templates.
- Ability to provide source documents and objectives.
- Outline review + section generation workflow.
- Output in DOCX/PDF.

**Recommended Enhancements (Critical)**
- Intelligent retrieval of relevant past documents (by client, document type, regulatory topic, etc.).
- Automatic suggestion of strong historical examples when starting a new document.
- Ability to generate related document sets together (e.g., Validation Plan + Risk Management File + Traceability Matrix).
- Strong consistency checking across generated sections.
- Direct export of finished documents into the correct client folder in Google Drive.

### 3.6 Memory & File Intelligence (Foundation Layer)

This is the most important structural addition.

**Required Capabilities**
- Reliable connection to both Google Drive (active) and Dropbox (archive).
- Clean ingestion pipeline that never creates confusing duplicate files.
- High-quality text extraction (especially PDFs) with layout awareness where possible.
- Automatic and manual metadata enrichment (client, project, document type, date, regulatory relevance, version).
- Powerful semantic + keyword search across all indexed documents.
- Ability for Workspace, CoS, and Pulse to retrieve relevant documents as context.

**Recommended Features**
- Global search that can find clients, projects, documents, findings, and notes together.
- “Relevant Past Work” surfaces in Client Dossier and Workspace.
- Smart filing suggestions for new files dropped into Google Drive.
- Clear separation between source files and any processed/indexed representations.

### 3.7 Security & Compliance Surface

**Recommended Scope**
- Per-client compliance status and key documents (Design History File status, risk management, clinical evidence, etc.).
- Gap tracking and audit readiness views.
- Ability to link regulatory findings and standards updates to specific compliance areas.
- Calendar of upcoming standards or regulatory deadlines.

(Decision needed during execution: dedicated tab vs powerful module inside Client Dossier + CoS.)

### 3.8 Automation & Runtime

- Background jobs via APScheduler (already working).
- Intel monitoring job.
- Future jobs: retainer health checks, compliance calendar alerts, periodic memory indexing, daily briefing preparation.

### 3.9 Global UX & Navigation

**Recommended Features**
- Global search (Ctrl+K style) across everything.
- Unified activity feed or “Today’s Context” view.
- Strong keyboard navigation and tab switching.
- Consistent visual language across all major areas.
- Ability to quickly jump from a raised Intel item to the related client/project.

---

## 4. Phased Implementation Plan (Approved Order)

**Phase 0 – Foundation & Cleanup**  
- Dropbox diagnostic + cleanup tooling (full functionality + safe move mode).
- Google Drive read access + file listing.
- Unified document ingestion + metadata extraction pipeline (clean, no duplicate artifacts).
- Basic global indexing foundation.

**Phase 1 – Memory & Retrieval Core**  
- Robust document understanding and retrieval system.
- Ability for Workspace, CoS, and Pulse to query relevant past documents.
- “Relevant Past Work” surfaces.
- High-quality PDF handling and metadata inference.

**Phase 2 – Billing Depth**  
- Deep integration of time entries and deliverables with Projects.
- Semi-automatic time capture suggestions.
- Retainer health dashboards.
- Improved invoice generation from multiple entry points.
- Multiple template support.

**Phase 3 – Intelligence & Coordination**  
- Mature Pulse with better raising and private memory.
- Structured proactive briefings in CoS.
- Security/Compliance surface (tab or module).
- Stronger cross-linking between Intel, Projects, and Billing.

**Phase 4 – Workspace Production Engine**  
- Strong retrieval of historical examples during generation.
- Support for generating related document sets.
- Consistency checking.
- Direct export into Google Drive client folders.

**Phase 5 – Organization Intelligence & Polish**  
- Smart filing suggestions.
- High-quality global search.
- Personal dashboards and reporting.
- Absorption or retirement of the separate FileOrganizer app.
- General UX and performance polish.

---

## 5. Cross-Cutting Decisions (to be handled during execution)

- Level of proactive behavior (daily briefings, notifications).
- Whether Security/Compliance becomes a dedicated top-level tab.
- Degree of time-tracking automation.
- Number of supported branded invoice templates.

---

## 6. Success Criteria

The system will be considered successful when:
- You can reliably find relevant past work across Google Drive and Dropbox with minimal effort.
- Workspace regularly suggests and uses your real historical documents when generating new client deliverables.
- Billing feels like a natural extension of project work rather than a separate chore.
- Pulse surfaces genuinely useful regulatory and competitive signals that influence your planning.
- The Chief of Staff has enough context and memory to give high-quality daily/weekly guidance.
- Administrative overhead (time tracking, invoicing, file hunting, context switching) is noticeably reduced.

---

**This document is the fixed reference for implementation.**

All development will follow the vision, layers, features, and phased order described above.