# Intel Tab (Pulse)

**Status:** In active development (as of May 2026)

## Purpose

The Intel tab is a dedicated workspace for **market intelligence and regulatory intelligence**. It acts as a proactive specialist ("Pulse") that:

- Monitors topics you care about (your personal watchlist).
- Allows you to request research on specific subjects.
- Surfaces important findings with a visual indicator (badge on the tab).
- Lets you link intelligence to specific clients.
- Makes findings available to other agents (especially the Chief of Staff) when relevant.

The goal is to have an "analyst on staff" who watches the regulatory and competitive landscape and raises things you should see sooner rather than later.

## Current Capabilities

### Watchlist
- You maintain a list of topics/keywords directly in the tab.
- Each topic can have associated keywords and a priority (high/medium/low).
- The background monitoring job periodically checks these topics.

### Research Requests
- You can type a topic or question in the "Request Research" field.
- This creates a high-priority finding and automatically adds the topic to your watchlist.

### Findings
- Intelligence items are stored in Pulse’s private agent memory (`agent_memory` with `kind="intel_finding"`).
- Each finding includes:
  - Title and summary
  - Importance level
  - "Raised" flag (drives the tab badge)
  - Links to one or more clients
  - Free-form notes
- Findings can be promoted to global memory so Navi and the Chief of Staff can see them.

### Background Monitoring
- A recurring `intel_monitoring` job runs via the runtime system (every ~2 hours by default) once Runtime + Browser tools are enabled.
- The job performs real web searches (via Grok's native web_search tool) for each watch topic using its keywords.
- Findings are created only when substantive results are returned. High-priority topics and strong regulatory signals (FDA guidance, warnings, enforcement, etc.) are more likely to be raised.
- Pulse can also proactively surface high-signal items outside your explicit watchlist when they appear relevant to your practice/clients.
- You can force an immediate cycle from the Intel tab using the "Run Monitoring Now" button (very useful for testing).

### Badge & Visibility
- When findings are marked as "raised", the Intel tab shows a badge (`Intel ★ (n)`).
- The Chief of Staff only sees important Intel items when **you** review the Intel tab (no automatic pinging).

### Cross-Agent Access ("Poke Your Head In")
- Most intelligence requests from other agents go through the Chief of Staff (Tier 1).
- Limited direct queries (Tier 2) between agents are supported but kept narrow and are logged for review.

## Where It Lives

- **UI**: `gui/intel_tab.py` (`IntelTab`)
- **Service Layer**: `core/intel.py` (`IntelService`)
- **Agent**: Uses the `pulse` specialist agent
- **Storage**: `agent_memory` (kind = `intel_watch_topic` and `intel_finding`) + promotion to `user_memory` / client-linked memory when appropriate
- **Background Jobs**: `core/runtime/jobs.py` (`intel_monitoring` job type)

## Model Usage

- Intel monitoring and research requests use the heavy multi-agent model when appropriate.
- The left-side Navi chat uses a lighter model (`grok-latest`) via the `NAV_CHAT` role.

## Relationship to Other Tabs

- **Chief of Staff**: Primary consumer of Intel findings. When you are in the CoS tab and review the Intel tab, relevant intelligence becomes available for planning and delegation.
- **Deep Research**: Intel does *not* automatically trigger Deep Research. You or the CoS decide when a finding warrants a deeper research project.
- **Clients**: Findings can be explicitly linked to clients. Relevant intel can surface in a client’s dossier view.
- **Library**: Intel is kept separate (you decided Library could eventually be folded into Deep Research, but Intel should remain a distinct top-level tab).

## Future / Planned Work

- Real web/regulatory feed integration inside `run_monitoring_cycle()` (currently simulated with heuristics + model judgment).
- Smarter importance scoring and deduplication of findings.
- Deeper integration with the CoS so it can proactively pull recent raised Intel items during planning.
- Ability for other specialists to make scoped queries to Pulse (Tier 2 "direct poke" support).
- Better visualization of findings over time and trend detection.

## How to Use (Current)

1. Open the **Intel** tab.
2. Add topics to your watchlist (e.g. "FDA AI/ML Guidance", "reimbursement changes for SaMD", competitor names).
3. Use the **Research** field to request information on a specific topic.
4. Let the background `intel_monitoring` job run (or trigger it manually via the runtime).
5. Review raised findings (they appear with a badge on the tab).
6. Link important findings to the relevant clients.
7. When working in the Chief of Staff tab, check the Intel tab for any new signals.

---

*Last updated: May 2026*