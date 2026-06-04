// SUPERSEDED / ARCHIVED per review (Issue 6 + re-review): python-docx generator (generate_business_plan_docx.py) is the active/maintained source for .docx (matches app billing/docx_render patterns, reliable cross-platform). This JS file is kept for reference only; do not use for production .docx. Run the Python generator instead. Added 2026-06-01.
const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, Header, Footer, 
        AlignmentType, HeadingLevel, BorderStyle, WidthType, ShadingType, PageNumber, 
        PageBreak, LevelFormat } = require('docx');
const fs = require('fs');
const path = require('path');

const OUT_FILE = path.join(__dirname, 'NaviSsurance_Business_Plan_June2026.docx');

// Border helper
const thinBorder = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: thinBorder, bottom: thinBorder, left: thinBorder, right: thinBorder };

// Helper cell
function cell(text, opts = {}) {
    const p = new Paragraph({ 
        children: [new TextRun({ text: String(text), size: opts.size || 20, bold: opts.bold || false, font: "Arial" })],
        alignment: opts.align || AlignmentType.LEFT
    });
    return new TableCell({
        borders,
        width: { size: opts.width || 2000, type: WidthType.DXA },
        shading: opts.shade ? { fill: opts.shade, type: ShadingType.CLEAR } : undefined,
        margins: { top: 60, bottom: 60, left: 80, right: 80 },
        children: [p]
    });
}

const doc = new Document({
    styles: {
        default: { document: { run: { font: "Arial", size: 22 } } },
        paragraphStyles: [
            { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
              run: { size: 32, bold: true, font: "Arial", color: "1E3A5F" },
              paragraph: { spacing: { before: 360, after: 200 }, outlineLevel: 0 } },
            { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
              run: { size: 26, bold: true, font: "Arial", color: "2E5A8C" },
              paragraph: { spacing: { before: 280, after: 160 }, outlineLevel: 1 } },
            { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
              run: { size: 24, bold: true, font: "Arial", color: "3D6E9E" },
              paragraph: { spacing: { before: 200, after: 120 }, outlineLevel: 2 } },
        ]
    },
    numbering: {
        config: [
            { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
                style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
            { reference: "numbers", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
                style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
        ]
    },
    sections: [{
        properties: {
            page: {
                size: { width: 12240, height: 15840 }, // US Letter
                margin: { top: 1080, right: 1080, bottom: 1080, left: 1080 }
            }
        },
        headers: {
            default: new Header({ children: [new Paragraph({
                children: [new TextRun({ text: "NaviSure Consulting | NaviSsurance Business Plan – Confidential | June 2026", size: 18, italics: true, color: "666666", font: "Arial" })],
                alignment: AlignmentType.CENTER
            })] })
        },
        footers: {
            default: new Footer({ children: [new Paragraph({
                children: [new TextRun({ text: "Page ", size: 18, font: "Arial" }), new TextRun({ children: [PageNumber.CURRENT], size: 18, font: "Arial" }), new TextRun({ text: " | Grounded in actual app capabilities (roadmap_status.md, consultant-os-roadmap.md) and founder inputs", size: 16, color: "666666", font: "Arial" })],
                alignment: AlignmentType.CENTER
            })] })
        },
        children: [
            // COVER
            new Paragraph({ spacing: { before: 1200 } }),
            new Paragraph({ children: [new TextRun({ text: "NAVISURE CONSULTING", size: 48, bold: true, font: "Arial", color: "1E3A5F" })], alignment: AlignmentType.CENTER }),
            new Paragraph({ children: [new TextRun({ text: "&", size: 28, font: "Arial" })], alignment: AlignmentType.CENTER }),
            new Paragraph({ children: [new TextRun({ text: "NAVISURANCE (CONSULTANT OS)", size: 44, bold: true, font: "Arial", color: "2E5A8C" })], alignment: AlignmentType.CENTER }),
            new Paragraph({ spacing: { before: 400 } }),
            new Paragraph({ children: [new TextRun({ text: "COMPREHENSIVE BUSINESS PLAN FOR COMPANY GROWTH", size: 28, bold: true, font: "Arial" })], alignment: AlignmentType.CENTER }),
            new Paragraph({ spacing: { before: 200 } }),
            new Paragraph({ children: [new TextRun({ text: "Incorporating the NaviSsurance AI-Powered Operations Platform", size: 22, font: "Arial", italics: true })], alignment: AlignmentType.CENTER }),
            new Paragraph({ spacing: { before: 600 } }),
            new Paragraph({ children: [new TextRun({ text: "June 2026", size: 24, font: "Arial" })], alignment: AlignmentType.CENTER }),
            new Paragraph({ children: [new TextRun({ text: "Founder: Dr. Adam Odeh | NaviSure Consulting", size: 20, font: "Arial" })], alignment: AlignmentType.CENTER }),
            new Paragraph({ children: [new TextRun({ text: "Prepared with deep grounding in current app (Phases 1-4 status), approved roadmap, and founder interviews", size: 18, font: "Arial", color: "555555" })], alignment: AlignmentType.CENTER }),
            new Paragraph({ spacing: { before: 400 } }),
            new Paragraph({ children: [new TextRun({ text: "CONFIDENTIAL – For internal planning use", size: 18, bold: true, color: "AA0000", font: "Arial" })], alignment: AlignmentType.CENTER }),

            new Paragraph({ children: [new PageBreak()] }),

            // EXEC SUMMARY
            new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("1. Executive Summary")] }),
            
            new Paragraph({ children: [new TextRun({ text: "NaviSure Consulting (founded by Dr. Adam Odeh) is a specialized MedTech regulatory consulting practice focused on AI/ML SaMD, IVD/LDT, and compliance-heavy device work. Current run-rate ~$230k (last 12 months), with ~90% concentration in a single high-value fractional VP RA/QA engagement (Dova Health Intelligence) plus 4 other active clients. The founder operates solo at 70% billable / 25% app development / 5% bizdev, with very low overhead (~$400/mo business expenses) and comfortable bootstrap runway.", size: 20 })] }),
            new Paragraph({ spacing: { before: 120 } }),
            new Paragraph({ children: [new TextRun({ text: "The core asset and growth lever is ", size: 20 }), new TextRun({ text: "NaviSsurance (\"Navi\" / Consultant OS)", bold: true, size: 20 }), new TextRun({ text: " — a mature desktop-first AI operations platform (Python/PyQt6 + SQLite + local Qwen3-14B + Grok orchestration) that functions as a \"small, highly competent team\" exclusively for the user. It delivers deep layered memory, proactive regulatory/competitive Intel (Pulse agent), Chief of Staff planning & delegation, high-quality document production with historical work reuse (Workspace Phase 4 advancing), native billing/time/invoicing, evidence-first lead gen (openFDA enriched), compliance review, and client dossiers. Per docs/roadmap_status.md (May 2026), Phase 1 (Memory & Retrieval) is 100% complete; Phase 2/3 (Intel, CoS briefings, compliance cross-links) largely delivered; Phase 4 (Workspace production engine with real historical reference injection) partially live and highest-leverage next step.", size: 20 })] }),
            new Paragraph({ spacing: { before: 120 } }),
            new Paragraph({ children: [new TextRun({ text: "Vision (aligned to approved consultant-os-roadmap.md): Grow to $500k total revenue in 36 months, 100% from consulting services, using Navi as the internal operating system and staff replacement to (a) solve the founder's #1 blocker — \"no time and no strategy for bizdev\" — by having the app itself drive outreach, proposals, and pipeline; (b) deliver 20-30%+ capacity/utilization lift via faster, higher-quality deliverables that reuse real past work; (c) free founder time for high-value client/FDA interactions and personal/family life; and (d) enable justified first hire (domain expert) once client base supports it. App monetization (subscription to peer solo/boutique MedTech consultants) is explicitly secondary/optional bonus — founder priority is services scale. Low CAC, high LTV, exceptional unit economics.", size: 20 })] }),

            new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun("Key Numbers (Base Case)")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("Current: $230k rev, 5 clients (heavy Dova concentration), solo, 0 external app users, Phase 1-3 advanced.")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("36-month target: $500k services revenue (100% consulting); app sales as upside only.")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("Timeline: 36 months realistic (founder input); systematic bizdev + Phase 4/5 Navi delivery as enablers.")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("Margins: ~78% gross; strongly positive EBITDA from low overhead. LTV:CAC >30x via organic + app leverage.")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("Capital: Bootstrap primary; open to small business loan ($25-75k) for acceleration/events/hire bridge once clients justify.")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("Risk mitigations: Revenue diversification via Navi-powered GTM is #1 priority; app itself is the tool to execute it.")] }),

            new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun("Immediate 90-Day Action Plan (Start Monday)")] }),
            new Paragraph({ numbering: { reference: "numbers", level: 0 }, children: [new TextRun("Prioritize completion of highest-leverage Phase 4 Workspace items (historical ref injection polish, related-set generation, export paths) per roadmap to deliver first measurable time savings vs plain Grok.")] }),
            new Paragraph({ numbering: { reference: "numbers", level: 0 }, children: [new TextRun("Use Chief of Staff + AM Sweep + Intel to build and execute a 90-day systematic bizdev plan inside the app: target 8-12 qualified outreaches, 2-3 proposal drafts using Workspace + memory of past wins, track everything in Clients/Tasks/Leads. Goal: land 1 new client.")] }),
            new Paragraph({ numbering: { reference: "numbers", level: 0 }, children: [new TextRun("Create 2 client case studies / win stories (one Dova, one other) using app workflows; use in LinkedIn content and future pitches.")] }),
            new Paragraph({ numbering: { reference: "numbers", level: 0 }, children: [new TextRun("Review this plan + full Assumptions tab in the accompanying Financial_Projections xlsx; decide on any small loan for 1-2 key conferences (RAPS/MedTech) or content production.")] }),
            new Paragraph({ numbering: { reference: "numbers", level: 0 }, children: [new TextRun("Pilot \"Navi OS for consultants\" alpha with 1-2 trusted peer solos for feedback (internal validation first).")] }),
            new Paragraph({ numbering: { reference: "numbers", level: 0 }, children: [new TextRun("Weekly CoS review of progress against this 90-day plan; adjust using the app itself.")] }),

            new Paragraph({ spacing: { before: 200 } }),
            new Paragraph({ children: [new TextRun({ text: "This plan is deliberately grounded in the actual shipped state of the app (no overclaiming), founder answers (services-first, 36mo $500k, app as internal lever, referral-only GTM today, low burn), and credible external data (MedTech devices $572B+, reg consultants $250-450/hr, vertical AI pricing benchmarks). It extends the approved product roadmap without contradiction. Actionable starting Monday.", size: 20, italics: true })] }),

            new Paragraph({ children: [new PageBreak()] }),

            // COMPANY + VISION
            new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("2. Company & Vision")] }),
            new Paragraph({ children: [new TextRun({ text: "NaviSure Consulting provides high-value, evidence-based regulatory strategy, 510(k)/De Novo/PMCF support, QMS/compliance, and fractional RA/QA leadership (e.g., current Dova Health Intelligence engagement) to MedTech companies, with emphasis on AI/ML SaMD, IVD/LDT, and complex compliance work. The founder brings deep domain expertise; the competitive edge is increasingly the NaviSsurance platform itself.", size: 20 })] }),

            new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun("Vision (Directly from Approved Product Roadmap)")] }),
            new Paragraph({ children: [new TextRun({ text: "\"NaviSsurance becomes a single, intelligent workspace that functions like a small, highly competent team working exclusively for you. It maintains deep memory of your clients and past work, proactively monitors the regulatory and competitive environment, helps you plan and prioritize, captures time and revenue cleanly, and dramatically accelerates the creation of high-quality client deliverables by intelligently reusing your real historical work.\"", size: 20, italics: true })] }),
            new Paragraph({ spacing: { before: 80 } }),
            new Paragraph({ children: [new TextRun({ text: "This business plan operationalizes that vision for company growth: Navi is not a side project to spin out — it is the operating system that lets a solo founder scale services revenue to $500k in 36 months while regaining personal time, with optional future product upside.", size: 20 })] }),

            new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun("Guiding Principles (from roadmap, applied to biz)")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("One coherent system (Navi runs the entire practice: planning, intel, production, billing, memory).")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("Memory & retrieval first-class (your real past work is the moat and accelerator).")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("Reduce context switching and admin overhead (the founder's #1 pain).")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("Proactive intelligence valuable but never annoying (Pulse raises signals for planning).")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("Billing/time native and low-friction (already strong in app).")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("Safe, gradual expansion without constant rework (smallest-safe edits per contributor_guide).")] }),

            new Paragraph({ children: [new PageBreak()] }),

            // PRODUCT DEEP DIVE
            new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("3. Product Deep Dive & Roadmap Alignment")] }),
            new Paragraph({ children: [new TextRun({ text: "NaviSsurance is a desktop-first (PyQt6), local-first/privacy-first (SQLite source-of-truth, optional local runtime + FastAPI, optional xAI Grok for complex/CoS flows), highly specialized AI platform for MedTech regulatory consultants. It is not a general chat wrapper — it is workflow-native with specialist named agents (Atlas, Quill, Sentinel, Lex, Scout, Mason, Ledger, Archive, Pulse, Shield), layered durable memory (user/cos/agent/assignment), and production-grade integrations (Playwright browser, RAG/Chroma, APScheduler jobs, DOCX/PDF export, Google Drive/Dropbox file intelligence).", size: 20 })] }),

            new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun("Current Capabilities (Grounded in May 2026 State)")] }),
            new Paragraph({ children: [new TextRun({ text: "From docs/overview.md + roadmap_status.md + contributor_guide (source of truth order: code > current docs > roadmap):", size: 20 })] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Dashboard: ", bold: true, size: 20 }), new TextRun({ text: "Daily briefing, Google Calendar, unreplied email triage, tasks, MedTech news (7-day persistence).", size: 20 })] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Chief of Staff: ", bold: true, size: 20 }), new TextRun({ text: "Natural language planning, AM Sweeps (Dispatch/Prep/Yours/Skip buckets + time-block proposals + parallel ASSIGN actions), structured daily briefings (billing snapshot, high-prio deliverables, suggested focus, Pulse context), delegation board with health signals (overdue, blocked, NEEDS_INPUT), assignment lifecycle + artifacts.", size: 20 })] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Intel / Pulse: ", bold: true, size: 20 }), new TextRun({ text: "Watchlists, background monitoring (runtime jobs), findings with importance/raised flags + notes, hybrid local retrieval (keyword + vector + LLM relevance filter in intel_retrieval.py), client/project linking, private theme memory, badge on tab, cross-links to CoS.", size: 20 })] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Workspace (Phase 4 advancing): ", bold: true, size: 20 }), new TextRun({ text: "Template-driven DOCX generation, outline + section review, dual-LLM (Grok gen + review), direct export to client folders, ", size: 20 }), new TextRun({ text: "auto-injection of strong historical references", bold: true, size: 20 }), new TextRun({ text: " (Phase 1 get_relevant_past_documents + style/structure guidance from real past work) — now live for production use with zero manual clicks when matches surface.", size: 20 })] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Billing (mature): ", bold: true, size: 20 }), new TextRun({ text: "Hourly + deliverable/SoW modes per client, manual + timer time entry, client_deliverables table, branded DOCX/PDF invoice drafts from templates (default + imported), monthly autorun (runtime or GUI), history, numbering, review-first export. Unified on main clients table + legacy billing_clients parity.", size: 20 })] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Clients / Dossier (largely complete per TODO): ", bold: true, size: 20 }), new TextRun({ text: "Rich profiles (billing_mode, default_rate, contacts, notes, aliases), linked memory (Teach client), projects/assignments/tasks, recent activity, quick actions, Compliance Status section (Phase 2 cross-link via Intel), Relevant Past Work surface (Phase 1).", size: 20 })] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Leads (evidence-first): ", bold: true, size: 20 }), new TextRun({ text: "Grok + openFDA 510(k) enrichment, scoring (fit/signals/confidence), personalized outreach drafts, status tracking, one-click follow-up task creation. Strict \"sources required\" anti-hallucination.", size: 20 })] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Memory (foundation, Phase 1 100%): ", bold: true, size: 20 }), new TextRun({ text: "Layered (user_memory global, cos_memory, agent_memory private per specialist, assignment_memory short-horizon), explicit Teach Navi:/Teach <Agent>:, passive extraction + approval, promotion paths, entity scoping (client/project), daily/weekly reflections, summary-first chat retrieval + raw grounding, Mem0 optional local supplement.", size: 20 })] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Other active: ", bold: true, size: 20 }), new TextRun({ text: "Deep Research (iterative web, synthesis to reusable brief), Meetings (AssemblyAI transcription + task extraction + DOCX export), Notes (living docs), Compliance checker (Grok-assisted SOP/PDF/URL vs ISO/FDA), runtime scheduler + local API scaffolding, browser tools (Playwright), tool registry.", size: 20 })] }),

            new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun("Approved Roadmap (consultant-os-roadmap.md) → Biz Value Mapping")] }),
            new Paragraph({ children: [new TextRun({ text: "This plan aligns exactly to the fixed 5-phase order (no reordering). Product milestones are gates for biz outcomes:", size: 20 })] }),

            // Roadmap table (simplified)
            createRoadmapTable(),

            new Paragraph({ spacing: { before: 160 } }),
            new Paragraph({ children: [new TextRun({ text: "Phase 4 (Workspace Production Engine) is the single highest-leverage item for the $500k goal: it directly attacks deliverable production time (the bulk of consulting hours) by injecting real historical examples automatically. Current partial implementation (ref injection + style guidance in workspace_tab.py / file_handler.py / workspace_generation.py per recent IMPLs) already provides \"zero manual clicks\" value when strong matches surface. Full completion + consistency checking + related-set generation + Drive export = 2-3x effective speed on complex packages (Validation Plan + RMF + Traceability etc.). This is what lets a solo founder take on more or higher-value work without proportional time increase.", size: 20 })] }),

            new Paragraph({ children: [new PageBreak()] }),

            // MARKET
            new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("4. Market Opportunity")] }),
            new Paragraph({ children: [new TextRun({ text: "Primary focus is growing the services business (MedTech regulatory consulting) to $500k using Navi as the differentiator and capacity multiplier. Product TAM for Navi is secondary and viewed as an optional upside once the platform is proven internally and the services engine is firing.", size: 20 })] }),

            new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun("TAM / SAM / SOM (Services-First Lens)")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "TAM: ", bold: true, size: 20 }), new TextRun({ text: "Global MedTech regulatory/quality consulting spend. Med devices market $572B (2025) → $605B (2026), CAGR ~6.9% (Fortune Business Insights). IVD subset $109B (2025) → $158B (2030), CAGR 7.6%. Regulatory services are a high-margin slice of device CRO/services (~$10-11B device CRO TAM). AI/ML SaMD boom + EU IVDR + increased FDA software scrutiny drive demand for specialized expertise.", size: 20 })] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "SAM: ", bold: true, size: 20 }), new TextRun({ text: "US + EU founders/startups + small-mid device companies needing SaMD/IVD regulatory strategy, 510(k)/De Novo prep, QMS lift, clinical evidence plans, or fractional RA/QA. High willingness to pay: specialist consultants $275-450/hr (2026 benchmarks); typical 510(k) consulting project $17.5k-$50k+. Equity value creation from clearances is massive (one analysis: $51M submission costs → $1.54B attributable equity in 14 trading days across cohort, 30x ROI).", size: 20 })] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "SOM (36mo): ", bold: true, size: 20 }), new TextRun({ text: "Founder-controlled: grow from 5 clients / $230k to ~12-14 clients / $500k via 2-3 new clients/year (mix project + retainers), modest rate expansion, utilization lift from Navi, and diversification away from Dova concentration. Achievable with systematic (app-driven) bizdev + demonstrated delivery speed/quality edge. Addressable via referrals + content + 1-2 conferences/year initially.", size: 20 })] }),

            new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun("Buyer Personas & Trends")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Primary (services): ", bold: true, size: 20 }), new TextRun({ text: "CEOs/founders of AI SaMD or IVD startups (need fast, defensible regulatory path + evidence plan + timeline + risks — exactly the 10-day sprint offering in ceo_regulatory_strategy_sprint.md); small device cos lacking in-house reg bandwidth; larger cos needing surge or specialized (cyber, human factors, SaMD) support.", size: 20 })] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Secondary (future app): ", bold: true, size: 20 }), new TextRun({ text: "Solo MedTech/regulatory consultants and 5-20 person boutiques in the same niche (US/EU focus) who are drowning in admin, context switching, and proposal/drafting volume — exactly the founder's current pain. They already use Grok/ChatGPT + Notion/Obsidian/custom scripts. Navi replaces \"potential staff\" with a coherent, memory-rich, local/privacy-safe system.", size: 20 })] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Trends 2026: ", bold: true, size: 20 }), new TextRun({ text: "Explosive growth in AI/regtech (regtech mkt $19.6B → $82B by 2032, 22.8% CAGR). Enterprise AI adoption scaling (Deloitte/PwC 2026 reports: agentic workflows, 50%+ worker access growth). Vertical domain AI (Harvey legal at $400-1200/seat/mo) proves willingness to pay premium for specialized tools. Regulatory complexity for software/AI devices is increasing, not decreasing — perfect tailwind for both services and a purpose-built OS.", size: 20 })] }),

            new Paragraph({ children: [new PageBreak()] }),

            // COMPETITIVE
            new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("5. Competitive Positioning")] }),
            new Paragraph({ children: [new TextRun({ text: "NaviSsurance occupies a unique \"Consultant Operating System\" niche. No direct competitor combines deep MedTech/regulatory domain specialization, layered durable memory of real historical client work, local/privacy-first execution, proactive specialist agents (Pulse for intel), native full-lifecycle ops (CoS + Billing + Leads + Workspace), and production document generation that reuses your actual past deliverables.", size: 20 })] }),

            new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun("Positioning Matrix (Simplified)")] }),
            createCompetitorTable(),

            new Paragraph({ spacing: { before: 160 } }),
            new Paragraph({ children: [new TextRun({ text: "Moats (durable because they are data + workflow + domain + architecture, not just prompts):", size: 20 })] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Your data moat: ", bold: true, size: 20 }), new TextRun({ text: "Layered memory (user/agent/assignment) + RAG over your real Google Drive/Dropbox client files + past deliverables + intel findings + time entries. This compounds with every project. Phase 4 makes it production-visible in every new document.", size: 20 })] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Domain depth: ", bold: true, size: 20 }), new TextRun({ text: "Specialist agents, prompts, openFDA enrichment, compliance cross-links, regulatory intel watchlists, SaMD/IVD-specific workflows — not generic \"write a plan.\"", size: 20 })] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Local + privacy: ", bold: true, size: 20 }), new TextRun({ text: "SQLite + optional local LLM + no forced cloud. Critical for clients sharing sensitive design history, clinical data, or pre-submission materials. Aligns with HIPAA/GDPR expectations and founder security.md posture.", size: 20 })] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Full-stack integration: ", bold: true, size: 20 }), new TextRun({ text: "Memory → Intel → CoS planning → Workspace production → Billing time capture → Client dossier — one desktop app. No context switching tax. The \"small competent team\" is real and always available.", size: 20 })] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Option value: ", bold: true, size: 20 }), new TextRun({ text: "Proven internally first, then optionally productized for peers. Low risk of distraction from services core.", size: 20 })] }),

            new Paragraph({ children: [new PageBreak()] }),

            // BUSINESS MODEL & PRICING
            new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("6. Business Model, Pricing & Packaging")] }),
            new Paragraph({ children: [new TextRun({ text: "Per founder inputs: 100% of the $500k target is services revenue. App monetization is unknown/secondary bonus and not required for success. The model is therefore hybrid with services as the engine and Navi as the secret weapon / moat / optional product line.", size: 20 })] }),

            new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun("Primary: Services (Navi-Powered)")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Offerings: ", bold: true, size: 20 }), new TextRun({ text: "CEO Regulatory Strategy Sprints (fixed-scope 10-day board-ready memo + research brief + execution plan, per existing sprint doc), 510(k)/De Novo/PMCF protocol support, QMS/ISO 13485/21 CFR 820 implementation & remediation, clinical evidence strategy, cybersecurity/human factors, fractional VP RA/QA (Dova model), ongoing retainer support.", size: 20 })] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Pricing (market-aligned + premium for speed/quality): ", bold: true, size: 20 }), new TextRun({ text: "Hourly $275-400+ (specialist rates); project 510(k) packages $18k-60k+; retainers $8-20k/mo for fractional/executive roles. Premium justified by faster turnaround, higher first-pass quality (historical reuse + consistency), proactive intel, and clean billing from the same system.", size: 20 })] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Attach / Upsell: ", bold: true, size: 20 }), new TextRun({ text: "Navi \"powered delivery\" positioning in every proposal/pitch — live demo of CoS/memory/Workspace/Intel during sales process is a powerful differentiator (\"this is the OS I use to deliver for clients like you\"). Future: optional client-facing Navi workspace or intel briefings as add-on.", size: 20 })] }),

            new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun("Secondary / Optional: App Productization")] }),
            new Paragraph({ children: [new TextRun({ text: "Only after internal proof and services engine is stable (post $350k+ run-rate). Target: solo and small-boutique (5-20 person) MedTech/regulatory consultants in SaMD/IVD niche (US/EU). They face the same admin/memory/context/bizdev pain the founder does today.", size: 20 })] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Hypothesized packaging (conservative; test with alpha): ", bold: true, size: 20 })] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("Solo Consultant: $1,999/yr or $199/mo (full desktop + local models + updates + basic support)")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("Small Firm (up to 5 seats): $4,999/yr (shared memory pools, team assignment features, priority support)")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("Enterprise / In-house (per seat or site): custom, $8k-15k/yr + onboarding services")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Services bundle (high-margin upsell): ", bold: true, size: 20 }), new TextRun({ text: "$3-8k one-time \"Navi OS Setup + Training + Custom Agent + Template Pack\" for new buyers (leverages founder's expertise + app). 30% attach target.", size: 20 })] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Rationale: ", bold: true, size: 20 }), new TextRun({ text: "Vertical AI precedent (Harvey $400-1200/seat/mo for legal; vertical SaaS addons $15-65/user/mo). Reg professionals pay for time savings and risk reduction. Desktop/local/privacy is a feature, not a bug, for this ICP. Low CAC via founder's content + network + peer referrals.", size: 20 })] }),

            new Paragraph({ children: [new PageBreak()] }),

            // GTM
            new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("7. Go-to-Market Strategy")] }),
            new Paragraph({ children: [new TextRun({ text: "Founder reality: \"I have no time to find clients, and no strategy for how to do so even if I did. It's been all referrals so far.\" This is the exact problem Navi (CoS + Intel + Workspace + Leads) is built to solve. GTM is therefore \"use the product to sell the services, and prove the product internally first.\"", size: 20 })] }),

            new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun("Phased GTM (Services Primary)")] }),
            new Paragraph({ children: [new TextRun({ text: "0-6 months (Foundation + First Proof):", bold: true, size: 20 })] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("Inside Navi: Build the bizdev operating system (CoS templates for outreach sequences, Intel watchlists for regulatory triggers that create client needs, Workspace proposal templates seeded with past wins, Leads tab for target device cos, full pipeline tracking in Clients/Tasks). Run AM Sweeps that explicitly include \"bizdev\" bucket. Goal: 8-12 outreaches/month, 2-3 proposals, 1-2 new clients.")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("Content flywheel: Publish 1-2 LinkedIn/FDA-update posts per week, generated/supported by Pulse intel + Deep Research briefs (\"What the latest FDA AI guidance actually means for SaMD founders\"). Use app in public demos where appropriate.")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("Sales enablement: Create live 10-15 min pitch demo of Navi (CoS morning plan → Intel on a client's regulatory area → Workspace generating a section with real past reference → Billing draft). This is the ultimate differentiator vs generic consultants with ChatGPT.")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("Dova & existing: Deepen relationship, ask for referrals/intros, document case study using app workflows.")] }),

            new Paragraph({ children: [new TextRun({ text: "6-18 months (Systematic + Events):", bold: true, size: 20 })] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("1-2 key conferences/year (RAPS Regulatory Convergence, MedTech Conference, specific SaMD/IVD events). Budget $8-15k/yr for booth or speaking (use app to prepare talks/proposals). Low CAC because founder is the speaker/expert.")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("Partnerships: Referral arrangements with complementary boutiques (clinical strategy, reimbursement, software dev for med devices). Navi makes handoff clean (shared memory artifacts, assignment export).")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("App alpha: 2-3 peer solo consultants get free/steep-discount Navi for 3-6 months in exchange for structured feedback + testimonials. Internal proof first, then light product marketing.")] }),

            new Paragraph({ children: [new TextRun({ text: "18-36 months (Scale):", bold: true, size: 20 })] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("Hire first domain expert (reg consultant) — Navi dramatically lowers onboarding cost (memory + CoS delegation + templates).")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("If app traction from alpha: formalize Solo/Firm tiers, add to website, light paid acquisition (LinkedIn ads targeting \"regulatory consultant\" or \"SaMD founder\" keywords).")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("Services scale: larger retainers, more complex programs, geographic expansion (EU IVDR work) enabled by capacity from Navi + hire.")] }),

            new Paragraph({ children: [new PageBreak()] }),

            // TEAM & OPS
            new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("8. Team & Hiring Roadmap + Operations")] }),
            new Paragraph({ children: [new TextRun({ text: "Current: Solo founder. No contractors. Extremely low overhead.", size: 20 })] }),

            new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun("Hiring Gates (Revenue- and Capacity-Triggered)")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [
                new TextRun({ text: "First hire (target ~month 18, once $300k+ run-rate or 7+ active clients): ", bold: true, size: 20 }),
                new TextRun({ text: "Junior-to-mid regulatory consultant or ops/admin hybrid ($90-120k fully loaded). Profile: strong writer, detail-oriented, eager to learn SaMD/IVD. Navi makes this person productive in weeks (memory transfer, CoS assigns scoped work, Workspace templates, client dossiers). Goal: delegate day-to-day drafting, research, compliance checks, meeting notes — founder retains client relationships, FDA calls, strategy, bizdev.", size: 20 })
            ] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Second hire (post $450k or clear product traction): ", bold: true, size: 20 }), new TextRun({ text: "Either additional domain specialist or first dedicated app/dev support if productizing (or bizdev/sales if services volume justifies).")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Org chart evolution: ", bold: true, size: 20 }), new TextRun({ text: "Founder (strategy, clients, FDA, vision) → 1-2 domain delivery + 0-1 ops/app. Flat, high-trust, enabled by Navi as the coordination layer (no need for heavy management overhead).", size: 20 })] }),

            new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun("How Navi Runs the Company (Ops)")] }),
            new Paragraph({ children: [new TextRun({ text: "The entire business operates inside Navi today and will continue to do so. This is the ultimate proof point and moat:", size: 20 })] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Planning & Prioritization: ", bold: true, size: 20 }), new TextRun({ text: "Daily CoS briefings + AM Sweeps (include explicit bizdev bucket + client health + billing snapshot). Weekly reflections.")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Intel & Positioning: ", bold: true, size: 20 }), new TextRun({ text: "Pulse monitors FDA guidance, competitor clearances, standards updates — surfaced in CoS for client work and for own content/bizdev targeting.")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Delivery: ", bold: true, size: 20 }), new TextRun({ text: "All client deliverables start in Workspace with automatic historical reference injection + consistency checking. Meeting notes/transcripts → tasks → memory.")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Pipeline & CRM: ", bold: true, size: 20 }), new TextRun({ text: "Leads tab (or targeted use of it) + Clients dossiers + Tasks + assignment board. Everything linked.")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Finance: ", bold: true, size: 20 }), new TextRun({ text: "Native time entry linked to clients/projects, invoice drafts from templates, autorun, revenue visibility in CoS briefings.")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Knowledge & Onboarding: ", bold: true, size: 20 }), new TextRun({ text: "All past work, decisions, client context in durable memory. New hire (or future self) has instant access via search + CoS + dossiers.")] }),

            new Paragraph({ children: [new TextRun({ text: "This \"eat your own dogfood at the highest level\" is how a solo founder scales without proportional chaos or burnout. It is also the story that sells the app later.", size: 20, italics: true })] }),

            new Paragraph({ children: [new PageBreak()] }),

            // FINANCIALS
            new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("9. Financials & Projections (See Accompanying Excel for Full Model)")] }),
            new Paragraph({ children: [new TextRun({ text: "Detailed 3-scenario model (Base / Conservative / Optimistic) is in ", size: 20 }), new TextRun({ text: "business-plan/Financial_Projections_NaviSure_June2026_v1.xlsx", bold: true, size: 20 }), new TextRun({ text: " (generated from Python/openpyxl with formulas, color-coded per skill standards: blue inputs/yellow highlights for editable assumptions, linked calculations). Key tabs: Assumptions (with live scenario selector B4), Revenue_Build, P&L, Cashflow, Metrics_KPIs, Sensitivity, Balance_Sheet.", size: 20 })] }),

            new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun("Base Case Highlights (36 months)")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("Y1 (to ~Jun 2027): ~$320-350k revenue (gradual ramp from bizdev system + early Phase 4 capacity lift)")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("Y2: ~$480k (more clients, utilization to ~29 hrs/wk, first hire impact)")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("Y3: $500k+ target hit (or exceeded); ~14 clients, 32+ hrs/wk effective, diversified base")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("Cumulative 36mo revenue: ~$1.42M (Base)")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("Gross margin ~78% throughout; EBITDA 38-45% (operating leverage from Navi + low fixed costs)")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("Cash position strong and growing; minimal WC needs. Already profitable.")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("App revenue modeled at $0 in Base (per founder); small bonus only in Optimistic.")] }),

            new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun("Scenarios & Sensitivity")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Conservative: ", bold: true, size: 20 }), new TextRun({ text: "~$380-420k at 36mo (slower client acquisition 1/yr, delayed Navi lift, Dova concentration lingers). Still successful services growth; app stays 100% internal.")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Optimistic: ", bold: true, size: 20 }), new TextRun({ text: "$650k+ (faster acquisition, full Navi + hire leverage, $25-50k app product upside from 5-8 peer licenses). Includes small capital injection for acceleration.")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Highest sensitivity: ", bold: true, size: 20 }), new TextRun({ text: "New client acquisition rate (+/- $120k at Y3), Dova retention/expansion (+/- $80k), timing of Phase 4 utilization lift (+/- $80k). Focus execution here.")] }),

            new Paragraph({ children: [new TextRun({ text: "Full assumptions, monthly detail, formulas, and sensitivity tables live in the .xlsx. Re-generate or extend after updating inputs.", size: 20 })] }),

            new Paragraph({ children: [new PageBreak()] }),

            // MILESTONES
            new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("10. Milestones & Timeline (Product + Biz + Team)")] }),
            createMilestonesTable(),

            new Paragraph({ children: [new PageBreak()] }),

            // RISKS
            new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("11. Risks & Mitigations")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Revenue concentration (Dova ~90%): ", bold: true, size: 20 }), new TextRun({ text: "HIGH. Mitigation: Navi-powered systematic bizdev is the entire 0-6mo focus; case studies + referrals from existing; diversification is non-negotiable gate before any hiring.")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "App fails to deliver promised time savings / capacity: ", bold: true, size: 20 }), new TextRun({ text: "MED-HIGH (current state per founder). Mitigation: Smallest-safe Phase 4 completion is top product priority (already partially delivering); fallback to Grok for near-term; measure actual hours before/after in app itself.")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Bizdev execution (founder has no time/strategy today): ", bold: true, size: 20 }), new TextRun({ text: "HIGH. Mitigation: Force the process inside Navi CoS (templates, recurring tasks, Intel triggers, proposal generation). Weekly review against 90-day plan. App makes it low-friction.")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Key-person / founder capacity: ", bold: true, size: 20 }), new TextRun({ text: "MED. Mitigation: Memory system + Navi as knowledge capture + first hire as delegation layer. Founder focuses on what only he can do (relationships, FDA, strategy).")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Regulatory / market demand shift: ", bold: true, size: 20 }), new TextRun({ text: "LOW-MED. Mitigation: Intel/Pulse monitors exactly this for clients and self; diversified client base; high-value work (strategy, evidence) remains sticky even if volumes fluctuate. Local/privacy is defensive.")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "App productization distraction or failure: ", bold: true, size: 20 }), new TextRun({ text: "LOW (by design). Mitigation: Explicitly secondary; only after services $350k+ and internal proof. No capital or team allocated until validated.")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun({ text: "Competition / commoditization of AI drafting: ", bold: true, size: 20 }), new TextRun({ text: "MED. Mitigation: General tools (ChatGPT) are table stakes. Navi's moats (your memory + domain + full ops integration + local) are hard to replicate quickly. Vertical precedent (Harvey) shows domain + workflow wins.")] }),

            new Paragraph({ children: [new PageBreak()] }),

            // ASSUMPTIONS & APPENDICES
            new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("12. Assumptions Log & Sensitivity")] }),
            new Paragraph({ children: [new TextRun({ text: "See full live model in the .xlsx (Assumptions tab). Selected key assumptions (editable, blue/yellow per skill):", size: 20 })] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("Base revenue $230k (founder data); 5 clients, 90% Dova.")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("36mo target $500k services (founder); 100% consulting.")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("New clients/yr Base: 2.0 (Cons 1.0, Opt 3.5). Avg first-year value $45k.")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("Navi utilization lift: 20% by mo12, 30% by mo24 (tied to Phase 4/5).")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("First hire mo18 Base at $105k; timing shifts with scenario.")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("Gross margin 78%, inflation 3%, etc.")] }),
            new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: [new TextRun("App product revenue $0 in Base/Cons (founder priority); small in Opt.")] }),

            new Paragraph({ spacing: { before: 200 } }),
            new Paragraph({ children: [new TextRun({ text: "Research Sources (selected): ", bold: true, size: 20 }), new TextRun({ text: "Fortune Business Insights (medical devices $572B 2025); MarketsandMarkets (IVD); meddeviceguide.com & consultfees.com (2026 consultant rates $275-450/hr, project fees); Deloitte/PwC 2026 AI reports (enterprise adoption, agentic workflows); regtech market projections (22.8% CAGR); Harvey AI pricing benchmarks ($400-1200/seat); innolitics analysis (AI/ML SaMD clearance equity value). Full citations and web results in research notes if extended. All numbers conservative relative to market data.", size: 20 })] }),

            new Paragraph({ spacing: { before: 300 } }),
            new Paragraph({ children: [new TextRun({ text: "Document prepared June 2026. Next actions: Open the .docx and .xlsx, update Assumptions tab with any refinements, execute the 90-day plan inside Navi itself, re-evaluate at 6 months against milestones. This is a living blueprint — the app will help keep it current.", size: 20, italics: true })] }),

            // End
            new Paragraph({ spacing: { before: 400 } }),
            new Paragraph({ children: [new TextRun({ text: "— End of Business Plan —", size: 20, bold: true })] }),
            new Paragraph({ children: [new TextRun({ text: "Aligned to docs/consultant-os-roadmap.md (approved fixed plan) and actual app state per roadmap_status.md + contributor_guide.md.", size: 18, color: "666666" })] }),
        ]
    }]
});

// Minimal helper tables
function createRoadmapTable() {
    const rows = [
        ["Phase", "Product Focus (from roadmap)", "Biz Value / Trigger for Growth"],
        ["Phase 4 (Current Priority)", "Workspace Production: historical ref injection, related sets, consistency, Drive export", "2-3x faster high-quality deliverables → higher utilization, win rate, capacity for $500k without burnout"],
        ["Phase 5", "Smart filing, global search, personal dashboards/reporting, UX polish", "Lower friction, better insights, founder time savings realized, easier onboarding of first hire"],
        ["Billing Depth (deferred)", "Semi-auto time, retainers health, multi-template, one-click from dossier", "Cleaner revenue visibility in CoS, higher realization, less admin tax"],
    ];
    return new Table({
        width: { size: 10080, type: WidthType.DXA },
        columnWidths: [1800, 4200, 4080],
        rows: rows.map((r, i) => new TableRow({ children: r.map((t, j) => cell(t, { width: j===0?1800: j===1?4200:4080, shade: i===0 ? "DCE6F1" : undefined, bold: i===0 })) }))
    });
}

function createCompetitorTable() {
    const rows = [
        ["Player", "Strength", "Weakness vs Navi", "Navi Advantage"],
        ["ChatGPT + Notion/Obsidian", "Ubiquitous, cheap, flexible", "No memory of YOUR real work, no domain agents, no billing/intel/CoS integration, context switching, privacy risks", "Durable layered memory + full workflow + local/privacy + reg-specific"],
        ["Harvey / Legal Vertical AI", "Deep domain for law, high willingness to pay", "Wrong domain (law vs MedTech reg), enterprise pricing, no local option, no ops/billing native", "Purpose-built for exact ICP + local + integrated ops at accessible price"],
        ["General regtech / compliance platforms", "Monitoring or QMS features", "Shallow on consulting workflows, no personal memory/reuse of past deliverables, no CoS delegation", "End-to-end Consultant OS with production generation + memory"],
        ["Custom scripts + email/calendar", "Tailored today", "Brittle, no AI, no intelligence layer, high maintenance, no scale", "AI-native, proactive, memory-rich, low maintenance"],
    ];
    return new Table({
        width: { size: 10080, type: WidthType.DXA },
        columnWidths: [2200, 2400, 2800, 2680],
        rows: rows.map((r, i) => new TableRow({ children: r.map((t, j) => cell(t, { width: [2200,2400,2800,2680][j], shade: i===0 ? "DCE6F1" : undefined, bold: i===0, size: 18 })) }))
    });
}

function createMilestonesTable() {
    const rows = [
        ["Timeframe", "Product (Roadmap)", "Biz / Revenue", "Team / Ops", "Owner"],
        ["0-6 mo", "Complete Phase 4 core (ref injection polish, related sets, export); runtime hardening", "Build & run bizdev system inside Navi; 1-2 new clients; first case studies; $260-300k run-rate", "Solo; weekly CoS reviews of 90-day plan; all ops in app", "Founder"],
        ["6-12 mo", "Phase 5 start or Billing Depth; app alpha to 2-3 peers for feedback", "$320-380k run-rate; 7-8 clients; first conference; app alpha validated internally", "Solo + selective contractor if needed; document processes in Navi", "Founder"],
        ["12-24 mo", "Polish + any deferred items; global search / reporting if high value", "$420-480k; 9-11 clients; diversified (Dova <60%); first hire justified", "First hire (junior reg/ops) ~mo18; Navi for onboarding", "Founder + Hire 1"],
        ["24-36 mo", "Mature production platform; optional product packaging", "$500k+ services (100%); app sales as bonus if pursued", "1-2 domain + optional app support; founder on high-value only", "Founder + Team"],
    ];
    return new Table({
        width: { size: 10080, type: WidthType.DXA },
        columnWidths: [1400, 2600, 2400, 2200, 1480],
        rows: rows.map((r, i) => new TableRow({ children: r.map((t, j) => cell(t, { width: [1400,2600,2400,2200,1480][j], shade: i===0 ? "DCE6F1" : undefined, bold: i===0, size: 17 })) }))
    });
}

Packer.toBuffer(doc).then(buffer => {
    fs.writeFileSync(OUT_FILE, buffer);
    console.log(`Created: ${OUT_FILE}`);
}).catch(err => {
    console.error("Docx creation failed:", err);
    process.exit(1);
});