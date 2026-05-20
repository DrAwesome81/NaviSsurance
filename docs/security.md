# NaviSsurance Security

Last updated: 2026-05-12

<!-- Pulse private memory visibility + Shield Security/Compliance surface awareness -->

## Overview
NaviSsurance is a local-first desktop application with optional local runtime and local HTTP service components. Security posture is therefore centered on:
- protecting local secrets and tokens
- avoiding secret leakage in logs and source code
- limiting remote exposure
- keeping durable data auditable in SQLite and local artifact storage

This document describes the current implementation posture. It does not certify regulatory or legal compliance on its own.

## Current Security Model

### Local-first storage
- Primary state is stored locally in SQLite through `core/db.py`.
- Artifacts are written to local paths under the configured artifacts directory.
- Secrets and credentials should remain in local environment/config files rather than committed source.

### Logging and secret handling
- The app uses centralized logging from `main.py`.
- Sensitive tokens, credentials, and auth material should not be logged directly.
- See the more implementation-specific security notes in the repository-level `SECURITY.md`.

### API and channel exposure
- The local FastAPI surface is optional and controlled from **Settings → App preferences** (SQLite `app_settings`). Legacy `NAVI_LOCAL_API_*` environment variables may seed those keys once via `core.app_preferences.migrate_legacy_env_preferences()`.
- Telegram scaffolding exists in the repo but remote chat is not part of the intended current product surface.
- These integrations should remain disabled unless actively needed.

## Third-Party Credential Handling
- API keys should be stored in environment/config files, not hardcoded.
- Non-transferable provider accounts should be treated as buyer/operator-managed in any sale or handoff scenario.
- Review provider terms separately for production and commercial use.

## Operational Controls
- NaviSsurance is currently designed as a single-user local application.
- There is no general multi-user permission system.
- Retrieved text and external content should be treated as untrusted reference material.
- Browser automation may create screenshots and evidence artifacts; review local storage and retention accordingly.

## Data and Compliance Notes
- This repository contains workflows that may process sensitive client, regulatory, and operational information.
- Legal/compliance obligations such as GDPR, HIPAA, and client-contract requirements depend on deployment practices, data handling, retention, and operator behavior, not on documentation alone.
- Do not treat this document as a formal compliance certification.

<!-- Pulse private memory + Shield triage surface -->

