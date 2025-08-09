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

Purpose: Analyzes SOPs for compliance (ISO 13485, 21 CFR 820) and generates study protocols, outputting JSON ([{section, issue, fix, reference}]).
Endpoints: https://api.x.ai/grok (REST API).
Authentication: API key (GROK_API_KEY) in .env.
Setup:
Register at https://x.ai/api.
Obtain SuperGrok subscription (~$20–$100/month, higher quotas).
Update .env with key.


Code: chat.py (compliance, study design calls).
Notes: Commercial use allowed per ToS; verify at https://x.ai/grok.

# Claude API removed - now using Grok 4 API for lead generation

LinkedIn APIs (Share, Sign In, Community Management)

Purpose: Posts content, authenticates users, manages NaviSure’s LinkedIn page.
Endpoints:
Share: https://api.linkedin.com/v2/ugcPosts (w_member_social).
Sign In: https://api.linkedin.com/v2/me (r_liteprofile).
Community: https://api.linkedin.com/v2/socialActions (r_organization_social).


Authentication: OAuth token (LINKEDIN_ACCESS_TOKEN) in .env.
Setup:
Apply at https://www.linkedin.com/developers.
Create app, request Marketing Developer Platform access.
Update .env with token.


Code: interface.py (Leads Tab, page posts).
Notes: US accounts can’t use Member Data Portability; buyer must reapply for access.

AssemblyAI

Purpose: Transcribes client meetings with speaker-separated output.
Endpoints: https://api.assemblyai.com/v2/transcript.
Authentication: API key (ASSEMBLYAI_API_KEY) in .env.
Setup:
Register at https://www.assemblyai.com.
Obtain API key (~$0.10–$0.50/hour audio).
Update .env.


Code: interface.py (lines 248–312).
Notes: ToS allows commercial use; verify at https://www.assemblyai.com/terms.

Notes

API keys are stored in .env, not hardcoded, ensuring GDPR/HIPAA compliance.
Buyers must secure their own API keys due to non-transferable ToS.
Transition support (30–60 days) recommended for buyer setup.
Review ToS for commercial use and transfer policies before sale.

