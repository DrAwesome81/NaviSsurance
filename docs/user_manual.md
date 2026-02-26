# NaviSsurance User Manual

Last updated: 2026-02-25

## 1) What This App Is

NaviSsurance is a desktop app for day-to-day consulting operations: planning, tasks, AI assistant workflows, document work, compliance review, lead generation, and notes.

This manual is written as a practical reference so you can quickly find how to do a specific action.

## 2) Getting Started

### Open the app
- Launch NaviSsurance.
- Wait for the main window and tab bar to load.

### Main navigation
- You will see top-level tabs such as:
  - `Dashboard`
  - `Tasks`
  - `Workspace`
  - `AI Projects`
  - `Compliance`
  - `Meetings`
  - `Leads`
  - `Billing`
  - `Library`
  - `Intel`
  - `Security`
  - `Team`
  - `Notes`
  - `Chief of Staff`

### Where to start each day
1. Open `Dashboard` for current tasks/schedule/news.
2. Open `Chief of Staff` for planning, delegation, and assignment control.
3. Open `Tasks` to batch-clean task list if needed.

## 3) Dashboard

Use this as your daily command center. It gives you one place to triage work, review what is time-sensitive, and decide where to execute next.

### What the Dashboard does
- Shows a `Daily Briefing` (top panel) with a concise summary and suggested next actions.
- Shows `Today's Schedule` from calendar events.
- Embeds your task manager (`Task List`) so task actions stay consistent with the `Tasks` tab.
- Shows `Unreplied Emails` to surface messages needing follow-up.
- Shows a `News Feed` focused on MedTech/AI/regulatory relevance with cached storage and repeat suppression.

### Dashboard layout (at a glance)
- **Top:** `Daily Briefing` with a `Refresh` button.
- **Left column:** `Today's Schedule` and `Task List`.
- **Right column:** `Unreplied Emails` and `News Feed`.
- **Bottom-right action:** `Refresh News`.

### How to use the Task List (fast path)
1. Scan highlighted due items first (overdue/due-today stand out visually).
2. Use filters to narrow by category/date and include completed or snoozed items when needed.
3. Add quick tasks directly from the row at the bottom (`task`, `due date`, `category`, `recurrence`, then `Add`).
4. Use row actions (for example edit/snooze/delete where shown) to clean and reprioritize quickly.
5. Archive completed tasks when you want to reduce noise.

### How to use Daily Briefing
- On load, briefing auto-runs (unless briefing/email is disabled in config).
- Use `Refresh` to force a newly generated briefing.
- Treat this section as your “what needs attention now” summary before diving into deep work.

### How to use Today's Schedule
- Review today’s event list and timing blocks at startup and after major plan changes.
- The schedule auto-refreshes periodically, so you can leave Dashboard open during the day.
- If no events appear, the panel explicitly says no events are scheduled.

### How to use Unreplied Emails
- Use this queue to catch pending conversations quickly.
- Keep `Only clients/leads` enabled for business-priority focus, or disable it for a broader view.
- Use `Mark replied` after you respond so the queue stays accurate.
- Use `Email rules…` to adjust classification behavior.

### How to use News Feed
- Use `Refresh News` for an immediate update, or let it refresh automatically.
- Tune duplicates with `Hide repeats` (1/2/3/7 days).
- Tune density with `Max items` (5/8/10).
- Open article links directly from the feed for full context.
- If live fetch is unavailable, cached news is still used when possible.

### Recommended dashboard routine (3–5 minutes)
1. Read `Daily Briefing`.
2. Check `Today's Schedule` for hard time constraints.
3. Triage `Task List` (overdue, then due today, then upcoming).
4. Clear or flag `Unreplied Emails`.
5. Scan `News Feed` for changes that affect client or regulatory decisions.

## 4) Tasks Tab

Use this for direct task management in local SQLite storage.

### Common actions
- Add a task quickly.
- Filter tasks by status/date/category.
- Search by text.
- Mark complete/incomplete.
- Delete tasks.

### Tip
- If you created a task from CoS actions, it should appear here as well since it is the same task store.

## 5) Chief of Staff (CoS)

This is the main AI planning/delegation interface.

### What it does
- Conversational planning and prioritization.
- Create/update assignments for specialist agents.
- Bulk assignment actions.
- Convert assignments into dashboard tasks.
- Optional calendar block creation commands.

### Everyday use pattern
1. Ask for plan-of-day.
2. Delegate work (single or bulk).
3. Review assignment board.
4. Open assignee chat from assignment when needed.
5. Track results and convert key assignments to dashboard tasks.

### Assignment board basics
- Filter by status, assignee, and search text.
- Click an assignment to see details/timeline.
- Use board actions for status/priority/due/reassign updates.

### Open assignee chat from board
- Select an assignment.
- Use the action to open assignee console.
- The app will switch tabs and focus that assignment in the agent console if available.

## 6) CoS Command Cheatsheet

Use exact formats when entering explicit action commands.

### Task and calendar
- `ADD_TASK: <task description> | <MM-DD-YYYY or none> | <Business or Personal>`
- `ADD_CAL_BLOCK: <title> | <start datetime> | <end datetime> | <calendar id or primary>`

### Assignment create/update
- `ASSIGN: <AgentName> | <Title> | <Brief> | <P1-P5> | <YYYY-MM-DD or none>`
- `UPDATE_ASSIGNMENT_STATUS: <A-0007 or 7> | <queued|in_progress|awaiting_review|blocked|done|cancelled> | <optional note>`
- `UPDATE_ASSIGNMENT_PRIORITY: <A-0007 or 7> | <P1-P5> | <optional note>`
- `UPDATE_ASSIGNMENT_DUE: <A-0007 or 7> | <YYYY-MM-DD or none> | <optional note>`
- `REASSIGN: <A-0007 or 7> | <AgentName> | <optional note>`

### Bulk assignment commands
- `BULK_UPDATE_ASSIGNMENT_STATUS: <status> | <AgentName or all> | <open or all (optional)> | <optional note>`
- `BULK_UPDATE_ASSIGNMENT_PRIORITY: <P1-P5> | <AgentName or all> | <open or all (optional)> | <optional note>`
- `BULK_UPDATE_ASSIGNMENT_DUE: <YYYY-MM-DD or none> | <AgentName or all> | <open or all (optional)> | <optional note>`
- `BULK_REASSIGN_ASSIGNMENTS: <AgentName or all> | <AgentName target> | <open or all (optional)> | <optional note>`

### Assignment/task conversion
- `ADD_TASK_FROM_ASSIGNMENT: <A-0007 or 7> | <MM-DD-YYYY or none> | <Business or Personal>`
- `BULK_ADD_TASKS_FROM_ASSIGNMENTS: <AgentName or all> | <Business or Personal> | <open or all (optional)>`

### How to read bulk status results
Bulk status command notes now report deterministic counts:
- `matched`: rows in scope
- `eligible`: rows considered after mode filter
- `changed`: rows actually persisted to target value
- `unchanged`: rows already at target value
- `skipped closed`: rows skipped because `open` mode excludes done/cancelled
- `failed`: attempted rows that did not persist

If `changed=0`, no status mutation happened.

## 7) Team Tab

Use this to inspect agent metadata and navigate to an agent workspace.

### Common actions
- Select an agent to view aliases/capabilities/open assignments.
- Open agent workspace.
- Open next assignment for selected agent.

## 8) Workspace

Use this for document-centered drafting with one primary action: `Generate Draft`.

### What Workspace does
- Lets you add and preview source files.
- Lets you mark exactly which files are in scope for the draft.
- Runs an AI collaboration workflow to produce a Markdown draft from your prompt.

### Typical workflow
1. Open the `Workspace` tab.
2. Click `Select File/Folder` (or drag/drop files into the file list).
3. Mark files to include using the checkbox next to each file.
4. Optionally click a file to preview extracted content.
5. Set `Max Rounds` (how many review/refinement cycles to allow).
6. Click `Generate Draft`.
7. Enter your instruction prompt when asked (what to draft, format, tone, constraints).
8. Review:
   - `Grok (API)` pane for research/drafting output,
   - `ChatGPT (API)` pane for review/edit feedback,
   - `Markdown Document` pane for the current draft.
   - Status line for a context coverage note (how many selected files were fully/partially included).
9. Edit the markdown manually if needed.
10. Save using `Save Markdown` or `Export as...`.

### Prompting tips
- Be specific about audience, structure, and desired output length.
- Ask for explicit sections (for example: summary, risks, recommendations, next steps).
- If no files are marked, Workspace can still generate a research-only draft from your prompt.

## 9) Compliance

Use to analyze documents/URLs against compliance standards.

### Common actions
- Upload or provide source content.
- Run compliance analysis.
- Review structured issues/fixes output.

## 10) Leads

Use for discover/verify lead workflows and follow-up tasking.

### Common actions
- Generate/refine lead lists.
- Review evidence/scoring.
- Create follow-up tasks.

## 11) Notes

Use for AI-assisted notes and export.

### Common actions
- Capture notes during work.
- Organize with AI formatting/categorization.
- Export (for example to DOCX/TXT/PDF where available).

## 12) AI Projects / Specialist Tabs

Tabs such as `AI Projects`, `Billing`, `Library`, `Intel`, and `Security` host specialist agent consoles or workflows.

Use them when:
- CoS routes you to a specific assignee console.
- You want to work directly in that domain area.

## 13) Troubleshooting

### Assignment command says updated but nothing changed
- Check command note counters (`changed`, `failed`, `unchanged`).
- `changed=0` means no mutation occurred.
- Verify assignment ID/scope/mode and retry.

### Cannot open assignee chat from assignment
- Select assignment first.
- Ensure assignee has a routed console tab.
- Retry from `Chief of Staff` assignment board.

### Task not visible after creating from CoS
- Open `Tasks` tab and clear filters/search.
- Confirm category/date filters are not excluding it.

### Due date errors
- Use exact expected format:
  - Assignment due: `YYYY-MM-DD`
  - Dashboard task due: `MM-DD-YYYY`

## 14) Recommended Daily Routine

1. `Dashboard`: triage tasks and schedule.
2. `Chief of Staff`: generate plan and delegate.
3. Specialist tabs: execute deep work or review assignee outputs.
4. `Tasks`: close loop on outstanding work.
5. `Notes`: capture outcomes and export if needed.

## 15) Related Technical Docs

If you need implementation details or test specs, see:
- `docs/overview.md`
- `docs/chief_of_staff.md`
- `docs/testing.md`
- `docs/requirements.md`
