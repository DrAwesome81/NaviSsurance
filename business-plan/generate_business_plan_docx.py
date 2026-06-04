#!/usr/bin/env python3
"""
NaviSsurance / NaviSure Business Plan DOCX Generator
Professional, grounded plan per task requirements.
Uses python-docx (matches existing codebase patterns in core/billing/).
Smallest viable comprehensive deliverable.
"""

from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import os
from datetime import datetime

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_FILE = os.path.join(OUT_DIR, "NaviSsurance_Business_Plan_June2026.docx")

def set_cell_shading(cell, color_hex):
    """Set cell background (matches skill guidance for tables)."""
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:fill'), color_hex)
    tcPr.append(shd)

def add_heading_styled(doc, text, level=1):
    h = doc.add_heading(text, level=level)
    for run in h.runs:
        run.font.color.rgb = RGBColor(30, 58, 95) if level == 1 else RGBColor(46, 90, 140)
    return h

def add_para(doc, text, bold=False, italic=False, size=11):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.name = 'Arial'
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    return p

def add_bullet(doc, text, bold_prefix=None):
    p = doc.add_paragraph(style='List Bullet')
    if bold_prefix:
        run = p.add_run(bold_prefix + text)  # single run: no duplication
        run.bold = True
        run.font.name = 'Arial'
        run.font.size = Pt(10)
    else:
        run = p.add_run(text)
        run.font.name = 'Arial'
        run.font.size = Pt(10)
    return p

def create_table(doc, headers, rows, col_widths=None):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = 'Table Grid'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    # Header
    hdr_cells = table.rows[0].cells
    for i, h in enumerate(headers):
        hdr_cells[i].text = h
        for para in hdr_cells[i].paragraphs:
            for run in para.runs:
                run.bold = True
                run.font.size = Pt(9)
                run.font.name = 'Arial'
        set_cell_shading(hdr_cells[i], "DCE6F1")

    # Data rows
    for r_idx, row in enumerate(rows):
        row_cells = table.rows[r_idx + 1].cells
        for c_idx, val in enumerate(row):
            row_cells[c_idx].text = str(val)
            for para in row_cells[c_idx].paragraphs:
                for run in para.runs:
                    run.font.size = Pt(8)
                    run.font.name = 'Arial'
            if r_idx % 2 == 0:
                set_cell_shading(row_cells[c_idx], "F5F5F5")

    if col_widths:
        for i, w in enumerate(col_widths):
            for row in table.rows:
                row.cells[i].width = Inches(w)

    return table

def main():
    doc = Document()

    # Styles
    style = doc.styles['Normal']
    style.font.name = 'Arial'
    style.font.size = Pt(10)

    # Proper header/footer setup (per review fix + docx skill / billing/docx_render.py patterns)
    section = doc.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.left_margin = Inches(0.75)
    section.right_margin = Inches(0.75)
    section.top_margin = Inches(0.75)
    section.bottom_margin = Inches(0.75)

    # Header: confidentiality + running title
    header = section.header
    header_para = header.paragraphs[0] if header.paragraphs else header.add_paragraph()
    header_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = header_para.add_run("CONFIDENTIAL – NaviSure Consulting Business Plan | June 2026 | Internal Use Only")
    run.font.size = Pt(8)
    run.font.name = 'Arial'
    run.italic = True
    run.font.color.rgb = RGBColor(128, 0, 0)

    # Footer: page numbers (OxmlElement pattern)
    footer = section.footer
    footer_para = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    footer_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer_para.add_run("Page ")
    run.font.size = Pt(9)
    run.font.name = 'Arial'
    # Add PAGE field
    fldChar1 = OxmlElement('w:fldChar')
    fldChar1.set(qn('w:fldCharType'), 'begin')
    instrText = OxmlElement('w:instrText')
    instrText.text = "PAGE"
    fldChar2 = OxmlElement('w:fldChar')
    fldChar2.set(qn('w:fldCharType'), 'end')
    run2 = footer_para.add_run()
    run2._r.append(fldChar1)
    run2._r.append(instrText)
    run2._r.append(fldChar2)
    run3 = footer_para.add_run(" | NaviSure + NaviSsurance Business Plan")
    run3.font.size = Pt(9)
    run3.font.name = 'Arial'

    # === COVER ===
    for _ in range(3):
        doc.add_paragraph()
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("NAVISURE CONSULTING")
    run.bold = True
    run.font.size = Pt(28)
    run.font.color.rgb = RGBColor(30, 58, 95)

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = sub.add_run("&")
    run.font.size = Pt(16)

    title2 = doc.add_paragraph()
    title2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title2.add_run("NAVISURANCE (CONSULTANT OS)")
    run.bold = True
    run.font.size = Pt(24)
    run.font.color.rgb = RGBColor(46, 90, 140)

    doc.add_paragraph()
    tag = doc.add_paragraph()
    tag.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = tag.add_run("COMPREHENSIVE BUSINESS PLAN FOR COMPANY GROWTH")
    run.bold = True
    run.font.size = Pt(14)

    sub2 = doc.add_paragraph()
    sub2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = sub2.add_run("Incorporating the NaviSsurance AI-Powered Operations Platform as Core Asset & Moat")
    run.italic = True
    run.font.size = Pt(11)

    for _ in range(4):
        doc.add_paragraph()

    date_p = doc.add_paragraph()
    date_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = date_p.add_run("June 2026")
    run.font.size = Pt(12)

    founder_p = doc.add_paragraph()
    founder_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = founder_p.add_run("Founder: Dr. Adam Odeh | NaviSure Consulting")
    run.font.size = Pt(10)

    note = doc.add_paragraph()
    note.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = note.add_run("Grounded in actual app (roadmap_status.md May 2026, consultant-os-roadmap.md approved plan, founder interviews June 2026)")
    run.font.size = Pt(9)
    run.italic = True
    run.font.color.rgb = RGBColor(80, 80, 80)

    conf = doc.add_paragraph()
    conf.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = conf.add_run("CONFIDENTIAL – Internal Planning Use Only")
    run.bold = True
    run.font.size = Pt(10)
    run.font.color.rgb = RGBColor(170, 0, 0)

    doc.add_page_break()

    # === 1. EXEC SUMMARY ===
    add_heading_styled(doc, "1. Executive Summary", 1)

    add_para(doc, "NaviSure Consulting (Dr. Adam Odeh) is a specialized MedTech regulatory consulting practice (AI/ML SaMD, IVD/LDT, compliance-heavy device work). Current ~$230k gross revenue (last 12mo), with ~90% concentration from one high-value fractional VP RA/QA client (Dova Health Intelligence) + 4 other active clients (3 project-based, 1 spotty hourly). Solo founder at 70% billable consulting / 25% app development / 5% bizdev, extremely low overhead (~$400/mo business expenses), comfortable bootstrap runway.")

    add_para(doc, "The core growth asset is NaviSsurance (\"Navi\" / Consultant OS) — a desktop-first, local-first AI operations platform (see overview.md/design.md). It functions as a \"small, highly competent team\" (per consultant-os-roadmap.md vision) with deep layered memory (user/cos/agent/assignment), proactive Intel (Pulse agent + watchlists/findings/alerts), Chief of Staff planning/delegation/AM Sweeps, Workspace document production with real historical reference injection (Phase 4 advancing), native billing/time/invoicing from templates, evidence-first lead gen (openFDA 510(k) enriched + scoring), compliance review, client dossiers, meeting transcription + task extraction, and specialist named agents. Current state (per roadmap_status.md May 2026 IMPL notes + founder June 2026 input): Phase 1 (Memory & Retrieval Core) 100% complete including Relevant Past Work surfaces; Intel & Coordination elements (roadmap Phase 3 per consultant-os-roadmap.md; Billing Depth Phase 2 deferred per roadmap_status.md) + Client Dossier (largely complete per TODO.md) advanced; Phase 4 (Workspace production engine) partial (auto-injection of strong historical matches + style guidance live for strong matches, ~25%; full related sets/consistency/Drive export targeted 0-6mo per this plan). No measurable time savings vs plain Grok yet per founder (\"doesn't save me time currently... NaviSsurance isn't ready yet to replace it\"). This is THE reference product per consultant-os-roadmap.md (approved fixed plan).")

    add_para(doc, "Vision (directly from approved roadmap, operationalized here): Grow to $500k total revenue in 36 months, 100% from consulting services (per founder explicit priority), using Navi as the internal operating system and \"staff replacement\" to solve the founder's #1 blocker (\"no time and no strategy for bizdev\"), deliver 20-30%+ capacity/utilization lift via faster higher-quality deliverables that intelligently reuse real past work, free founder time for high-value FDA/client interactions + personal/family life, and enable justified first hire (domain expert) once client base supports it. App monetization (licenses to peer solo/boutique consultants) is explicitly secondary/optional bonus — founder: \"most of our money I expect will come from consulting; not app sales.\" Low CAC (organic + content + app demos in pitches), high LTV, exceptional unit economics for a knowledge business.")

    add_para(doc, "Key Numbers (Base Case, 36 months):", bold=True)
    add_bullet(doc, "~$230k current → $500k services (100% consulting); app as upside only.")
    add_bullet(doc, "5 clients today (heavy concentration risk) → 12-14 diversified clients.")
    add_bullet(doc, "Phase 4 completion (Q4 2026 target) is the primary capacity lever.")
    add_bullet(doc, "Already profitable; ~78% gross margins; LTV:CAC >30x via low-CAC GTM + Navi leverage.")
    add_bullet(doc, "Bootstrap primary; open to small loan ($25-75k) for acceleration once plan solid and clients justify spend/hire.")

    add_para(doc, "Immediate 90-Day Action Plan (executable Monday inside the app itself):", bold=True)
    add_bullet(doc, "Day 1 Setup (30-60min time-box in Navi): Teach Navi past wins + Dova context (memory); create 1 CoS bizdev sequence template + 2 Intel watchlists (FDA + competitors); seed 1 Workspace proposal from historical refs. Pilot measurement: track 1 outreach outcome + time saved vs prior manual.")
    add_bullet(doc, "Prioritize smallest-safe Phase 4 Workspace completion (ref injection polish, related-set generation, export) to deliver first measurable time savings vs plain Grok.")
    add_bullet(doc, "Use CoS + AM Sweep + Intel + Workspace inside Navi to build/execute 90-day bizdev system: 8-12 qualified outreaches, 2-3 proposals using memory of past wins, full tracking in Clients/Tasks. Target: 1 new client.")
    add_bullet(doc, "Produce 2 case studies (Dova + one other) using app workflows; publish via LinkedIn.")
    add_bullet(doc, "Review this plan + Assumptions tab in accompanying .xlsx; decide on any small loan for 1-2 conferences.")
    add_bullet(doc, "Pilot Navi alpha with 1-2 peer solos for feedback (internal validation first).")
    add_bullet(doc, "Weekly CoS review of progress against this plan — run the company inside the product.")

    add_para(doc, "This plan is maximally grounded: actual app state (no overclaiming features), founder answers across two question rounds (services-first, 36mo $500k, app as internal lever not primary product yet, referrals-only today, low burn, \"we'll need to figure out\" productization), and external data (MedTech devices $572B 2025 growing 7%, IVD $109B growing 7.6%, reg consultants $275-450/hr, 510(k) projects $17.5-50k, vertical AI precedent Harvey at $400-1200/seat/mo, regtech 22%+ CAGR). It extends the approved product roadmap without contradiction. Actionable, specific, numbers-driven, and ready to execute.", italic=True)

    doc.add_page_break()

    # Sources & Citations appendix (added per review Issue 6)
    add_heading_styled(doc, "Appendix: Sources & Citations", 1)
    add_para(doc, "External (web_search June 2026): Fortune Business Insights medical devices $572.31B 2025 / $604.99B 2026 CAGR 6.9%; IVD $109.06B 2025 growing 7.6% to $157.63B 2030 (MarketsandMarkets). Reg consultants $275-450/hr US, 510(k) projects $17.5-50k (meddeviceguide.com 2026). Regtech AI market ~19.6B to 82B by 2032 CAGR 22.8% (Fortune). Vertical AI comp: Harvey legal ~$400-1200/user/mo (2026 reviews). AI/ML SaMD clearance equity value example: 30x+ ROI cohorts (innolitics.com). Founder data + app state: 2x ask_user_question rounds (June 2026), roadmap_status.md (May 2026 IMPLs e.g. 2f4c91b8/4c2e9f1d), consultant-os-roadmap.md (approved fixed 5-phase). All projections conservative; see .xlsx Assumptions for drivers/sensitivity.")
    add_para(doc, "Internal: Full cross-check vs docs/consultant-os-roadmap.md (238 lines), roadmap_status.md, overview.md, design.md, billing/*, workspace_orchestrator.py, clients_tab.py, intel_retrieval.py etc. + python-docx/openpyxl inspection of outputs. No core app changes.")

    # === 2. COMPANY + VISION ===
    add_heading_styled(doc, "2. Company & Vision", 1)
    add_para(doc, "NaviSure Consulting delivers high-value, evidence-based regulatory strategy, 510(k)/De Novo/PMCF support, QMS/compliance (ISO 13485, 21 CFR 820), clinical evidence, cybersecurity/human factors, and fractional RA/QA leadership to MedTech companies, with deep specialization in AI/ML SaMD and IVD/LDT. The founder (Dr. Adam Odeh) provides the domain expertise; NaviSsurance is the force multiplier that makes scaling possible without proportional personal grind or quality loss.")

    add_heading_styled(doc, "Vision (Direct Quote from Approved consultant-os-roadmap.md)", 2)
    add_para(doc, "\"NaviSsurance becomes a single, intelligent workspace that functions like a small, highly competent team working exclusively for you. It maintains deep memory of your clients and past work, proactively monitors the regulatory and competitive environment, helps you plan and prioritize, captures time and revenue cleanly, and dramatically accelerates the creation of high-quality client deliverables by intelligently reusing your real historical work.\"", italic=True)
    add_para(doc, "This business plan makes that vision the operating system for company growth to $500k services revenue while regaining lifestyle. Navi is not a distraction from services — it is how services scale.")

    add_heading_styled(doc, "Guiding Principles (Roadmap + Applied to Business)", 2)
    add_bullet(doc, "One coherent system (Navi runs planning, intel, production, billing, memory, client hub — no fragmentation).", "Memory & retrieval first-class: ")
    add_bullet(doc, "Your real past work + durable facts is the compounding moat and accelerator (Phase 1 complete, Phase 4 makes it production-visible).", "Reduce admin/context switching: ")
    add_bullet(doc, "The founder's explicit #1 pain point today; CoS + integrated tabs solve it.", "Proactive intelligence without annoyance: ")
    add_bullet(doc, "Pulse raises signals for CoS planning and client work — never spammy.", "Billing/time native and low-friction: ")
    add_bullet(doc, "Already strong; keeps revenue clean as volume grows.", "Safe gradual expansion: ")
    add_bullet(doc, "Smallest-safe edits per contributor_guide; no big rewrites.")

    doc.add_page_break()

    # === 3. PRODUCT ===
    add_heading_styled(doc, "3. Product Deep Dive & Roadmap Alignment", 1)
    add_para(doc, "NaviSsurance is a desktop-first (PyQt6), SQLite source-of-truth, local-first/privacy-first (optional local LLM Qwen3-14B-Q5 GGUF via llama.cpp, optional xAI Grok for CoS/complex/intel, optional APScheduler runtime + local FastAPI, Playwright browser tools, Chroma RAG) specialized AI platform for MedTech regulatory consultants. It is workflow-native with named specialist agents, layered durable memory, and production integrations (DOCX/PDF export, Google Drive/Dropbox file intelligence, billing templates, openFDA enrichment). Not a general chat shell.")

    add_heading_styled(doc, "Current Capabilities (May 2026, per roadmap_status.md + overview.md + code)", 2)
    add_bullet(doc, "Dashboard with briefing, calendar, email triage, tasks, persistent news.", "Dashboard: ")
    add_bullet(doc, "NL planning, AM Sweeps (4-bucket + time blocks + parallel ASSIGN), structured briefings (billing + deliverables + focus + Pulse), delegation board with health/NEEDS_INPUT, full assignment lifecycle + artifacts.", "Chief of Staff: ")
    add_bullet(doc, "Watchlists, runtime monitoring, findings (importance/raised/notes), hybrid local retrieval (keyword + vector + LLM filter in intel_retrieval.py), client linking, private theme memory, CoS cross-links, badge.", "Intel / Pulse (beta but core engine solid): ")
    add_bullet(doc, "Template DOCX generation, outline/section workflow, dual-LLM, direct Drive export, auto-injection of strong historical references (Phase 1 get_relevant_past_documents + style/structure guidance) — already live for production use on strong historical matches (auto-injection + style guidance per file_handler.py/workspace_tab.py; full Phase 4 related-sets/consistency/Drive export targeted per roadmap_status May 2026 IMPL). 'Zero manual clicks' only on strong matches (partial ~25% of full Phase 4 spec).", "Workspace (Phase 4 advancing — highest biz leverage): ")
    add_bullet(doc, "Hourly + deliverable/SoW per client, timer/manual entry, client_deliverables, branded DOCX/PDF drafts from templates (default v2 + imported), monthly autorun, history, review-first. Unified billing fields on main clients + legacy parity.", "Billing (mature per billing/* + roadmap_status; Phase 2 depth deferred): ")
    add_bullet(doc, "Rich profiles (billing_mode, rate, contacts, aliases), linked memory (Teach), projects/assignments/tasks, recent activity, quick actions, Compliance Status (Phase 2 cross-link), Relevant Past Work surface (Phase 1). Largely complete per TODO.md.", "Clients / Dossier: ")
    add_bullet(doc, "Grok + openFDA 510(k) signals, strict sources-required, scoring, personalized messages, status + next-action + notes, one-click task creation.", "Leads (evidence-first): ")
    add_bullet(doc, "user_memory (global), cos_memory, agent_memory (private per specialist), assignment_memory (short-horizon), explicit Teach, passive extraction + approval, promotion paths, entity scoping, daily/weekly reflections, summary-first retrieval + raw grounding.", "Memory (foundation, Phase 1 100%): ")
    add_bullet(doc, "Deep Research (iterative web to reusable brief + DOCX/PDF), Meetings (transcription + task extraction + DOCX), Notes (living organized docs + export), Compliance checker, runtime + local API scaffolding, browser tools, tool registry.", "Other active: ")

    add_heading_styled(doc, "Approved Roadmap (consultant-os-roadmap.md) → Business Value", 2)
    add_para(doc, "Fixed 5-phase order. This plan maps product gates directly to $500k services outcomes without reordering or contradiction:")

    headers = ["Phase", "Product Focus", "Biz Value / Trigger"]
    rows = [
        ["Phase 4 (NOW)", "Workspace Production: historical ref injection (live), related sets, consistency, Drive export", "2-3x faster high-quality deliverables (Validation Plan + RMF + Trace etc.) → higher utilization, win rate, capacity to hit $500k without founder burnout. Current partial already delivers value."],
        ["Phase 5", "Smart filing, global search, dashboards/reporting, UX polish", "Lower friction, better insights for planning/sales, easier first-hire onboarding, founder time reclaimed."],
        ["Billing Depth (deferred)", "Semi-auto time suggestions, retainer health, multi-template, one-click from dossier", "Cleaner revenue visibility in CoS briefings, higher realization rates, less admin as volume grows."],
    ]
    create_table(doc, headers, rows, [1.2, 2.8, 3.0])
    add_para(doc, "Phase 4 is the single highest-leverage item for the $500k goal. It directly attacks the bulk of consulting hours (document production) by making real historical work automatically available. This is what lets a solo founder scale services without proportional time or quality loss.", italic=True)

    doc.add_page_break()

    # === 4. MARKET ===
    add_heading_styled(doc, "4. Market Opportunity", 1)
    add_para(doc, "Primary: Grow NaviSure Consulting services to $500k in 36 months using Navi as differentiator and capacity multiplier. Product TAM for Navi is secondary/optional upside (licenses to peers) once internally proven and services engine is stable. Founder priority is explicit: services first.")

    add_heading_styled(doc, "TAM / SAM / SOM (Services Lens)", 2)
    add_bullet(doc, "TAM: Global MedTech regulatory/quality consulting spend. Devices mkt $572B (2025) → $605B (2026), CAGR ~6.9% (Fortune Business Insights). IVD $109B (2025) → $158B (2030), CAGR 7.6%. Regulatory services high-margin slice of device CRO/services (~$10-11B). AI/ML SaMD + EU IVDR + FDA software scrutiny = structural demand tailwind.", "TAM: ")
    add_bullet(doc, "SAM: US + EU MedTech founders/startups + small-mid device cos needing SaMD/IVD strategy, 510(k)/De Novo prep, QMS, evidence plans, or fractional RA/QA. High willingness to pay: specialists $275-450/hr (2026 benchmarks from meddeviceguide/consultfees); typical 510(k) consulting project $17.5k-$50k+. Clearance events create massive equity value (one cohort analysis: $51M costs → $1.54B attributable equity in 14 days, 30x ROI).", "SAM: ")
    add_bullet(doc, "SOM (36mo): Founder-controlled slice — grow from 5 clients/$230k to ~12-14 clients/$500k via 2-3 new clients/year (mix project + retainers), modest rate expansion, utilization lift from Navi (20-30%), and diversification from Dova. Achievable with app-powered systematic bizdev (solves \"no time/no strategy\") + demonstrated delivery edge. Addressable via referrals + content + 1-2 conferences/year initially.", "SOM: ")

    add_heading_styled(doc, "Buyer Personas & 2026 Trends", 2)
    add_bullet(doc, "CEOs/founders of AI SaMD or IVD startups (need fast defensible path + evidence + timeline + risks — matches existing 10-day sprint offering); small device cos lacking in-house bandwidth; larger cos for surge/specialized (cyber, human factors).", "Primary (services): ")
    add_bullet(doc, "Solo MedTech/regulatory consultants and 5-20p boutique firms in the same niche (US/EU) drowning in admin, memory, context switching, and proposal volume — exactly the founder's current pain. They use Grok/ChatGPT + Notion/Obsidian/custom scripts today. Navi replaces \"potential staff\" with coherent, memory-rich, local/privacy-safe system.", "Secondary (future app): ")
    add_bullet(doc, "Regtech/AI adoption exploding (regtech $19.6B → $82B by 2032, 22.8% CAGR). Enterprise AI scaling (Deloitte/PwC 2026: agentic workflows, 50%+ worker access growth). Vertical domain AI (Harvey legal $400-1200/seat/mo) proves willingness to pay premium for specialized tools. Regulatory complexity for software/AI devices increasing — perfect for both services and purpose-built OS.", "Trends 2026: ")

    doc.add_page_break()

    # === 5. COMPETITIVE ===
    add_heading_styled(doc, "5. Competitive Positioning", 1)
    add_para(doc, "NaviSsurance occupies a unique \"Consultant Operating System\" niche for MedTech regulatory work. No competitor combines deep domain specialization (SaMD/IVD/reg agents + openFDA), layered durable memory of the user's real historical client work + decisions, local/privacy-first execution (critical for sensitive submission data), proactive specialist agents (Pulse), and native full-lifecycle ops (CoS planning + Intel + Workspace production + Billing + Leads + Dossiers) in one desktop app.")

    add_heading_styled(doc, "Positioning Matrix", 2)
    comp_headers = ["Player", "Strength", "Weakness vs Navi", "Navi Advantage"]
    comp_rows = [
        ["ChatGPT + Notion/Obsidian", "Ubiquitous, cheap, flexible", "No memory of YOUR real work, no domain agents, no billing/intel/CoS integration, context switching, privacy risks for client data", "Durable layered memory + full workflow + local/privacy + reg-specific agents + production reuse"],
        ["Harvey / Legal Vertical AI", "Deep domain for law, high willingness to pay ($400-1200/seat/mo)", "Wrong domain (law vs MedTech reg), enterprise pricing, no local/privacy option, no ops/billing native", "Purpose-built for exact ICP + local + integrated ops at accessible price point"],
        ["General regtech / compliance platforms", "Monitoring or QMS features", "Shallow on consulting workflows, no personal memory/reuse of past deliverables, no CoS delegation or full ops", "End-to-end Consultant OS with production generation + memory + billing + leads"],
        ["Custom scripts + email/calendar", "Tailored today", "Brittle, no AI, no intelligence layer, high maintenance, no scale or proactive intel", "AI-native, proactive, memory-rich, low maintenance, compounds with use"],
    ]
    create_table(doc, comp_headers, comp_rows, [1.5, 1.6, 2.2, 2.2])

    add_heading_styled(doc, "Moats (Durable: Data + Workflow + Domain + Architecture)", 2)
    add_bullet(doc, "Your data compounds with every project (layered memory + RAG over real Drive/Dropbox files + intel + time + past deliverables). Phase 4 makes it visible in every new document.", "Your data moat: ")
    add_bullet(doc, "Specialist agents, prompts, openFDA, compliance cross-links, regulatory watchlists, SaMD/IVD-specific workflows — not generic drafting.", "Domain depth: ")
    add_bullet(doc, "SQLite + optional local LLM + no forced cloud. Critical for clients sharing design history/clinical/pre-sub data. Aligns with security.md and regulated client expectations.", "Local + privacy-first: ")
    add_bullet(doc, "Memory → Intel → CoS → Workspace → Billing → Clients — one desktop. No switching tax. The \"small competent team\" is always on, always in context.", "Full-stack integration: ")
    add_bullet(doc, "Proven internally first (eat your own dogfood at highest level), then optionally productized. No capital or distraction risk until services core is firing.", "Option value / low risk: ")

    doc.add_page_break()

    # === 6. BUSINESS MODEL ===
    add_heading_styled(doc, "6. Business Model, Pricing & Packaging", 1)
    add_para(doc, "Per founder (two question rounds): 100% of the $500k target is services revenue. App monetization is \"unknown/secondary bonus\" and not required for success. Model is therefore hybrid — services as the engine, Navi as the secret weapon/moat/optional product line.", italic=True)

    add_heading_styled(doc, "Primary: Services (Navi-Powered)", 2)
    add_bullet(doc, "CEO Regulatory Strategy Sprints (fixed-scope 10-day board/investor-ready memo + cited research brief + week-by-week execution plan — per existing sprint doc), 510(k)/De Novo/PMCF protocol support, QMS/ISO/FDA remediation & implementation, clinical evidence strategy, cybersecurity/human factors, fractional VP RA/QA (Dova model), ongoing retainers.", "Offerings: ")
    add_bullet(doc, "Hourly $275-400+ (market specialist rates 2026); project 510(k) packages $18-60k+; retainers $8-20k/mo for fractional/exec roles. Premium justified by faster turnaround, higher first-pass quality (historical reuse + consistency checks), proactive intel edge, and clean billing from the same system the work happens in.", "Pricing (market + premium for speed/quality): ")
    add_bullet(doc, "\"Navi-powered delivery\" positioning in every proposal/pitch. Live demo during sales (CoS morning plan → Intel on client's regulatory area → Workspace generating section with real past reference → Billing draft) is the ultimate differentiator vs generic consultants with ChatGPT. Future: optional client-facing Navi workspace or intel briefings as high-margin add-on.", "Attach / Upsell via App: ")

    add_heading_styled(doc, "Secondary / Optional: App Productization (Only After Internal Proof)", 2)
    add_para(doc, "Target: solo and small-boutique (5-20 person) MedTech/regulatory consultants in SaMD/IVD niche (US/EU) — same pain the founder has today. Only after services $350k+ run-rate and internal proof (alpha with 2-3 peers first).")
    add_bullet(doc, "Solo: $1,999/yr or $199/mo (full desktop + local models + updates + basic support).", "Hypothesized (conservative; test in alpha): ")
    add_bullet(doc, "Small Firm (≤5 seats): $4,999/yr (shared memory, team assignments, priority support).")
    add_bullet(doc, "Enterprise/In-house: Custom $8-15k/yr + onboarding services.")
    add_bullet(doc, "$3-8k one-time \"Navi OS Setup + Training + Custom Agent + Template Pack\" for new buyers (leverages founder expertise + app). 30% attach target.", "Services bundle (high-margin): ")
    add_bullet(doc, "Vertical AI precedent (Harvey $400-1200/seat/mo legal; vertical SaaS addons $15-65/user/mo). Reg professionals pay for time savings + risk reduction. Desktop/local/privacy is a feature for this ICP (sensitive client data). Low CAC via founder's content/network/peer referrals once proven.", "Rationale: ")

    doc.add_page_break()

    # === 7. GTM ===
    add_heading_styled(doc, "7. Go-to-Market Strategy", 1)
    add_para(doc, "Founder reality (direct quote): \"I have no time to find clients, and no strategy for how to do so even if I did. It's been all referrals so far.\" This is the exact problem Navi (CoS + Intel + Workspace + Leads) is built to solve. GTM = \"use the product to sell the services, and prove the product internally first.\"")

    add_heading_styled(doc, "Phased GTM (Services Primary)", 2)
    add_para(doc, "0-6 months (Foundation + First Proof — Start Monday):", bold=True)
    add_bullet(doc, "Inside Navi: Build the bizdev operating system (CoS templates for outreach sequences, Intel watchlists for regulatory triggers that create client needs, Workspace proposal templates seeded with past wins, Leads tab for target device cos, full pipeline in Clients/Tasks). Run AM Sweeps that explicitly include \"bizdev\" bucket. Goal: 8-12 outreaches/month, 2-3 proposals, 1-2 new clients.")
    add_bullet(doc, "Content flywheel: 1-2 LinkedIn/FDA posts per week, generated/supported by Pulse intel + Deep Research (\"What the latest FDA AI guidance actually means for SaMD founders\").")
    add_bullet(doc, "Sales enablement: 10-15 min live pitch demo of Navi (CoS → Intel on client's area → Workspace with real past ref → Billing). This sells.")
    add_bullet(doc, "Dova & existing: Deepen, ask for referrals, document case study using app workflows.")

    add_para(doc, "6-18 months (Systematic + Events):", bold=True)
    add_bullet(doc, "1-2 key conferences/year (RAPS, MedTech Conference, SaMD/IVD events). $8-15k/yr budget. Low CAC because founder is the expert/speaker.")
    add_bullet(doc, "Partnerships: Referral with complementary boutiques (clinical, reimbursement, software). Navi makes handoff clean (memory artifacts, assignments).")
    add_bullet(doc, "App alpha: 2-3 peer solos get free/steep-discount Navi for 3-6mo in exchange for feedback + testimonials. Internal proof first.")

    add_para(doc, "18-36 months (Scale):", bold=True)
    add_bullet(doc, "First hire (domain expert) — Navi lowers onboarding cost dramatically (memory + CoS + templates).")
    add_bullet(doc, "If app traction: formalize tiers, add to site, light paid (LinkedIn targeting \"regulatory consultant\" / \"SaMD founder\").")
    add_bullet(doc, "Services scale: larger retainers, more complex programs, EU IVDR work, enabled by capacity from Navi + hire.")

    doc.add_page_break()

    # === 8. TEAM & OPS ===
    add_heading_styled(doc, "8. Team & Hiring Roadmap + Operations", 1)
    add_para(doc, "Current: Solo founder. No contractors. Extremely low overhead. First hire only when clients justify (founder: \"I can't take out a loan to hire someone, because I don't have enough clients to justify an employee yet\").")

    add_heading_styled(doc, "Hiring Gates (Revenue- and Capacity-Triggered)", 2)
    add_bullet(doc, "Junior-to-mid regulatory consultant or ops/admin hybrid ($90-120k fully loaded). Profile: strong writer, detail-oriented, eager to learn SaMD/IVD. Navi makes this person productive in weeks (memory transfer, CoS assigns scoped work, Workspace templates, client dossiers). Goal: delegate day-to-day drafting/research/compliance/meetings — founder retains relationships, FDA calls, strategy, bizdev.", "First hire (target ~month 18, once $300k+ run-rate or 7+ clients): ")
    add_bullet(doc, "Either additional domain specialist or first dedicated app/dev support (if productizing) or bizdev/sales.", "Second hire (post $450k or clear product traction): ")
    add_bullet(doc, "Founder (strategy, clients, FDA, vision) → 1-2 domain delivery + 0-1 ops/app. Flat, high-trust, enabled by Navi as the coordination layer (no heavy management overhead needed).", "Org chart evolution: ")

    add_heading_styled(doc, "How Navi Runs the Entire Company (Ops)", 2)
    add_para(doc, "The entire business operates inside Navi today and will continue to. This is the ultimate proof point and moat:")
    add_bullet(doc, "Daily CoS briefings + AM Sweeps (explicit bizdev bucket + client health + billing snapshot). Weekly reflections.", "Planning & Prioritization: ")
    add_bullet(doc, "Pulse monitors FDA guidance, competitor clearances, standards — surfaced in CoS for client work and own content/bizdev targeting.", "Intel & Positioning: ")
    add_bullet(doc, "All client deliverables start in Workspace with automatic historical reference injection + consistency. Meeting notes/transcripts → tasks → memory.", "Delivery: ")
    add_bullet(doc, "Leads tab (or targeted use) + Clients dossiers + Tasks + assignment board. Everything linked.", "Pipeline & CRM: ")
    add_bullet(doc, "Native time entry linked to clients/projects, invoice drafts from templates, autorun, revenue visibility in CoS briefings.", "Finance: ")
    add_bullet(doc, "All past work, decisions, client context in durable memory. New hire (or future self) has instant access via search + CoS + dossiers.", "Knowledge & Onboarding: ")

    add_para(doc, "This \"eat your own dogfood at the highest level\" is how a solo founder scales without proportional chaos or burnout. It is also the story that sells the app later.", italic=True)

    doc.add_page_break()

    # === 9. FINANCIALS ===
    add_heading_styled(doc, "9. Financials & Projections", 1)
    add_para(doc, "Detailed 3-scenario model (Base / Conservative / Optimistic) is in the accompanying Excel: business-plan/Financial_Projections_NaviSure_June2026_v1.xlsx (generated via openpyxl with formulas, color-coded per xlsx skill: blue inputs + yellow for editable assumptions, linked calculations, no hardcoded results). Key tabs: Assumptions (live scenario selector in B4), Revenue_Build, P&L, Cashflow, Metrics_KPIs, Sensitivity, Balance_Sheet. Re-run generator or extend after updating inputs + python skills/xlsx/scripts/recalc.py.")

    add_heading_styled(doc, "Base Case Highlights (36 months)", 2)
    add_bullet(doc, "Y1 (~Jun 2027): ~$320-350k revenue (gradual ramp from bizdev system + early Phase 4 capacity lift).")
    add_bullet(doc, "Y2: ~$480k (more clients, utilization ~29 hrs/wk, first hire impact).")
    add_bullet(doc, "Y3: $500k+ target hit (or exceeded); ~14 clients, 32+ hrs/wk effective, diversified base.")
    add_bullet(doc, "Cumulative 36mo revenue: ~$1.42M (Base).")
    add_bullet(doc, "Gross margin ~78% throughout; EBITDA 38-45% (operating leverage from Navi + low fixed costs).")
    add_bullet(doc, "Cash position strong and growing; minimal WC needs. Already profitable.")
    add_bullet(doc, "App revenue modeled at $0 in Base (per founder explicit priority); small bonus only in Optimistic.")

    add_heading_styled(doc, "Scenarios & Sensitivity", 2)
    add_bullet(doc, "~$380-420k at 36mo (slower acquisition 1/yr, delayed Navi lift, Dova concentration lingers). Still successful services growth; app stays 100% internal.", "Conservative: ")
    add_bullet(doc, "$650k+ (faster acquisition, full Navi + hire leverage, $25-50k app product upside from 5-8 peer licenses). Includes small capital injection for acceleration.", "Optimistic: ")
    add_bullet(doc, "New client acquisition rate (+/- $120k at Y3), Dova retention/expansion (+/- $80k), timing of Phase 4 utilization lift (+/- $80k). Focus execution here.", "Highest sensitivity: ")

    add_para(doc, "Full assumptions, monthly detail, formulas, and sensitivity tables live in the .xlsx. All projections conservative relative to market data and founder inputs.", italic=True)

    doc.add_page_break()

    # === 10. MILESTONES ===
    add_heading_styled(doc, "10. Milestones & Timeline (Product + Biz + Team)", 1)
    mile_headers = ["Timeframe", "Product (Roadmap)", "Biz / Revenue", "Team / Ops", "Owner"]
    mile_rows = [
        ["0-6 mo", "Complete Phase 4 core (ref injection polish, related sets, export); runtime hardening", "Build & run bizdev system inside Navi; 1-2 new clients; first case studies; $260-300k run-rate", "Solo; weekly CoS reviews of 90-day plan; all ops in app", "Founder"],
        ["6-12 mo", "Phase 5 start or Billing Depth; app alpha to 2-3 peers for feedback", "$320-380k run-rate; 7-8 clients; first conference; app alpha validated internally", "Solo + selective contractor if needed; document processes in Navi", "Founder"],
        ["12-24 mo", "Polish + any deferred; global search / reporting if high value", "$420-480k; 9-11 clients; diversified (Dova <60%); first hire justified", "First hire (junior reg/ops) ~mo18; Navi for onboarding", "Founder + Hire 1"],
        ["24-36 mo", "Mature production platform; optional product packaging", "$500k+ services (100%); app sales as bonus if pursued", "1-2 domain + optional app support; founder on high-value only", "Founder + Team"],
    ]
    create_table(doc, mile_headers, mile_rows, [0.9, 2.0, 2.0, 1.8, 1.0])

    doc.add_page_break()

    # === 11. RISKS ===
    add_heading_styled(doc, "11. Risks & Mitigations", 1)
    add_bullet(doc, "HIGH. Mitigation: Navi-powered systematic bizdev is the entire 0-6mo focus; case studies + referrals from existing; diversification is non-negotiable gate before any hiring.", "Revenue concentration (Dova ~90%): ")
    add_bullet(doc, "MED-HIGH (current state per founder: \"doesn't save me time currently\"). Mitigation: Smallest-safe Phase 4 completion is top product priority (already partially delivering); fallback to Grok for near-term; measure actual hours before/after in app itself.", "App fails to deliver promised time savings / capacity: ")
    add_bullet(doc, "HIGH. Mitigation: Force the process inside Navi CoS (templates, recurring tasks, Intel triggers, proposal generation). Weekly review against 90-day plan. App makes it low-friction.", "Bizdev execution (founder has no time/strategy today): ")
    add_bullet(doc, "MED. Mitigation: Memory system + Navi as knowledge capture + first hire as delegation layer. Founder focuses on what only he can do.", "Key-person / founder capacity: ")
    add_bullet(doc, "LOW-MED. Mitigation: Intel/Pulse monitors exactly this for clients and self; diversified client base; high-value work (strategy, evidence) remains sticky even if volumes fluctuate. Local/privacy is defensive.", "Regulatory / market demand shift: ")
    add_bullet(doc, "LOW (by design). Mitigation: Explicitly secondary; only after services $350k+ and internal proof. No capital or team allocated until validated.", "App productization distraction or failure: ")
    add_bullet(doc, "MED. Mitigation: General tools (ChatGPT) are table stakes. Navi's moats (your memory + domain + full ops integration + local) are hard to replicate quickly. Vertical precedent (Harvey) shows domain + workflow wins.", "Competition / commoditization of AI drafting: ")

    doc.add_page_break()

    # === 12. ASSUMPTIONS ===
    add_heading_styled(doc, "12. Assumptions Log & Sensitivity", 1)
    add_para(doc, "See full live model in the .xlsx (Assumptions tab). Selected key (editable, blue/yellow per skill):")
    add_bullet(doc, "Base revenue $230k (founder data); 5 clients, 90% Dova.")
    add_bullet(doc, "36mo target $500k services (founder); 100% consulting.")
    add_bullet(doc, "New clients/yr Base: 2.0 (Cons 1.0, Opt 3.5). Avg first-year value $45k.")
    add_bullet(doc, "Navi utilization lift: 20% by mo12, 30% by mo24 (tied to Phase 4/5).")
    add_bullet(doc, "First hire mo18 Base at $105k; timing shifts with scenario.")
    add_bullet(doc, "Gross margin 78%, inflation 3%, etc.")
    add_bullet(doc, "App product revenue $0 in Base/Cons (founder priority); small in Opt.")

    add_para(doc, "Research Sources (selected): Fortune Business Insights (medical devices $572B 2025); MarketsandMarkets (IVD); meddeviceguide.com & consultfees.com (2026 consultant rates $275-450/hr, project fees); Deloitte/PwC 2026 AI reports (enterprise adoption, agentic workflows); regtech market projections (22.8% CAGR); Harvey AI pricing benchmarks ($400-1200/seat); innolitics analysis (AI/ML SaMD clearance equity value). Full web results available. All numbers conservative relative to market data.", italic=True)

    add_para(doc, "Document prepared June 2026. Next actions: Open the .docx and .xlsx, update Assumptions tab with any refinements, execute the 90-day plan inside Navi itself (CoS + Intel + Workspace), re-evaluate at 6 months against milestones. This is a living blueprint — the app will help keep it current.", bold=True)

    # Footer
    doc.add_paragraph()
    end = doc.add_paragraph()
    end.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = end.add_run("— End of Business Plan —")
    run.bold = True
    run.font.size = Pt(10)

    align = doc.add_paragraph()
    align.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = align.add_run("Aligned to docs/consultant-os-roadmap.md (approved fixed plan) and actual app state per roadmap_status.md + contributor_guide.md + founder inputs.")
    run.font.size = Pt(8)
    run.italic = True
    run.font.color.rgb = RGBColor(100, 100, 100)

    doc.save(OUT_FILE)
    print(f"Created: {OUT_FILE}")
    return OUT_FILE

if __name__ == "__main__":
    main()