# NaviSsurance User Manual

Last updated: 2026-05-12

## 1. What This App Is

NaviSsurance is a desktop operating system for consulting work. It combines daily planning, task/project tracking, AI-assisted drafting, meeting transcription, lead generation, compliance review, billing, and long-running working documents in one local app.

Use this manual as the practical "how do I do this?" guide. It focuses on the workflows you see in the UI rather than internal implementation details.

This manual now also notes a few optional advanced integrations so operators understand what may be enabled on a given machine.

Contributor/operator note:
- If you are trying to determine whether a behavior is current, planned, or historical, check `docs/contributor_guide.md` and `docs/roadmap_status.md` before relying on older plan files.

## 2. Getting Started

### Open the app
- Launch NaviSsurance.
- Wait for the main window and tabs to finish loading.

### Optional advanced services
Some installations may also start optional services in the background:
- a runtime scheduler for queued or recurring work
- a local API for non-GUI integrations

If these are not enabled, the main desktop workflows should still function normally.
The intended user chat surface is still the built-in desktop chat, not a remote messaging app.

### Main navigation
You will see top-level tabs for:
- `Dashboard`
- `Tasks`
- `Workspace`
- `Deep Research`
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

### Navi chat vs Chief of Staff chat
- On most tabs, the app shows a persistent left-side `Navi Chat` panel.
- The `Chief of Staff` tab has its own dedicated chat workspace, so the global left-side chat panel is hidden there.
- Tasks created from chat should still flow into the same shared task database used by `Dashboard` and `Tasks`.

### Best way to start each day
1. Open `Dashboard` to review your briefing, schedule, tasks, email queue, and news.
2. Open `Chief of Staff` to plan the day, delegate work, or run `AM Sweep`.
3. Open `Tasks` if you need to clean up the backlog in bulk.

## 3. Dashboard

Use `Dashboard` as your daily command center.

### What is on the page
- `Daily Briefing` for a quick planning summary.
- `Today's Schedule` from your calendar.
- `Task List` for the same local tasks used elsewhere in the app.
- `Unreplied Emails` for follow-up triage.
- `News Feed` for MedTech, AI, and regulatory updates.

### Typical dashboard routine
1. Read `Daily Briefing`.
2. Check `Today's Schedule` for hard constraints.
3. Review the task list, starting with overdue and due-today work.
4. Clear `Unreplied Emails`.
5. Scan `News Feed` for anything that may affect clients or priorities.

### Task list fast path
- Use filters to narrow by category and date.
- Add a quick task from the inline add row.
- Use row actions to edit, snooze, complete, or delete.
- Archive completed tasks when you want to reduce noise.

### Notes
- `Refresh` forces a new briefing.
- `Refresh News` forces a news refresh.
- If calendar or email access is missing, these panels should degrade gracefully instead of crashing.

## 4. Tasks And Projects

Use `Tasks` for direct task management and project tracking.

### Task list
The main task page supports:
- search,
- category filtering,
- date filtering (`All`, `Today`, `Overdue`, `No Date`, `Specific Date`),
- project filtering,
- sort options,
- toggles for completed and snoozed tasks.

### Quick add
- Enter the task title.
- Choose `Business` or `Personal`.
- Enter a due date manually in `MM-DD-YYYY` format, or use the `Date` picker button.
- Click `Add`.

### Task fields you will see
- priority,
- tags,
- next action date,
- due date,
- category,
- linked project,
- completion state.

### Common task actions
- mark complete or undo completion,
- edit task details,
- snooze a task,
- delete a task,
- refresh the filtered list.

### Projects subtab
The full `Tasks` page also includes a `Projects` subtab.

Use it to:
- create and edit projects,
- set project deadlines,
- update project status,
- connect tasks to projects,
- review project timelines and Gantt-style views.

### Tip
If a task was created from `Chief of Staff`, `Workspace`, `Meetings`, or `Leads`, it should also appear here because those workflows share the same underlying task store.

## 5. Chief Of Staff

`Chief of Staff` is the main planning, delegation, and executive-control interface.

### What it is best for
- plan-of-day conversations,
- prioritization,
- task capture,
- assignment management,
- specialist-agent delegation,
- calendar-aware planning,
- memory-aware planning,
- AM Sweep morning triage.

### Layout
The tab has two main sidebar areas:
- `Chats` for separate CoS conversations.
- `Assignments` for the delegation board.

### Everyday use pattern
1. Start or open a CoS chat.
2. Ask for planning help, prioritization, or delegation.
3. Review assignments in the board.
4. Check the assignment row and detail pane for `NEEDS_INPUT`, the latest agent update, and any requested files or answers.
5. Open assignee chats when needed.
6. Upload requested files from the agent console if the assignee asks for documents.
7. Convert key assignments into dashboard tasks.

### Options menu
The `Options` menu includes:
- `AM Sweep`
- `AM Sweep (Run again)`
- `Preferences…`
- `Review Pending Memory…`
- `Global Memory…`
- `Action Commands…`

### Preferences
Use `Preferences…` to store planning constraints and behavior preferences such as:
- blocked time windows,
- scheduling constraints,
- other durable CoS planning rules.

These preferences are meant to influence CoS responses without requiring you to repeat them every time.

### AM Sweep
`AM Sweep` is a morning triage workflow that collects context and organizes work into four buckets:
- `Dispatch`
- `Prep`
- `Yours`
- `Skip`

Use it when you want a more structured start-of-day pass than normal chat.

### Action command cheatsheet
Most users can stay in natural language, but the app also supports explicit action formats. The built-in `Action Commands…` reference is the best place to copy exact syntax if you need deterministic behavior.

Common examples:
- `ADD_TASK`
- `ADD_CAL_BLOCK`
- `ASSIGN`
- assignment update commands for status, priority, due date, title, brief, and summary
- bulk assignment commands
- assignment-to-task commands

### Assignment board
The `Assignments` tab is the delegation board.

It supports:
- creating assignments manually with `New`,
- opening an assignee chat,
- reassigning work,
- bulk status, priority, due-date, and reassignment changes,
- exporting the board,
- filtering by `Open only` or `All`,
- filtering by status, health, follow-up state, assignee, and search text.
- surfacing `NEEDS_INPUT` when the latest agent reply is asking you for answers or uploads.
- a sortable table layout so you can sort by assignment id, status, needs input, priority, assignee, due date, health, or title.

### Assignment detail actions
After selecting an assignment, you can:
- `Start`
- set priority
- set due date
- mark `Awaiting Review`
- `Block`
- mark `Done`
- `Cancel`
- `Reopen`
- edit the title
- edit the brief
- edit the summary
- `Create Task`
- `Bulk Create Tasks`
- `View Artifact`
- `Open Assignee Chat`

### Reading agent follow-up from the board
When an assignee has already replied in their linked thread, the assignment detail pane now shows:
- `Needs input: yes/no`
- `Latest agent update`
- `Requested from you` lines when the agent asks questions or requests files
- `Uploaded files` already attached to that assignment

Use this before opening the assignee tab if you just want to know whether the agent is blocked on you.

### Sorting and filtering the board
- Click a column header to sort the delegation board.
- Use `Follow-up: Needs Input` when you want to see only assignments currently waiting on you.
- Use `Follow-up: No Input Needed` when you want to see work that is not blocked on your reply or uploads.
- The board now remembers your current sort, column widths, and active filters between sessions.

### Supplying documents to an agent
If the assignee asks for source material:
1. Select the assignment.
2. Click `Open Assignee Chat`.
3. In the agent console, click `Upload Artifact`.
4. Choose one or more files.

The uploaded files are attached to the assignment, stored as artifacts, and shown back on the CoS assignment detail pane.

### Bulk result counters
When CoS or the board reports bulk changes, pay attention to counts such as:
- `matched`
- `eligible`
- `changed`
- `unchanged`
- `skipped closed`
- `failed`

If `changed=0`, nothing was actually updated.

## 6. Memory And Teaching

NaviSsurance now has layered memory that can influence future prompts and assignment work.

### Memory layers you should know about
- `Global memory`
  - user-wide facts, preferences, aliases, and shared reference knowledge for Navi
- `Chief of Staff memory`
  - planning-oriented memory used by CoS
- `Agent memory`
  - durable private memory for one named specialist such as `Atlas` or `Quill`
- `Assignment memory`
  - task-local working memory tied to one assignment or thread

### What counts as memory
The app can store:
- durable facts,
- preferences,
- aliases and glossary terms,
- client or project-specific conventions,
- other stable reference information that should survive beyond one chat.

### Explicit memory capture
Use explicit teaching commands when you want to save something intentionally.

Examples:
- `Teach Navi: I prefer deep work before noon.`
- `Teach Navi: PMCF means post-market clinical follow-up.`
- `Teach Atlas: Acme means Acme Biotech.`
- `Teach Quill: Prefer the client's template language unless told otherwise.`

Alias or glossary entries are stored in a more structured way when Navi can detect the term and meaning clearly.

### How the layers behave
- `Teach Navi:` writes approved memory into Navi's global memory.
- `Teach <Agent>:` writes approved memory into that named agent's durable memory.
- Direct agent chats can also learn passively into their own agent memory.
- Assignment-specific work can create short-horizon task-local memory that stays attached to the assignment unless promoted upward.

### Reviewing memory
Open `Global Memory…` from `Chief of Staff`.

That dialog can now inspect:
- `Global` memory
- `Agent` memory
- `Assignment` memory

From there you can:
- search entries,
- filter by status, scope, source, and agent,
- add memory manually,
- edit selected memory,
- approve pending memory,
- reject memory,
- delete memory,
- promote agent memory into Navi global memory,
- promote assignment memory into durable agent memory.

### Pending memory review
- Auto-learned memory may enter a `pending` review state before it starts influencing prompts.
- If pending items exist, you will see a review prompt in the CoS UI such as `Review pending memory`.

### Practical guidance
- Use `Teach Navi:` for anything you definitely want remembered globally.
- Use `Teach <Agent>:` when the learning should belong to one specialist only.
- Review pending memory regularly so weak or noisy auto-learned entries do not accumulate.

## 7. Workspace

Use `Workspace` for professional document production and collaborative drafting from your source files + historical work. It is the main "production engine" for regulatory deliverables (plans, reports, matrices, etc.).

### What you can currently do
- Add source files/folders (PDF, DOCX, MD, TXT) via Select, Add Folder, or drag-and-drop. Mark items in scope. Preview content.
- See auto-retrieved "Relevant Historical Documents" from your archive (strong matches by type/client/topic). Double-click or use context menu to inject as references. These are automatically used for style/structure guidance during generation (Phase 1 retrieval fully active here).
- Choose **Prompt Templates** (e.g. CEO Strategy Memo, Board Update, Product Brief → Plan) or custom instructions in the prompt box.
- Choose **Document Templates** (structured .docx-based from your templates folder) for fill-in-the-blanks style output with LLM assistance.
- Click **Generate Draft**: Runs dual-LLM collaboration (Grok primary + ChatGPT review) with full reference pack from sources + historical cluster. Streams into Grok/ChatGPT panes + editable Markdown. Supports outline + section generation, revisions via natural language.
- For complex regulatory work: In the "Relevant Historical Documents" list, right-click a strong cluster (ref + related matches) and select **"Generate Related Set (presets...)"**. It:
  - Uses presets for common companions (e.g. Validation Plan + Risk Management File + Traceability Matrix).
  - Reuses the *exact same historical cluster* for all companions (style, structure, references, consistency).
  - Auto-starts generation for the set members.
  - Produces: Related Set Manifest (traceability note), Summary, Cross-References subsection in "Historical Sources Used", and runs Consistency Checker (reports contradictions, scope drift, etc. across the set).
- Saved Workspaces: "Save" / "Save As…" full session state (files, generated content, related-set metadata, consistency reports, billing artifacts, templates used). Later reload restores everything including set companions and reports. List of saved workspaces in the UI.
- Exports:
  - Save Markdown.
  - Export as... (DOCX, PDF via integration, etc.).
  - Quick-export to client folder (auto-includes manifest, summary, cross-refs, consistency report, billing summary for sets).
  - GDrive auto-upload toggle (persisted): when enabled, related-set exports + all artifacts go to client folder on GDrive.
  - Export Question Packet.
- **Generate Billing Summary for Set** (from historical list menu, after Generate Related Set or strong cluster): Produces lightweight billing artifact (time/deliverables snapshot + cluster style notes) without full invoice. Auto-included in exports.
- Consistency: Post-generation for sets (and now enhanced single-doc intra-review). Reports visible in saved state, exports, and surfaced in CoS/briefings.
- Extract Suggested Tasks from the draft (review/import to Tasks tab).
- Full traceability: Generated docs include "Historical Sources Used" with Related Document Set Cross-References listing companions and cluster.
- Integration: Send research from Deep Research tab. Delegate drafting/review to sub-agents (Quill etc.) via CoS. Link to clients/projects. Use with CoS for planning.
- Templates system: Discover/import structured templates with machine tags for fields; preview, validate, render to DOCX.

### Typical advanced workflow (Phase 4 production)
1. Pull strong historical refs in the list (auto or from prior).
2. Right-click → Generate Related Set (uses preset + cluster).
3. Review companions auto-generating with shared context + consistency report.
4. Save as workspace (full state preserved).
5. Quick-export (or GDrive) → client folder gets doc + manifest + summary + consistency report + cross-refs.
6. Optionally Generate Billing for Set → included in export.
7. Use in CoS (surface reports, delegate fixes to Sentinel).

### When to use Workspace vs Deep Research
- Use `Workspace` when your main inputs are files/folders you already have (or historical archive) and you want polished, traceable client deliverables (especially sets of related docs).
- Use `Deep Research` when you need external web research first (it can feed into Workspace).

The Workspace is heavily focused on MedTech regulatory work (FDA-style docs, consistency, traceability, client-folder exports). All Phase 4 elements (historical reuse, related sets, consistency, GDrive) are actively wired and usable.

## 8. Deep Research

Use `Deep Research` for web-first research runs that produce a final brief.

### What you can do here
- name a research run,
- enter a research objective or question,
- let the app gather research artifacts,
- review intermediate outputs,
- provide optional focus notes,
- generate a final brief,
- export the final brief.

### Main workflow
1. Enter a `Research name`.
2. Enter the `Research objective / question`.
3. Decide whether `Auto-generate final research brief when research completes` should stay enabled.
4. Click `Start deep research`.
5. Wait for the pipeline to finish and review:
   - `Web brief`
   - `Grok synthesis`
   - `ChatGPT synthesis`
6. Add optional focus or constraints.
7. Click `Generate final research brief` if auto-generation did not already run.
8. Review the `Final research brief (markdown)`.
9. Use `Export brief...` if you want a file version.

### Notes
- The status line and progress bar show research progress while the run is active.
- The tab also includes an optional direct chat area for `Atlas (Deep Researcher)`.
- Web research requires `OPENAI_API_KEY` to be configured.

## 9. Meetings

Use `Meetings` to record, transcribe, save, and mine meetings for follow-up tasks.

### Main controls
- `Start Recording`
- `Stop Recording`
- `Generate Transcript`
- `Load File`
- `Save Transcript`
- `Draft Tasks`

### Recording workflow
1. Click `Start Recording`.
2. Click `Stop Recording` when finished.
3. The app saves the audio file locally and starts the transcription flow.
4. Enter meeting metadata when prompted:
   - meeting date,
   - meeting with,
   - notes.

### File-based workflow
Use `Load File` if you want to transcribe an existing audio or video file instead of recording live.

### Transcript workflow
- Use `Generate Transcript` when a file is loaded and ready.
- Review the transcript in the transcript pane.
- Use `Save Transcript` when you want a portable copy.

### Saving transcripts
`Save Transcript` supports:
- plain text (`.txt`)
- Word (`.docx`)

### Drafting tasks from a meeting
Use `Draft Tasks` to turn the transcript into proposed tasks.

This is a review-first flow:
- suggested tasks are drafted first,
- you review and edit them,
- only accepted tasks are imported into the task database.

### Recording note
If live recording is unavailable, the tab should explain that the `sounddevice` package is missing. In that case, you can still use `Load File`.

## 10. Compliance

Use `Compliance` to compare documents or URLs against compliance expectations and generate a structured report.

### Typical workflow
1. Add source material such as a document or URL.
2. Run the compliance check.
3. Review the structured output.
4. Save the report if needed.

### What to expect
- This tab is best for document review and issue identification.
- Saved reports are intended to be human-readable.

### Current caveat
`Link to CRM` should not be treated as a working end-to-end integration yet. If you need CRM linkage, verify it manually in your current environment.

## 11. Leads

Use `Leads` for evidence-first lead discovery and outreach tracking.

### What it does
- finds candidate leads,
- stores only leads with evidence,
- shows scores so you can prioritize,
- gives you a personalized outreach draft,
- supports follow-up task creation.

### Main workflow
1. Run a lead search.
2. Review stored leads in the table.
3. Use filters for status, score, and hide-contacted behavior.
4. Open `Sources` to inspect evidence and signals.
5. Open the message viewer if you want a suggested outreach draft.
6. Edit status, next action date, and notes as needed.
7. Use `Create Task` to schedule outreach follow-up.

### Important note
Lead storage is intentionally strict: no evidence means no saved lead.

### Outreach note
The app supports manual outreach support and follow-up scheduling. It is not the place to assume direct LinkedIn message sending is automated.

## 12. Billing

Use `Billing` to track time, manage invoice templates, and generate invoice drafts for review.

### What the tab includes
- client selection and client records,
- timer-based and manual time entry,
- invoice template management,
- DOCX editing support,
- grouped invoice draft generation,
- Word-first review and PDF export,
- monthly in-app auto-draft prompts.

### Template workflow
You can:
- create a new template,
- import a template,
- edit a DOCX template with `Edit DOCX…`,
- save template changes,
- `Auto-wire` common placeholders,
- mark a template as default with `Set default`.

### Draft generation workflow
1. Select a client.
2. Log or review billable time entries.
3. Choose the billing mode:
   - `Hourly (rate × hours)`
   - `Fixed fee (% of total)`
4. Set the invoice period with `Generate previous month` or the custom date range.
5. Optionally enable `Set due date`. If you leave this off, the draft uses `Due upon receipt`.
6. Generate the draft.
7. Review the draft in the preview panel.

### Draft review actions
For a selected draft, you can:
- `Edit draft…`
- `Export PDF…`
- `Refresh preview`
- `Open file…`
- `Save As…`
- `Mark reviewed`

### What billing fields are supported
Current invoice data supports:
- incrementing invoice numbers in the `PM####` format,
- billing contact name,
- billing email,
- optional due date,
- grouped line items by deliverable or category,
- hourly billing,
- fixed-fee billing,
- fixed-fee allocation by percentage across grouped work.

### Important review-first note
Treat invoice drafts as editable drafts, not send-ready invoices. The intended flow is:
1. generate the draft,
2. open it in Word,
3. review formatting and content,
4. export PDF only after the draft looks right.

Depending on the template, final cleanup may still be required before sending.

### Monthly auto-draft
The tab includes `Monthly auto-draft (in-app)` settings:
- enable or disable it,
- choose the day of the month,
- review the prompt when the app generates drafts.

## 13. Team

Use `Team` to inspect the AI team directory and jump into agent-specific work.

### Common uses
- review an agent's capabilities,
- inspect aliases and open assignments,
- open the agent workspace,
- jump to the next assignment for that agent.

## 14. Notes

The `Notes` tab is now a live document builder, not a loose-note inbox.

### Core idea
Each work context becomes one living document. As you add raw observations, Navi merges them into the active context document and keeps reorganizing the content into something more coherent.

### Typical workflow
1. Create or select a context in the left sidebar.
2. Use the capture box to enter a raw observation.
3. Press `Enter` to merge it into the active document.
4. Use `Shift+Enter` if you need a newline in the capture box.
5. Review the updated document in the main editor.
6. Use `Save Document` when you manually edit the document.
7. Use `Re-organize` when you want Navi to clean up the current document without adding a new observation.
8. Use `Export…` to create an external file.

### What exports do here
Exports operate on the active compiled context document, not on a list of raw note rows.

### Supported export formats
- Word (`.docx`)
- Markdown (`.md`)
- PDF (`.pdf`)

## 15. Library, Intel, And Security

These tabs are lighter-weight specialist workspaces.

### `Library`
Use this as an archive and retrieval workspace for institutional knowledge and previously gathered material.

### `Intel`
The **Intel** tab (powered by the Pulse specialist) is a dedicated workspace for ongoing market and regulatory intelligence.

**Core features**
- Maintain a personal **watchlist** of topics and keywords (e.g. “FDA AI/ML Guidance”, specific competitors, reimbursement changes).
- Request research on any topic directly from the tab.
- Background monitoring runs periodically (via the runtime system) and creates findings when relevant developments are detected.
- The system can raise findings that match your watchlist **or** that the model judges important even if they fall outside your explicit topics.
- Important findings appear with a badge on the tab (`Intel ★ (n)`).
- Findings can be linked to one or more clients.
- You can add private notes to any finding.

**How it behaves**
- Treat Pulse like a proactive analyst: it monitors, flags what looks important, and waits for you to review.
- The Chief of Staff only sees new Intel items when **you** open the Intel tab (no automatic alerts to CoS).
- Other agents can request scoped intelligence from Pulse (usually routed through CoS, with limited direct “poke” queries supported).

**Typical workflow**
1. Add topics to your watchlist.
2. Occasionally request research on a specific question.
3. Check the Intel tab when it shows a badge.
4. Review raised findings, link them to clients, and add notes.
5. When working in the Chief of Staff tab, open Intel to pull in any relevant signals for planning.

See the dedicated guide: [docs/intel.md](intel.md)

### `Security`
Use this for security and privacy risk triage.

### Practical guidance
- **Intel** is now a full dedicated workspace with watchlists, background monitoring, and client linking. It is intended to feel like a proactive specialist who raises important signals.
- **Library** and **Security** are still lighter specialist workspaces (they remain as focused `AgentTab` interfaces for now).
- These tabs become most powerful when used together with the Chief of Staff for planning and delegation.

## 16. Exports

Several parts of the app can export user-facing artifacts.

### Notes
- `DOCX`
- `Markdown`
- `PDF`

### Workspace
- `DOCX`
- `PDF`
- `Markdown`
- `TXT`

### Deep Research
- `DOCX`
- `PDF`
- `Markdown`
- `TXT`

### Meetings
- transcript save supports `TXT`
- transcript save supports `DOCX`

### Billing
- invoice drafts are edited and saved as document files,
- you can export a selected draft to `PDF`.

### Export guidance
- Prefer `DOCX` when you expect to keep editing in Word.
- Prefer `PDF` for a fixed-share version after review.
- Prefer `Markdown` when you want an editable text-based draft.
- Prefer `TXT` for simple transcript or plain-text sharing.

## 17. Dates And Formats

Dates matter across `Dashboard`, `Tasks`, `Projects`, `Billing`, `Meetings`, and `Chief of Staff`.

### Where calendar pickers exist
Calendar-popup date pickers are used in many major places, including:
- dashboard date filtering and quick task dates,
- task editing and project deadlines,
- billing entry ranges, invoice periods, and invoice due dates,
- meeting metadata,
- assignment due-date pickers in CoS dialogs.

### Manual date formats to remember
- dashboard or task due dates often use `MM-DD-YYYY`
- assignment due dates use `YYYY-MM-DD`

If a date is rejected, double-check which workflow you are in before retrying.

## 18. Troubleshooting

### A task created from CoS is not visible
- Open `Tasks` and clear filters and search text.
- Check whether category, project, completed, or snoozed filters are hiding it.

### An assignment command says it changed something, but nothing moved
- Review the returned counters such as `changed`, `unchanged`, and `failed`.
- If `changed=0`, no actual update happened.

### I cannot open the assignee chat from an assignment
- Select the assignment first.
- Retry from the `Chief of Staff` assignment board.
- If needed, verify that the assignee has a routed specialist workspace in the current build.

### The agent says it needs documents or answers
- Select the assignment and read the `Agent follow-up` section in the detail pane.
- If the board shows `NEEDS_INPUT`, open the assignee chat and use `Upload Artifact` for files.
- Reply in the agent console thread if the agent asked clarification questions.

### Date entry keeps failing
- Assignment due dates must be `YYYY-MM-DD`.
- Task due dates commonly expect `MM-DD-YYYY`.
- Use the calendar picker when available instead of typing the date manually.

### Calendar-aware planning is not working
- Verify your calendar token is available in the app environment.
- If it is missing, CoS should fall back gracefully, but it will not have live schedule context.

### Live meeting recording is unavailable
- Install `sounddevice`, or use `Load File` to transcribe an existing recording instead.

### Deep Research will not start web research
- Check that `OPENAI_API_KEY` is configured.

### Billing draft output does not look ready to send
- Use `Edit draft…` to open the invoice in Word.
- Review formatting, branding, line items, and totals before exporting PDF.
- Treat draft generation as a starting point, not a final send action.

### Compliance CRM linking did not happen
- Treat `Link to CRM` as incomplete unless you have separately verified it in your current environment.

## 19. Recommended Daily Routine

1. `Dashboard`: read briefing, schedule, tasks, email queue, and news.
2. `Chief of Staff`: plan the day, delegate work, and run `AM Sweep` if needed.
3. `Tasks`: clean and reorder the backlog.
4. `Workspace`, `Deep Research`, `Meetings`, or another specialist tab: do focused execution.
5. `Notes`: capture conclusions into living context documents.
6. `Billing`: keep time entries current so invoice generation stays clean later.

## 20. Related Docs

If you want a deeper companion reference, use:
- `docs/overview.md`
- `docs/chief_of_staff.md`
- `docs/staff_replacement_matrix.md`
- `docs/note_taking_system.md`
- `docs/lead_generation.md`
- `docs/testing.md`
