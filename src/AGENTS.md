# AGENTS.md — `src/`

Source root. Two siblings, separate stacks:

| Directory | Stack | Guide |
| --- | --- | --- |
| [`legolizer/`](legolizer/AGENTS.md) | Python 3.12+ package (CLI + HTTP API + geometry) | [AGENTS.md](legolizer/AGENTS.md) |
| [`frontend/`](frontend/AGENTS.md) | React 19 + Vite 8 + Three.js studio UI | [AGENTS.md](frontend/AGENTS.md) |

## Boundaries

- Python package path is `src/legolizer` (hatch wheel packages only that tree).
  Imports are `from legolizer.<module> import …`.
- Frontend never embeds provider API keys; it talks to `legolizer.server` over
  `/api/v1` (or serves static `/demo` when `VITE_DEMO=true`).
- Do not move shared logic into a third top-level package without updating root
  and nested `AGENTS.md` files in the **same** change and the PR description.
- Inherit root [AGENTS.md](../AGENTS.md): minimal comments; sync this guide when
  agent-relevant layout or boundaries change.

## Parent / children

- Parent: [../AGENTS.md](../AGENTS.md) (governing rules).
- Children: `legolizer/`, `frontend/`.

## Agent backlog

- #16 — Refresh AGENTS.md guides (filed 2026-09-26) — see root AGENTS.md
