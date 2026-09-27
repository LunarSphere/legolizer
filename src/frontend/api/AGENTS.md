# AGENTS.md — `src/frontend/api/`

Contract directory for the local REST API consumed by the studio.

Parent: [../AGENTS.md](../AGENTS.md) · Root: [../../../AGENTS.md](../../../AGENTS.md)

## Contents

- `openapi.json` — OpenAPI 3.1 description of `/api/v1` (builds, jobs, assets).

Implementation lives in `src/legolizer/server.py`. Client: `../src/api.js`.

## Conventions

- Inherit root [AGENTS.md](../../../AGENTS.md): minimal comments; update this
  file in the same change when the contract or sync checklist changes.
- Treat `openapi.json` as the shared source of truth for request/response
  shapes, status codes, and `Idempotency-Key` behavior.
- Any change to routes, bodies, or asset allowlists must update:
  1. `src/legolizer/server.py`
  2. this `openapi.json`
  3. `src/frontend/src/api.js` (and UI callers if fields change)
- The same contract is served locally and by the deployed demo (Vercel function +
  `aws` backend; see `src/infra/README.md`). There is no user auth yet; do not
  document one until that product decision lands.

## Agent backlog

- #16 — Refresh AGENTS.md guides (filed 2026-09-26) — see root AGENTS.md
