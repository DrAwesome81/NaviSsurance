NaviSsurance API Integrations
Overview
NaviSsurance uses third-party APIs for core functionality: xAI Grok (compliance, study design), Anthropic Claude 3.7 Sonnet (lead generation), LinkedIn (posting, authentication), and AssemblyAI (transcription). API keys are non-transferable; buyers must register their own accounts.
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

Anthropic Claude 3.7 Sonnet

Purpose: Generates lead JSON ({name, company, title, LinkedIn_url, rationale}) for AI SaMD/IVD companies.
Endpoints: https://api.anthropic.com/v1/messages.
Authentication: API key (ANTHROPIC_API_KEY) in .env.
Setup:
Register at https://www.anthropic.com/api.
Obtain API key (~$50–$200/project).
Update .env.


Code: interface.py (Leads Tab).
Notes: Non-transferable key; contact support@anthropic.com for ToS.

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

