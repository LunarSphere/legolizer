# AGENTS.md — `src/frontend/`

**Legolizer Studio**: React 19 + Vite 7 + Three.js SPA for viewing packed LDraw
models, generating builds via the local Python API, and browsing parts/PDF.

Human runbook: [README.md](README.md). Parent: [../AGENTS.md](../AGENTS.md).
Root rules: [../../AGENTS.md](../../AGENTS.md).

## Layout

| Path | Guide | Contents |
| --- | --- | --- |
| [`src/`](src/AGENTS.md) | yes | App components, API client, CSS |
| [`api/`](api/AGENTS.md) | yes | OpenAPI 3.1 contract (`openapi.json`) |
| [`public/`](public/AGENTS.md) | yes | Static assets; bundled demo |
| [`scripts/`](scripts/AGENTS.md) | yes | `prepare_demo.py` |

Root files here: `index.html`, `vite.config.js` (`/api` → `127.0.0.1:8000`),
`package.json` (Node `>=22.12`), `eslint.config.js`, `.env.example`.
CI runs `npm run lint` and `npm run build` on every PR.

## Run

```sh
# terminal 1 (repo root)
uv run python -m legolizer.server

# terminal 2
cd src/frontend
npm ci
npm run dev -- --port 5173 --strictPort
```

Quality gate (also CI): `npm run lint` and `npm run build`.

Demo-only (no server): `VITE_DEMO=true` in `.env.local`.

## Conventions

- Inherit root [AGENTS.md](../../AGENTS.md): minimal comments (non-narrative;
  only when code is unclear); update this file in the same change when layout,
  run steps, or studio constraints shift.
- Small surface: no router, no global state library—`useState` / `useEffect`
  only. Prefer editing existing components over new frameworks.
- All HTTP goes through `src/api.js`. Never put secrets in `VITE_*`.
- One stylesheet: `src/styles.css` (design tokens on `:root`).
- Packed MPD + `LDConfig.ldr` are required for WebGL; do not point the loader at
  a remote parts library.
- Keep CORS/security assumptions: API is trusted loopback only.

## Performance

UX and frame rate matter. File issues for: perpetual 4s job polling, continuous
WebGL render loop when idle, large `packed.mpd` parse cost, N thumbnails without
virtualization, Google Fonts `@import` on first paint. Do not mix unrelated
perf PRs into feature work—see root governing rules.

## Agent backlog

- #16 — Refresh AGENTS.md guides (filed 2026-09-26) — see root AGENTS.md
- #12 — Assembly video (filed 2026-09-26)
- #8 — Vercel hosting (filed 2026-09-26)
- #7 — Published model gallery (filed 2026-09-26)
- #5 — Reprompt / generative infill on a region (filed 2026-09-26)
- #3 — Augmented reality mode (mobile) (filed 2026-09-26)
