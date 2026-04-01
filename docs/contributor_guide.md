# NaviSsurance Contributor Guide

Last updated: 2026-04-01

## Purpose
This short guide explains where the current source of truth lives in the repo so contributors do not accidentally follow stale historical plans or older architectural descriptions.

## Source Of Truth Order
When multiple files appear to disagree, use this order:

1. **Code**
   - The running implementation is the final truth.
   - Start with:
     - `main.py`
     - `config.py`
     - `core/main_chat_router.py`
     - `core/chief_of_staff_service.py`
     - `core/db.py`
     - `core/tool_registry.py`
     - `core/runtime/`
     - `api/app.py`

2. **Current architecture and status docs**
   - `docs/overview.md`
   - `docs/design.md`
   - `docs/api.md`

3. **Roadmap and backlog**
   - `docs/roadmap_status.md` for roadmap classification
   - `TODO.md` for active remaining work

4. **Testing / operational guidance**
   - `docs/testing.md`
   - `docs/user_manual.md`

5. **Historical plans**
   - Older plan files under `C:\Users\adamo\.cursor\plans\`
   - Treat these as history/spec/reference unless `docs/roadmap_status.md` or `TODO.md` explicitly says they are still active

## How To Read The Repo

### If you want current product scope
Read:
- `docs/overview.md`
- `docs/user_manual.md`

### If you want architecture
Read:
- `docs/design.md`
- `docs/api.md`

### If you want current remaining work
Read:
- `TODO.md`
- `docs/roadmap_status.md`

### If you want to validate changes
Read:
- `docs/testing.md`

## Historical Plan Guidance
Many older plan files were written before:
- the runtime scheduler
- the local API
- the browser tools
- the optional Telegram adapter scaffolding
- the current memory/retrieval layering

Because of that, some older plans:
- describe gaps that are now partially or fully closed
- duplicate each other
- belong to side directions that are no longer core to NaviSsurance

Current product-direction note:
- the built-in desktop chat is the intended user chat surface
- remote chat integrations are not part of the active roadmap unless explicitly revived later

Before using an older plan:
1. Check `docs/roadmap_status.md`
2. Check `TODO.md`
3. Verify against the current code

## Update Rule
When making meaningful architectural or product changes:
- update the code first
- then update:
  - `docs/overview.md`
  - `docs/design.md`
  - `docs/api.md`
  - `docs/testing.md` if the validation path changed
  - `docs/roadmap_status.md` if roadmap classification changed
  - `TODO.md` if the remaining work changed

## Practical Principle
Do not treat an unchecked paragraph in an old plan as active work by default.

Treat current work as active only if it is reflected in:
- current code,
- `TODO.md`,
- or `docs/roadmap_status.md`.
