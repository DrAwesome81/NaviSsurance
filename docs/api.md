NaviSsurance API Integrations
Overview
NaviSsurance uses third-party APIs for core functionality: xAI Grok (compliance, study design, lead generation), LinkedIn (posting, authentication), and AssemblyAI (transcription). It also uses a local Llama 3.1-8B-Instruct model for note-taking and chat interactions. API keys are non-transferable; buyers must register their own accounts.

Local AI Model (Llama 3.1-8B-Instruct)

Purpose: Provides AI-powered note formatting, categorization, and chat interactions using a local model for privacy and cost efficiency.
Model: Llama 3.1-8B-Instruct-GGUF (quantized for efficiency).
Configuration:
- Context Window: 8192 tokens
- Response Limit: 1000 tokens
- GPU Layers: 33 (for acceleration)
- Threads: 4 (for CPU processing)
- Temperature: 0.9 (for creative responses)
- Top-p: 0.9 (for response diversity)

Setup:
Download model from Hugging Face: Meta-Llama-3-8B-Instruct-GGUF
Place in local cache directory
Configure model path in core/llama_worker.py

Code: core/llama_worker.py, gui/interface.py (NoteTakingSystem)
Notes: Local processing ensures data privacy; no API costs; requires GPU for optimal performance.

API Details
xAI Grok

Purpose: Analyzes SOPs for compliance (ISO 13485, 21 CFR 820), generates study protocols, and provides lead generation, outputting JSON ([{section, issue, fix, reference}]) for compliance and structured data for leads.
Endpoints: https://api.x.ai/grok (REST API).
Authentication: API key (GROK_API_KEY) in .env.
Setup:
Register at https://x.ai/api.
Obtain SuperGrok subscription (~$20–$100/month, higher quotas).
Update .env with key.

Features:
- Compliance Analysis: Document analysis against regulatory standards
- Lead Generation: Company and contact research for MedTech companies
- News Search: AI-powered query generation for MedTech industry news

Code: core/chat.py (compliance, study design calls), gui/interface.py (lead generation, news search).
Notes: Commercial use allowed per ToS; verify at https://x.ai/grok.

LinkedIn APIs (Share, Sign In, Community Management)

Purpose: Posts content, authenticates users, manages NaviSure's LinkedIn page.
Endpoints:
Share: https://api.linkedin.com/v2/ugcPosts (w_member_social).
Sign In: https://api.linkedin.com/v2/me (r_liteprofile).
Community: https://api.linkedin.com/v2/socialActions (r_organization_social).

Authentication: OAuth token (LINKEDIN_ACCESS_TOKEN) in .env.
Setup:
Apply at https://www.linkedin.com/developers.
Create app, request Marketing Developer Platform access.
Update .env with token.

Code: gui/interface.py (Leads Tab, page posts).
Notes: US accounts can't use Member Data Portability; buyer must reapply for access.

AssemblyAI

Purpose: Transcribes client meetings with speaker-separated output.
Endpoints: https://api.assemblyai.com/v2/transcript.
Authentication: API key (ASSEMBLYAI_API_KEY) in .env.
Setup:
Register at https://www.assemblyai.com.
Obtain API key (~$0.10–$0.50/hour audio).
Update .env.

Code: gui/interface.py (Meeting Transcription Tab).
Notes: ToS allows commercial use; verify at https://www.assemblyai.com/terms.

Google Calendar API

Purpose: Fetches calendar events for dashboard schedule display.
Endpoints: https://www.googleapis.com/calendar/v3.
Authentication: OAuth2 credentials via client_secret.json and token files.
Setup:
Configure Google Cloud Console project
Enable Calendar API
Download credentials to config/client_secret.json
Generate token via OAuth2 flow

Code: core/data_fetch.py (get_calendar_events)
Notes: Used for dashboard schedule display with auto-refresh functionality.

Dropbox API

Purpose: File storage, indexing, and management for workspace documents.
Endpoints: https://api.dropboxapi.com/2.
Authentication: Access token (DROPBOX_ACCESS_TOKEN) in .env.
Setup:
Create Dropbox app at https://www.dropbox.com/developers
Generate access token
Update .env with token

Code: core/api.py, core/index_dropbox.py
Notes: Used for document workspace, file preview, and storage integration.

Notes

API keys are stored in .env, not hardcoded, ensuring GDPR/HIPAA compliance.
Buyers must secure their own API keys due to non-transferable ToS.
Transition support (30–60 days) recommended for buyer setup.
Review ToS for commercial use and transfer policies before sale.
All API integrations are currently functional and tested in the application.

