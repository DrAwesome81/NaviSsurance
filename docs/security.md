NaviSsurance Security
Overview
NaviSsurance implements security measures to protect client data and API integrations, ensuring compliance with GDPR (EU clients) and HIPAA (US health data). These practices safeguard leads, compliance results, and documents, supporting sale preparation.
Data Protection

Encryption: Client data in crm.py (SQLite) uses AES-256 encryption for leads, compliance results, and emails. Workspaces (data/clients/[client_name]) store SOPs/PDFs with file-level encryption.
Storage: Data resides locally at C:/Users/adamo/Dropbox/_Consulting/NaviSsurance/data, synced to Dropbox with end-to-end encryption.
GDPR Compliance: EU client data (e.g., leads) is processed with consent, anonymized for transfer, and deletable on request.
HIPAA Compliance: US health data (e.g., SOPs) is encrypted, access-controlled, and audit-logged in logs/.

API Security

Key Management: API keys (Grok, LinkedIn, AssemblyAI) are stored in .env, not hardcoded, and rotated every 90 days.
Access: Keys are accessible only to the local application (interface.py, chat.py), with no external exposure.
ToS Compliance: API usage adheres to provider terms (e.g., https://x.ai/grok), ensuring commercial use and no key sharing.

Access Controls

Local Server: NaviSsurance runs on a password-protected Windows machine (Ryzen 7900X, 64 GB RAM).
User Access: Single-user access (consultant) via UI (interface.py), with no multi-user support.
Audit Logs: Actions (e.g., data access, API calls) logged in C:/Users/adamo/Dropbox/_Consulting/NaviSsurance/logs.

Sale Considerations

Data Transfer: Client data transfers require consent (GDPR, HIPAA) and anonymization, per sale contract.
API Keys: Non-transferable; buyers must register own keys (api.md).
Transition: 30–60 days support for buyer security setup (e.g., .env configuration).

Notes

Security practices align with MedTech standards, verified by client contracts.
Consult a lawyer for GDPR/HIPAA compliance before sale.

