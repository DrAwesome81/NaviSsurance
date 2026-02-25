# NaviSsurance Testing Results Log

Record the **result** and **date** for each test item. Aligned with [testing.md](testing.md).

- **Result:** `Pass` | `Fail` | `Skip` | `Pending` — what you type after running the test.
- **Date:** YYYY-MM-DD (when the test was run).
- **Description:** Short summary of the test (for reference; see [testing.md](testing.md) for steps).
- **Notes:** Optional run-specific note you add (e.g., failure reason, "56 passed", environment).

---

## Chief of Staff + Executive Team Regression

*Ref: testing.md § Chief of Staff + Executive Team Manual Regression*

### Fast smoke (10–15 min)

| Test ID        | Result  | Date       | Description                          | Notes |
|----------------|---------|------------|--------------------------------------|-------|
| TC-054         | Pending |            | CoS chat persistence                 |       |
| TC-058         | Pending |            | CoS task capture                     |       |
| TC-COS-001     | Pending |            | Delegation command + board visibility |       |
| TC-COS-004     | Pending |            | Open assignee chat routing           |       |
| TC-COS-007     | Pending |            | Bulk board action                    |       |
| TC-COS-010     | Pending |            | Assignment health filter             |       |

### Current CoS / Delegation test cases

| Test ID        | Result  | Date       | Description                               | Notes |
|----------------|---------|------------|-------------------------------------------|-------|
| TC-COS-001     | Pass    | 2/24/26    | Create assignment from CoS chat           |       |
| TC-COS-002     | Pass    | 2/24/26    | Update assignment fields from CoS chat    |       |
| TC-COS-003     | Pass    | 2/24/26    | Reassign assignment from CoS chat         |       |
| TC-COS-004     | Fail    |            | Open assignee chat from board             | Could not open assignee tab in this context      |
| TC-COS-005     | Pass    | 2/24/26    | Create assignment manually from board     |       |
| TC-COS-006     | Pass    | 2/24/26    | Single assignment task bridge             |       |
| TC-COS-007     | Pass    | 2/24/26    | Bulk status update with optional note     |       |
| TC-COS-008     | Pass    | 2/24/26    | Bulk priority update with optional note   |       |
| TC-COS-009     | Pass    | 2/24/26    | Bulk due update with optional note        |       |
| TC-COS-010     | Pass    | 2/24/26    | Assignment health filter + badges         |       |
| TC-COS-011     | Pass    | 2/24/26    | Bulk reassign with optional note           |       |
| TC-COS-012     | Pass    | 2/24/26    | Bulk create tasks from filtered assignments |       |
| TC-COS-013     | Fail    | 2/24/26    | CoS bulk command open-mode semantics      | Chat says it updated it, but it didn't      |
| TC-COS-014     | Pass    | 2/24/26    | Due-date validation (chat and UI)          |       |

### Automated test runs

| Command / suite | Result  | Date       | Description                          | Notes |
|-----------------|---------|------------|--------------------------------------|-------|
| `pytest tests/test_chief_of_staff.py -q` | Pending |            | 56 selected (2 deselected)           |       |
| `pytest tests/test_cos_memory.py tests/test_db.py -q` | Pending |     | 1 passed, 1 skipped (test_db legacy) |       |
| `pytest tests/test_chief_of_staff.py -q -m qt` | Pending |        | Qt-marked tests only                 |       |

---

## Legacy manual catalog

*Ref: testing.md § Legacy manual catalog. Fill in Result and Date as you run each.*

### Dashboard tab

| Test ID | Result  | Date       | Description                 | Notes |
|---------|---------|------------|-----------------------------|-------|
| TC-001  | Pending |            | Dashboard task list display |       |
| TC-002  | Pending |            | Dashboard task completion   |       |
| TC-003  | Pending |            | Dashboard schedule display   |       |
| TC-004  | Pending |            | Dashboard news feed          |       |
| TC-005  | Pending |            | Dashboard auto-refresh       |       |

### Workspace tab

| Test ID | Result  | Date       | Description                  | Notes |
|---------|---------|------------|------------------------------|-------|
| TC-006  | Pending |            | Workspace file tree           |       |
| TC-007  | Pending |            | Workspace document preview    |       |
| TC-008  | Pending |            | Workspace analysis tools      |       |

### Note-taking system

| Test ID | Result  | Date       | Description              | Notes |
|---------|---------|------------|--------------------------|-------|
| TC-009  | Pending |            | Context setting          |       |
| TC-010  | Pending |            | Note formatting          |       |
| TC-011  | Pending |            | Dynamic categorization   |       |
| TC-012  | Pending |            | Export functionality     |       |
| TC-013  | Pending |            | Robust JSON parsing      |       |
| TC-014  | Pending |            | Thread-safe UI updates   |       |
| TC-015  | Pending |            | Notes session routing    |       |

### Chat and task management

| Test ID | Result  | Date       | Description                          | Notes |
|---------|---------|------------|--------------------------------------|-------|
| TC-015  | Pending |            | Chat response (duplicate ID in source) |       |
| TC-016  | Pending |            | Chat search                          |       |
| TC-017  | Pending |            | Daily briefing                       |       |
| TC-018  | Pending |            | Add task from chat                   |       |
| TC-019  | Pending |            | Add multiple tasks from chat         |       |

### Task list

| Test ID | Result  | Date       | Description                        | Notes |
|---------|---------|------------|------------------------------------|-------|
| TC-020  | Pending |            | Task list edit button              |       |
| TC-021  | Pending |            | Task list delete button            |       |
| TC-022  | Pending |            | Task list archive completed        |       |
| TC-023  | Pending |            | Task list persistence              |       |
| TC-024  | Pending |            | Task list visibility in briefing   |       |

### Tasks tab (local)

| Test ID | Result  | Date       | Description                      | Notes |
|---------|---------|------------|----------------------------------|-------|
| TC-045  | Pending |            | Tasks tab initialization        |       |
| TC-046  | Pending |            | Tasks tab quick add              |       |
| TC-047  | Pending |            | Tasks tab complete/undo + delete |       |

### Leads tab

| Test ID | Result  | Date       | Description                     | Notes |
|---------|---------|------------|---------------------------------|-------|
| TC-025  | Pending |            | Leads run search                |       |
| TC-026  | Pending |            | Leads settings editing          |       |
| TC-027  | Pending |            | Leads view message              |       |
| TC-028  | Pending |            | Leads delete                    |       |
| TC-029  | Pending |            | Leads sources/evidence viewer   |       |
| TC-030  | Pending |            | Leads LinkedIn hyperlink        |       |
| TC-031  | Pending |            | Leads contacted checkbox and date |       |

### Chief of Staff tab

| Test ID | Result  | Date       | Description                            | Notes |
|---------|---------|------------|----------------------------------------|-------|
| TC-054  | Pending |            | CoS new chat + persistence             |       |
| TC-055  | Pending |            | CoS preferences affect responses       |       |
| TC-056  | Pending |            | CoS calendar read-only context         |       |
| TC-057  | Pending |            | CoS tool loop (WEB_SEARCH / DOC_SEARCH) |       |
| TC-058  | Pending |            | CoS task capture (ADD_TASK)            |       |
| TC-059  | Pending |            | CoS structured memory                  |       |

### Document generation tab

| Test ID | Result  | Date       | Description                    | Notes |
|---------|---------|------------|---------------------------------|-------|
| TC-032  | Pending |            | Document upload/URL addition   |       |
| TC-033  | Pending |            | Document removal/deletion      |       |
| TC-034  | Pending |            | Document output generation     |       |

### Meetings tab

| Test ID | Result  | Date       | Description                   | Notes |
|---------|---------|------------|-------------------------------|-------|
| TC-035  | Pending |            | Meetings start recording      |       |
| TC-036  | Pending |            | Meetings stop recording       |       |
| TC-037  | Pending |            | Meetings generate transcript  |       |
| TC-038  | Pending |            | Meetings load file            |       |
| TC-039  | Pending |            | Meetings save transcript     |       |

### Compliance tab

| Test ID | Result  | Date       | Description                         | Notes |
|---------|---------|------------|-------------------------------------|-------|
| TC-040  | Pending |            | Compliance upload documents/URLs    |       |
| TC-041  | Pending |            | Compliance remove/delete document  |       |
| TC-042  | Pending |            | Compliance run compliance check    |       |
| TC-043  | Pending |            | Compliance save report             |       |
| TC-044  | Pending |            | Compliance link to CRM             |       |

---

## How to use

1. Run the test (manual or automated) as described in [testing.md](testing.md).
2. In this file, set **Result** to `Pass`, `Fail`, `Skip`, or `Pending`.
3. Set **Date** to the run date (YYYY-MM-DD).
4. Optionally add a short **Notes** line for that run (e.g., "Fail: calendar token missing", "56 passed").
5. For automated suites, record the overall outcome and date in the *Automated test runs* table.
