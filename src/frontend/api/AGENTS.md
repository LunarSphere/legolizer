# AGENTS.md — `src/frontend/api/`

Contract directory for the local REST API consumed by the studio.

Parent: [../AGENTS.md](../AGENTS.md) · Root: [../../../AGENTS.md](../../../AGENTS.md)

## Contents

- `openapi.json` — OpenAPI 3.1 description of `/api/v1` (builds, jobs, assets).

Implementation lives in `src/legolizer/server.py`. Client: `../src/api.js`.

## Conventions

- Treat `openapi.json` as the shared source of truth for request/response
  shapes, status codes, and `Idempotency-Key` behavior.
- Any change to routes, bodies, or asset allowlists must update:
  1. `src/legolizer/server.py`
  2. this `openapi.json`
  3. `src/frontend/src/api.js` (and UI callers if fields change)
- Do not document remote multi-user auth here; the server is loopback-only
  until that product decision lands (file an issue if proposing deployable
  hosting).

## Agent backlog

_(none yet)_
