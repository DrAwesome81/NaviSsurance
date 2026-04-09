# Roadmap Status

Last updated: 2026-04-03

## Purpose
This document is the visible roadmap/status companion to `TODO.md`. It exists so the repo has one current place to classify active, implemented, and historical roadmap work without requiring contributors to inspect private or historical plan files first.

## Current status categories

### Implemented and now part of the app baseline
- Chief of Staff assignment and delegation workflows
- AM Sweep
- durable memory and memory reflections
- layered memory with global, CoS, per-agent, and assignment-local scopes
- explicit `Teach <Agent>:` plus promotion paths between memory layers
- summary-first long-term retrieval
- Deep Research workflow
- Billing draft generation and exports
- Notes document workflow
- runtime scaffolding
- local API scaffolding
- browser tool scaffolding
- dormant Telegram integration scaffolding (not active roadmap direction)

### Active follow-up areas
- broader runtime hardening and real-world validation
- deeper browser-backed workflows
- more mature entity-aware and semantic retrieval
- agent/assignment reflection summaries and broader memory UX polish
- observability and operational controls for optional runtime/API surfaces
- performance work, especially CoS latency and duplicate calls

### Current product-direction note
- Built-in desktop chat is the intended user chat surface.
- Remote chat integrations are not part of the active roadmap unless explicitly revived later.
- Navi and CoS now act as supervisory readers across layered memory, while direct agents remain isolated to their own durable memory plus task-local memory by default.

### Historical or superseded planning themes
- older multi-agent strategy plans that predate the current implementation
- duplicate or overlapping roadmap files that described the same architectural direction before the current runtime/tooling work landed
- feature-spec docs that remain useful as design references but are not the canonical description of shipped behavior

## Reconciled legacy plan set

### Historical / implemented reference
- `finish_out_roadmap_beb6198a.plan.md`
- `ceo-first_go-to-market_from_current_code_3a186856.plan.md`

### Superseded / duplicate architecture plans
- `multi-agent_ai_ops_plan_86a81439.plan.md`
- `multi-agent_ai_ops_plan_86add018.plan.md`

These remain useful as historical strategy/spec material, but they no longer describe the current architecture accurately enough to drive implementation work.

### Verification-candidate plan
- `fix_dual_llm_workflow_document_visibility_dd58cd2a.plan.md`

This plan should only be reopened if the underlying Workspace document-visibility bug still reproduces on the current codebase.

### Non-core or deferred product direction
- `freeinputsta-news-fundamentals-optionsplan_560ce259.plan.md`
- `freedatainputsmarketintelligence_70fa83af.plan.md`

These are not part of the current NaviSsurance core roadmap and should be treated as historical or deferred unless that product direction is intentionally revived.

## Canonical references
- `TODO.md`: operational backlog and remaining work
- `docs/runtime_operator.md`: env flags, recurring jobs, and local API verification
- `docs/overview.md`: current product baseline
- `docs/design.md`: architecture baseline
- `docs/api.md`: local API plus third-party integrations
- `docs/testing.md`: current validation path
- `docs/chief_of_staff.md`: CoS and delegation behavior
- `docs/contributor_guide.md`: source-of-truth guidance for contributors

## How to use this document
- Use this file for status classification.
- Use `TODO.md` for actionable remaining work.
- Use the architecture and feature docs for implementation truth.
- Treat older plan files as history unless they are explicitly reflected here or in `TODO.md`.
