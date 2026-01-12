# Vikunja (local dev)

This folder contains a **local, single-user Vikunja** setup for development/testing.

## Start

From the repo root:

```powershell
cd vikunja
docker compose up -d
```

Then open:
- `http://localhost:3456` (UI)
- `http://localhost:3456/api/v1/docs` (API docs)

## Stop

```powershell
cd vikunja
docker compose down
```

## Data persistence

Data is persisted in:
- `vikunja/db/` (SQLite DB)
- `vikunja/files/` (uploads)

These folders are ignored by git.


