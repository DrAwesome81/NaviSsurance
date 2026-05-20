# Lead Generation (Leads Tab)

Last updated: 2026-05-12

<!-- Pulse private memory visibility + Shield Security/Compliance surface awareness -->

## What it does
The **Leads** tab finds MedTech decision-makers (AI SaMD / IVD / regulatory-adjacent) and produces:
- **verifiable** leads (each lead must have sources)
- a **personalized outreach message** (copy/paste)
- a lightweight **score** so you can filter/prioritize
- a one-click **follow-up task** so outreach is scheduled (not forgotten)

### Where it lives
- **UI**: `gui/leads_tab.py`
- **Persistence**: `core/db.py` (`leads` table)
- **Web research**: `core/grok_client.py:grok_web_search()`
- **510(k) signals**: `core/openfda.py` (openFDA device 510(k) API)
- **Scoring**: `core/lead_scoring.py`
- **Config prompt**: `config/lead_gen_config.json` (`system_message`)

---

## Runtime flow (two-pass)

### Pass A: Discover candidates
The app runs a web-search-backed prompt that returns **candidate leads** with minimal fields:
- `name`, `company`, `title`, `rationale`
- `linkedin_url`, `company_url`
- `sources` (must include at least one URL)
- optional `signals`

### Enrichment: openFDA 510(k) lookup
For each candidate company, the app queries openFDA’s 510(k) endpoint by applicant string and adds:
- signals like “newest received … decision …”
- the openFDA request URL as a source

Code: `core/openfda.py`

### Pass B: Verify + enrich
The app then sends the candidate list (including openFDA signals) into a **verification/enrichment** prompt that:
- drops unverifiable leads
- adds a **personalized message**
- strengthens evidence (`sources` should be \(\ge 2\) when possible)

---

## Evidence-first rules (anti-hallucination)
The app enforces:
- **No sources → no lead stored**
- Leads are inserted/updated via a stable `lead_key` (LinkedIn URL preferred; otherwise name+company)

This is intentionally strict: you can’t act on “pretty JSON” that isn’t grounded.

---

## SQLite data model (high level)
Table: `leads`
- identity: `lead_key` (unique), `company_key`
- core fields: `name`, `company`, `title`, `linkedin_url`, `company_url`
- content: `rationale`, `message`
- workflow: `status`, `contacted`, `contact_date`, `next_action_date`, `notes`
- evidence: `sources_json`, `signals_json`
- scoring: `signals_score`, `fit_score`, `confidence_score`, `total_score`
- tracking: `first_seen`, `last_seen`, `last_updated`

---

## UI workflow
- **Filters**: status, minimum score, hide-contacted
- **Sources**: opens a dialog with signals + clickable evidence links
- **Edit**: updates status/next-action/notes
- **Create Task**: creates a local task (category Business) for outreach follow-up and syncs `next_action_date`

---

## LinkedIn automation note (important)
The app currently supports **manual outreach** (open profile + copy/paste message) and **scheduling** (create follow-up tasks).

“Send a LinkedIn DM directly from the app” is not implemented here because LinkedIn’s messaging APIs are not generally available for typical apps and ToS constraints are real. If you want automation later, the safe path is:
- keep messaging manual, but automate **tracking + scheduling**
- only add direct send if you have an approved LinkedIn API scope/path that explicitly supports it

<!-- Pulse private memory + Shield triage in lead gen doc -->

